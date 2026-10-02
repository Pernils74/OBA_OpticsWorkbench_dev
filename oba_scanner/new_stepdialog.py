# -*- coding: utf-8 -*-

"""Step edit dialog for FreeCAD."""

import datetime
import os

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtGui, QtWidgets


class StepEditDialog(QtWidgets.QDialog):
    """Dialog for creating/editing a step configuration."""

    TARGET_NONE = "none"
    PLANES = ("XY", "XZ", "YZ")
    ROTATION_AXES = ("X", "Y", "Z")
    TARGET_FIELDS = ("move", "move1", "move2")

    TARGET_STYLES = {
        "beam": ("oba_beam.svg", "blue"),
        "body": ("icons:PartDesign_Body.svg", "green"),
        "compound": ("icons:Part_Compound.svg", "purple"),
        "feature": ("icons:Part_Feature.svg", "steelblue"),
    }

    def __init__(self, parent=None):
        super().__init__(parent or Gui.getMainWindow())
        self.setWindowTitle("Edit Step")

        self._scan_doc_for_objects()
        self._build_ui()
        self._connect_signals()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self):
        layout = QtWidgets.QVBoxLayout(self)

        self._build_id_section(layout)
        self._build_active_section(layout)
        self._build_target_section(layout)
        self._build_plane_section(layout)
        self._build_sweep_section(layout)
        self._build_offset_section(layout)
        self._build_buttons(layout)

    def _build_id_section(self, layout):
        form = QtWidgets.QFormLayout()
        unique_id = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")

        self.editID = QtWidgets.QLineEdit(unique_id)
        form.addRow("ID:", self.editID)
        layout.addLayout(form)

    def _build_active_section(self, layout):
        self.chkActive = QtWidgets.QCheckBox("Active")
        self.chkActive.setChecked(True)
        layout.addWidget(self.chkActive)

    def _build_target_section(self, layout):
        form = QtWidgets.QFormLayout()
        items = [self.TARGET_NONE, *self._target_names]

        for field_name, label in zip(
            self.TARGET_FIELDS,
            ("Move target:", "Move target 1:", "Move target 2:"),
        ):
            combo = QtWidgets.QComboBox()
            combo.addItems(items)
            self._decorate_target_combobox(combo)
            setattr(self, field_name, combo)
            form.addRow(label, combo)

        layout.addLayout(form)

    def _build_plane_section(self, layout):
        form = QtWidgets.QFormLayout()

        self.plan = QtWidgets.QComboBox()
        self.plan.addItems(self.PLANES)

        form.addRow("Plane:", self.plan)
        layout.addLayout(form)

    def _build_sweep_section(self, layout):
        form = QtWidgets.QFormLayout()

        self.angle = self._spin_box(1, 360, value=4)
        self.rf = self._double_spin_box(0, 9999, decimals=4)
        self.rt = self._double_spin_box(0, 9999, decimals=4, value=0.4)
        self.rs = self._spin_box(1, 2000, value=6)

        self.rotAxis = QtWidgets.QComboBox()
        self.rotAxis.addItems(self.ROTATION_AXES)

        self.rotAngle = self._double_spin_box(0, 360, decimals=1)

        fields = (
            ("Angle step:", self.angle),
            ("From radius:", self.rf),
            ("To radius:", self.rt),
            ("Radius steps:", self.rs),
            ("Rotation axis:", self.rotAxis),
            ("Rotation (°):", self.rotAngle),
        )
        for label, widget in fields:
            form.addRow(label, widget)

        layout.addLayout(form)

    def _build_offset_section(self, layout):
        form = QtWidgets.QFormLayout()

        self.offX = self._offset_spin_box()
        self.offY = self._offset_spin_box()
        self.offZ = self._offset_spin_box()

        for label, widget in (
            ("Offset X:", self.offX),
            ("Offset Y:", self.offY),
            ("Offset Z:", self.offZ),
        ):
            form.addRow(label, widget)

        layout.addLayout(form)

    def _build_buttons(self, layout):
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    @staticmethod
    def _spin_box(minimum, maximum, value=None):
        widget = QtWidgets.QSpinBox()
        widget.setRange(minimum, maximum)
        if value is not None:
            widget.setValue(value)
        return widget

    @staticmethod
    def _double_spin_box(minimum, maximum, decimals, value=None):
        widget = QtWidgets.QDoubleSpinBox()
        widget.setRange(minimum, maximum)
        widget.setDecimals(decimals)
        if value is not None:
            widget.setValue(value)
        return widget

    @classmethod
    def _offset_spin_box(cls):
        widget = cls._double_spin_box(-1e6, 1e6, decimals=4)
        widget.setSingleStep(0.05)
        return widget

    def _connect_signals(self):
        self.plan.currentTextChanged.connect(self._on_plan_changed)
        self._on_plan_changed(self.plan.currentText())

    # ------------------------------------------------------------------
    # Validation and values
    # ------------------------------------------------------------------

    def _on_accept(self):
        if not self._has_target():
            QtWidgets.QMessageBox.warning(
                self,
                "No valid target selected",
                "You must select at least one object:\n\n" "• Move target\n" "• Move target 1\n" "• Move target 2",
            )
            return

        self.accept()

    def _has_target(self):
        return any(getattr(self, field).currentText() != self.TARGET_NONE for field in self.TARGET_FIELDS)

    def _on_plan_changed(self, plan):
        if plan:
            self.rotAxis.setCurrentText(plan[0])

    def values(self):
        """Return the dialog state in the original tuple order."""
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
            self.offX.value(),
            self.offY.value(),
            self.offZ.value(),
        )

    # ------------------------------------------------------------------
    # Target decoration
    # ------------------------------------------------------------------

    def _decorate_target_combobox(self, combo):
        """Apply the icon and foreground color for each target type."""
        model = combo.model()
        icons_path = os.path.join(os.path.dirname(__file__), "..", "icons")

        icons = {
            "beam": QtGui.QIcon(os.path.join(icons_path, "oba_beam.svg")),
            "body": QtGui.QIcon("icons:PartDesign_Body.svg"),
            "compound": QtGui.QIcon("icons:Part_Compound.svg"),
            "feature": QtGui.QIcon("icons:Part_Feature.svg"),
        }

        for index in range(combo.count()):
            target_type = self._target_type(combo.itemText(index))
            if target_type is None:
                continue

            combo.setItemIcon(index, icons[target_type])

            item = model.item(index)
            if item is not None:
                color = self.TARGET_STYLES[target_type][1]
                item.setForeground(QtGui.QBrush(QtGui.QColor(color)))

    def _target_type(self, label):
        if label in self._beams:
            return "beam"
        if label in self._bodies:
            return "body"
        if label in self._compounds:
            return "compound"
        if label in self._features:
            return "feature"
        return None

    # ------------------------------------------------------------------
    # Document scanning
    # ------------------------------------------------------------------

    def _scan_doc_for_objects(self):
        """Scan the active document and classify reachable objects."""
        self._beams = []
        self._bodies = []
        self._compounds = []
        self._features = []

        doc = App.ActiveDocument
        if not doc:
            self._target_names = []
            return

        seen = set()
        objects = {
            "beam": set(),
            "body": set(),
            "compound": set(),
            "feature": set(),
        }

        def walk(obj):
            object_id = id(obj)
            if object_id in seen:
                return
            seen.add(object_id)

            target_type = self._classify_object(obj)
            if target_type:
                objects[target_type].add(obj.Label)

            for child in self._iter_children(obj):
                walk(child)

        for root in doc.Objects:
            walk(root)

        self._beams = sorted(objects["beam"])
        self._bodies = sorted(objects["body"])
        self._compounds = sorted(objects["compound"])
        self._features = sorted(objects["feature"])

        self._target_names = self._beams + self._bodies + self._compounds + self._features

    @classmethod
    def _classify_object(cls, obj):
        if cls._is_beam(obj):
            return "beam"
        if cls._is_body(obj):
            return "body"
        if cls._is_compound(obj):
            return "compound"
        if cls._is_feature(obj):
            return "feature"
        return None

    @staticmethod
    def _is_beam(obj):
        """Return True for Part::FeaturePython objects marked as beams."""
        try:
            optical_type = getattr(obj, "OpticalType", None)
            return obj.TypeId == "Part::FeaturePython" and isinstance(optical_type, str) and optical_type.lower() == "beam"
        except Exception:
            return False

    @staticmethod
    def _is_body(obj):
        """Return True for PartDesign bodies."""
        try:
            return obj.isDerivedFrom("PartDesign::Body")
        except Exception:
            return False

    @staticmethod
    def _is_compound(obj):
        """Return True for Part::Feature compounds and compsolids."""
        try:
            if obj.TypeId != "Part::Feature":
                return False

            shape = getattr(obj, "Shape", None)
            return bool(shape and not shape.isNull() and shape.ShapeType in ("Compound", "CompSolid"))
        except Exception:
            return False

    @classmethod
    def _is_feature(cls, obj):
        """Return True for plain Part::Feature objects."""
        try:
            return obj.TypeId == "Part::Feature" and not cls._is_beam(obj) and not cls._is_body(obj) and not cls._is_compound(obj)
        except Exception:
            return False

    @staticmethod
    def _iter_children(obj):
        """Return unique children from groups, links and linked objects."""
        children = []

        for attribute in ("Group", "Links"):
            try:
                values = getattr(obj, attribute, None)
                if values:
                    children.extend(values)
            except Exception:
                pass

        try:
            linked_object = getattr(obj, "LinkedObject", None)
            if linked_object:
                children.append(linked_object)

                linked_group = getattr(linked_object, "Group", None)
                if linked_group:
                    children.extend(linked_group)
        except Exception:
            pass

        unique = []
        seen_ids = set()

        for child in children:
            child_id = id(child)
            if child and child_id not in seen_ids:
                seen_ids.add(child_id)
                unique.append(child)

        return unique
