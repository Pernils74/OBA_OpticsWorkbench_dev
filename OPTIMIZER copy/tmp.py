
    # -------------------------------------------------------
    # SLIDERS (FULL)
    # -------------------------------------------------------



def _build_dynamic_sliders(self, root):
        grp = QtWidgets.QGroupBox("Målvikter")
        vbox = QtWidgets.QVBoxLayout(grp)

        self.sliderContainer = QtWidgets.QVBoxLayout()

        vbox.addLayout(self.sliderContainer)

        # add button
        self.btnAddMetric = QtWidgets.QPushButton("+ Lägg till metric")
        self.btnAddMetric.clicked.connect(self._add_slider_row)

        vbox.addWidget(self.btnAddMetric)

        root.addWidget(grp)

        # default rows
        for metric in [
            "cluster_count",
            "density",
            "roundness",
            "equal_distance",
        ]:
            self._add_slider_row(metric)

    def _add_slider_row(self, metric=None):
        metrics = [
            "cluster_count",
            "density",
            "roundness",
            "equal_distance",
        ]

        row = SliderRow(metrics, self)
        if metric:
            idx = row.cmb.findText(metric)
            if idx >= 0:
                row.cmb.setCurrentIndex(idx)
        row.changed.connect(self._update_dynamic_weights)
        row.removed.connect(self._remove_slider_row)
        row.targetsRequested.connect(self._edit_row_targets)
        self.sliderRows.append(row)
        self.sliderContainer.addWidget(row)
        self._update_dynamic_weights()

    def _remove_slider_row(self, row):
        self.sliderRows.remove(row)
        row.setParent(None)
        row.deleteLater()
        self._update_dynamic_weights()

    def _update_dynamic_weights(self):
        raws = []
        for row in self.sliderRows:
            metric, val = row.get_value()
            raws.append((row, metric, val))

        total = sum(v for _, _, v in raws)
        if total <= 0:
            total = 1e-6
        normalized = {}
        for row, metric, val in raws:
            norm = val / total
            normalized[metric] = norm
            # 🔥 visar både raw och normalized
            row.set_values(val / 100.0, norm)
        # statusrad
        txt = " | ".join(f"{m}:{w:.2f}" for m, w in normalized.items())
        self.lblWeights.setText(txt)
        self._pending_weights = normalized
        if self._running:
            self._slider_timer.start(120)

    def _edit_row_targets(self, row):
        doc = App.ActiveDocument
        if not doc:
            return
        available = ["ALL"]
        for obj in doc.Objects:
            if hasattr(obj, "OpticalType"):
                available.append(obj.Label)
        dlg = EditTargetsDialog(
            self,
            row.get_metric_key(),
            available,
            row.get_targets(),
        )
        if dlg.exec_():
            selected = dlg.selected_targets() or ["ALL"]
            row.set_targets(selected)
            # 🔥 live update worker
            if self._running and self._worker:
                self.pauseRequested.emit()
                self._worker.update_metric_targets(
                    row.get_metric_key(),
                    selected,
                )
                self.resumeRequested.emit()






    #
    #

    def _build_sliders(self, root):
        grp = QtWidgets.QGroupBox("Målvikter")
        grid = QtWidgets.QGridLayout()

        def make_row(metric_key, label, row):
            lbl = QtWidgets.QLabel(label)

            btnTargets = QtWidgets.QPushButton("ALL")
            btnTargets.setMinimumWidth(100)
            btnTargets.clicked.connect(lambda _, k=metric_key: self._edit_targets(k))

            sld = QtWidgets.QSlider(QtCore.Qt.Horizontal)
            sld.setRange(0, 100)
            sld.setValue(50)

            val = QtWidgets.QLabel("0.25")

            grid.addWidget(lbl, row, 0)
            grid.addWidget(btnTargets, row, 1)
            grid.addWidget(sld, row, 2)
            grid.addWidget(val, row, 3)

            return sld, val, btnTargets

        self.sldCluster, self.lblCluster, self.btnClusterTargets = make_row("cluster_count", "Studs", 0)
        self.sldDensity, self.lblDensity, self.btnDensityTargets = make_row("density", "Densitet", 1)
        self.sldRoundness, self.lblRoundness, self.btnRoundTargets = make_row("roundness", "Rundhet", 2)
        self.sldEqual, self.lblEqual, self.btnEqualTargets = make_row("equal_distance", "Avstånd", 3)

        # self.sldCluster, self.lblCluster = make_row("cluster_count", "Studs", 0)
        # self.sldDensity, self.lblDensity = make_row("density", "Densitet", 1)
        # self.sldRoundness, self.lblRoundness = make_row("roundness", "Rundhet", 2)
        # self.sldEqual, self.lblEqual = make_row("equal_distance", "Avstånd", 3)

        for s in (self.sldCluster, self.sldDensity, self.sldRoundness, self.sldEqual):
            s.valueChanged.connect(self._update_weights)
            s.sliderPressed.connect(self._slider_pressed)
            s.sliderReleased.connect(self._slider_released)

        grp.setLayout(grid)
        root.addWidget(grp)

        for k in self.state.metric_targets.keys():
            self._update_target_button(k)

        self._update_weights()

    # -------------------------------------------------------
    # SLIDER LOGIK (DEBOUNCE + PAUSE)
    # -------------------------------------------------------

    def _slider_pressed(self):
        self.lblStatus.setText("Pause – justerar vikter")
        print("DEBUG: Slider pressed, pausing optimization")
        self._slider_active = True
        self._slider_timer.stop()

        # if self._running:
        #     self.pauseRequested.emit()

    def _slider_released(self):
        self.lblStatus.setText("Kör...")
        print("DEBUG: Slider released, resuming optimization with new weights")
        self._slider_active = False
        self._slider_timer.stop()

        if self._running:
            self.pauseRequested.emit()
            self._emit_weights()
            self.resumeRequested.emit()

    def _update_weights(self):
        d = self.sldDensity.value()
        r = self.sldRoundness.value()
        e = self.sldEqual.value()
        c = self.sldCluster.value()

        S = max(1e-6, d + r + e + c)

        wD, wR, wE, wC = d / S, r / S, e / S, c / S
        self._pending_weights = (wC, wD, wR, wE)

        self.lblDensity.setText(f"{wD:.2f}")
        self.lblRoundness.setText(f"{wR:.2f}")
        self.lblEqual.setText(f"{wE:.2f}")
        self.lblCluster.setText(f"{wC:.2f}")

        self.lblWeights.setText(f"C:{wC:.2f} D:{wD:.2f} R:{wR:.2f} E:{wE:.2f}")

        if self._running and not self._slider_active:
            self._slider_timer.start(120)

    def _emit_weights(self):
        if not self._running:
            return

        wC, wD, wR, wE = self._pending_weights
        self.weightsChanged.emit(wC, wD, wR, wE)




    # -------------------------------------------------------
    # TARGETS (LIVE UPDATE)
    # -------------------------------------------------------

    def _update_target_button(self, metric_key):
        targets = self.state.metric_targets.get(metric_key, ["ALL"])

        if targets == ["ALL"]:
            text = "ALL"
        else:
            text = "; ".join(targets)
            if len(text) > 25:
                text = text[:25] + "..."

        mapping = {
            "cluster_count": getattr(self, "btnClusterTargets", None),
            "density": getattr(self, "btnDensityTargets", None),
            "roundness": getattr(self, "btnRoundTargets", None),
            "equal_distance": getattr(self, "btnEqualTargets", None),
        }

        btn = mapping.get(metric_key)
        if not btn:
            return

        btn.setText(text)

        # ✅ tooltip med full lista
        btn.setToolTip("; ".join(targets))

        # ✅ visuellt highlight om inte ALL
        if targets != ["ALL"]:
            btn.setStyleSheet("background-color:#ffeaa7")
        else:
            btn.setStyleSheet("")

    def _edit_targets(self, metric_key):
        doc = App.ActiveDocument
        if not doc:
            return

        available = ["ALL"]
        for obj in doc.Objects:
            if hasattr(obj, "OpticalType"):
                available.append(obj.Label)

        dlg = EditTargetsDialog(
            self,
            metric_key,
            available,
            self.state.metric_targets.get(metric_key, ["ALL"]),
        )

        if dlg.exec_():
            selected = dlg.selected_targets() or ["ALL"]
            self.state.metric_targets[metric_key] = selected
            self._update_target_button(metric_key)

            if self._running and self._worker:
                self.pauseRequested.emit()
                self._worker.update_metric_targets(metric_key, selected)
                self.resumeRequested.emit()
