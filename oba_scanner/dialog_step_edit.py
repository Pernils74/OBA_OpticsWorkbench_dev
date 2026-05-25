# -*- coding: utf-8 -*-

# dialog_step_edit.py

import os
import datetime
import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtWidgets, QtGui, QtCore


# ------------------------------------------------------------
# STEP EDIT DIALOG
# ------------------------------------------------------------
class StepEditDialog(QtWidgets.QDialog):
    def __init__(self, parent=None):
        super().__init__(parent or Gui.getMainWindow())
        self.setWindowTitle("Edit Step")

        layout = QtWidgets.QVBoxLayout(self)

        # --------------------------------------------------------
        # Scan document
        # --------------------------------------------------------
        self._scan_doc_for_objects()

        # --------------------------------------------------------
        # ID
        # --------------------------------------------------------
        unique_id = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        form = QtWidgets.QFormLayout()
        self.editID = QtWidgets.QLineEdit(unique_id)
        form.addRow("ID:", self.editID)
        layout.addLayout(form)

        # --------------------------------------------------------
        # Active
        # --------------------------------------------------------
        self.chkActive = QtWidgets.QCheckBox("Active")
        self.chkActive.setChecked(True)
        layout.addWidget(self.chkActive)

        # --------------------------------------------------------
        # Move targets
        # --------------------------------------------------------
        common_items = ["none"] + self._beams + self._bodies + self._compounds + self._features

        form = QtWidgets.QFormLayout()
        self.move = QtWidgets.QComboBox()
        self.move1 = QtWidgets.QComboBox()
        self.move2 = QtWidgets.QComboBox()

        for cb in (self.move, self.move1, self.move2):
            cb.addItems(common_items)

        for cb in (self.move, self.move1, self.move2):
            self._decorate_target_combobox(cb)

        form.addRow("Move target:", self.move)
        form.addRow("Move target 1:", self.move1)
        form.addRow("Move target 2:", self.move2)
        layout.addLayout(form)

        # --------------------------------------------------------
        # Plane
        # --------------------------------------------------------
        form = QtWidgets.QFormLayout()
        self.plan = QtWidgets.QComboBox()
        self.plan.addItems(["XY", "XZ", "YZ"])
        form.addRow("Plane:", self.plan)
        layout.addLayout(form)

        # --------------------------------------------------------
        # Sweep parameters
        # --------------------------------------------------------
        form = QtWidgets.QFormLayout()

        self.angle = QtWidgets.QSpinBox()
        self.angle.setRange(1, 360)
        self.angle.setValue(8)

        self.rf = QtWidgets.QDoubleSpinBox()
        self.rf.setRange(0, 9999)
        self.rf.setDecimals(4)

        self.rt = QtWidgets.QDoubleSpinBox()
        self.rt.setRange(0, 9999)
        self.rt.setDecimals(4)
        self.rt.setValue(0.4)

        self.rs = QtWidgets.QSpinBox()
        self.rs.setRange(1, 2000)
        self.rs.setValue(4)

        self.rotAxis = QtWidgets.QComboBox()
        self.rotAxis.addItems(["X", "Y", "Z"])

        self.rotAngle = QtWidgets.QDoubleSpinBox()
        self.rotAngle.setRange(0, 360)
        self.rotAngle.setDecimals(1)

        form.addRow("Angle step:", self.angle)
        form.addRow("From radius:", self.rf)
        form.addRow("To radius:", self.rt)
        form.addRow("Radius steps:", self.rs)
        form.addRow("Rotation axis:", self.rotAxis)
        form.addRow("Rotation (°):", self.rotAngle)
        layout.addLayout(form)

        # --------------------------------------------------------
        # Buttons
        # --------------------------------------------------------
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        layout.addWidget(buttons)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)

        # Plane → rotation axis
        self.plan.currentTextChanged.connect(self._on_plan_changed)
        self._on_plan_changed(self.plan.currentText())

    # ------------------------------------------------------------
    # Accept with validation ✅
    # ------------------------------------------------------------
    def _on_accept(self):
        if self.move.currentText() == "none" and self.move1.currentText() == "none" and self.move2.currentText() == "none":
            QtWidgets.QMessageBox.warning(self, "No valid target selected", "You must select at least one object:\n\n" "• Move target\n" "• Move target 1\n" "• Move target 2")
            return  # 🔴 Stop accept

        self.accept()

    # ------------------------------------------------------------
    # Plane changed
    # ------------------------------------------------------------
    def _on_plan_changed(self, plan):
        if plan:
            self.rotAxis.setCurrentText(plan[0])

    # ------------------------------------------------------------
    # Export values
    # ------------------------------------------------------------
    def values(self):
        return (
            self.editID.text().strip(),
            self.chkActive.isChecked(),
            self.plan.currentText(),
            self.move.currentText(),
            self.move1.currentText(),
            self.move2.currentText(),
            self.angle.value(),
            self.rf.value(),
            self.rt.value(),
            self.rs.value(),
            self.rotAxis.currentText(),
            self.rotAngle.value(),
        )

        # ------------------------------------------------------------
        # Decoration for combo box selections
        # ------------------------------------------------------------

    def _decorate_target_combobox(self, cb: QtWidgets.QComboBox):
        """
        Add icons and colors to items in a Move-target combobox
        based on object classification.
        """
        # Icon paths
        base_path = os.path.join(os.path.dirname(__file__), "..", "icons")

        beam_icon = QtGui.QIcon(os.path.join(base_path, "oba_beam.svg"))
        body_icon = QtGui.QIcon("icons:PartDesign_Body.svg")
        compound_icon = QtGui.QIcon("icons:Part_Compound.svg")
        feature_icon = QtGui.QIcon("icons:Part_Feature.svg")

        model = cb.model()

        for i in range(cb.count()):
            txt = cb.itemText(i)

            # -------- Icons --------
            if txt in self._beams:
                cb.setItemIcon(i, beam_icon)
            elif txt in self._bodies:
                cb.setItemIcon(i, body_icon)
            elif txt in self._compounds:
                cb.setItemIcon(i, compound_icon)
            elif txt in self._features:
                cb.setItemIcon(i, feature_icon)

            # -------- Colors --------
            it = model.item(i)
            if not it:
                continue

            if txt in self._beams:
                it.setForeground(QtGui.QBrush(QtGui.QColor("blue")))
            elif txt in self._bodies:
                it.setForeground(QtGui.QBrush(QtGui.QColor("green")))
            elif txt in self._compounds:
                it.setForeground(QtGui.QBrush(QtGui.QColor("purple")))
            elif txt in self._features:
                it.setForeground(QtGui.QBrush(QtGui.QColor("steelblue")))

        # ------------------------------------------------------------
        # Scan document for beams and bodies
        # ------------------------------------------------------------

    def _scan_doc_for_objects(self):
        """
        Fills:
          self._beams     -> Part::FeaturePython with OpticalType == "Beam"
          self._bodies    -> PartDesign::Body objects
          self._compounds -> Part::Feature with ShapeType Compound / CompSolid
          self._features  -> Part::Feature (non-beam, non-body, non-compound)

        The scan is recursive across the entire document hierarchy:
        Groups, Parts, Links, LinkGroups.
        """

        self._beams = []
        self._bodies = []
        self._compounds = []
        self._features = []

        doc = App.ActiveDocument
        if not doc:
            return

        seen = set()
        beams = set()
        bodies = set()
        compounds = set()
        features = set()

        # ------------------------------------------------------------
        # Classification helpers
        # ------------------------------------------------------------
        def is_beam(obj) -> bool:
            """
            Beam:
            Part::FeaturePython with OpticalType == "Beam"
            """
            try:
                return obj.TypeId == "Part::FeaturePython" and hasattr(obj, "OpticalType") and isinstance(obj.OpticalType, str) and obj.OpticalType.lower() == "beam"
            except Exception:
                return False

        def is_body(obj) -> bool:
            """
            PartDesign Body
            """
            try:
                return obj.isDerivedFrom("PartDesign::Body")
            except Exception:
                return False

        def is_compound(obj) -> bool:
            """
            Part::Feature with ShapeType Compound or CompSolid
            """
            try:
                if obj.TypeId != "Part::Feature":
                    return False

                shp = getattr(obj, "Shape", None)
                return bool(shp and not shp.isNull() and shp.ShapeType in ("Compound", "CompSolid"))
            except Exception:
                return False

        def is_feature(obj) -> bool:
            """
            Plain Part::Feature which is NOT:
            - Beam
            - Body
            - Compound
            """
            try:
                return obj.TypeId == "Part::Feature" and not is_beam(obj) and not is_body(obj) and not is_compound(obj)
            except Exception:
                return False

        # ------------------------------------------------------------
        # Hierarchy traversal
        # ------------------------------------------------------------
        def iter_children(obj):
            children = []

            try:
                grp = getattr(obj, "Group", None)
                if grp:
                    children.extend(list(grp))
            except Exception:
                pass

            try:
                lnks = getattr(obj, "Links", None)
                if lnks:
                    children.extend(list(lnks))
            except Exception:
                pass

            try:
                lnk = getattr(obj, "LinkedObject", None)
                if lnk:
                    children.append(lnk)
                    lgrp = getattr(lnk, "Group", None)
                    if lgrp:
                        children.extend(list(lgrp))
            except Exception:
                pass

            uniq = []
            seen_ptrs = set()
            for ch in children:
                if ch and id(ch) not in seen_ptrs:
                    uniq.append(ch)
                    seen_ptrs.add(id(ch))

            return uniq

        # ------------------------------------------------------------
        # Recursive walk
        # ------------------------------------------------------------
        def walk(obj):
            oid = id(obj)
            if oid in seen:
                return
            seen.add(oid)

            try:
                if is_beam(obj):
                    beams.add(obj.Label)
                elif is_body(obj):
                    bodies.add(obj.Label)
                elif is_compound(obj):
                    compounds.add(obj.Label)
                elif is_feature(obj):
                    features.add(obj.Label)
            except Exception:
                pass

            for ch in iter_children(obj):
                walk(ch)

        # ------------------------------------------------------------
        # Start from all top-level objects
        # ------------------------------------------------------------
        for root in doc.Objects:
            walk(root)

        # Store sorted lists (stable UI)
        self._beams = sorted(beams)
        self._bodies = sorted(bodies)
        self._compounds = sorted(compounds)
        self._features = sorted(features)
