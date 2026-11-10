from PySide import QtWidgets


class OBADialogBuilder:
    def __init__(self, dlg, obj, layout):
        self.dlg = dlg
        self.obj = obj
        self.layout = layout

    def build_shape(self):
        from . import oba_optical_shapes

        box = QtWidgets.QGroupBox("Geometry")
        lay = QtWidgets.QVBoxLayout(box)

        for p in oba_optical_shapes.SHAPE_PROPERTIES.get(str(self.obj.ShapeType), []):
            row = create_widget(self.dlg, self.obj, p["name"])
            if row:
                lay.addLayout(row)

        self.layout.addWidget(box)

    def build_placement(self):
        box = QtWidgets.QGroupBox("Placement (Expression Engine)")
        lay = QtWidgets.QVBoxLayout(box)
        for name in ("WorldX", "WorldY", "WorldZ", "RotX", "RotY", "RotZ"):
            row = create_widget(self.dlg, self.obj, name)
            if row:
                lay.addLayout(row)
        self.layout.addWidget(box)

    def build_module(self, mod):
        if not mod:
            return
        if hasattr(mod, "build_dialog"):
            mod.build_dialog(self.dlg, self.obj, self.layout)
            return
        self._build_properties("Optical", getattr(mod, "EXTRA_PROPERTIES", []))

    def build_behaviour(self, behaviour):
        if behaviour:
            self._build_properties(
                "Optical behaviour",
                getattr(behaviour, "OPTICAL_PROPERTIES", []),
            )

    def _build_properties(self, title, properties):
        box = QtWidgets.QGroupBox(title)
        lay = QtWidgets.QVBoxLayout(box)
        for p in properties:
            row = create_widget(self.dlg, self.obj, p["name"])
            if row:
                lay.addLayout(row)
        if lay.count():
            self.layout.addWidget(box)
        else:
            box.deleteLater()


import FreeCADGui as Gui


def _add_spin(self, label, prop, mn, mx, unit, layout, step=1.0):
    w = Gui.UiLoader().createWidget("Gui::QuantitySpinBox")
    w.setProperty("minimum", mn)
    w.setProperty("maximum", mx)
    w.setProperty("unit", unit)
    w.setProperty("singleStep", step)
    w.setProperty("rawValue", float(getattr(self.obj, prop)))
    w.setProperty("binding", f"{self.obj.Name}.{prop}")
    layout.addRow(label, w)
    return w


def create_widget(dlg, obj, prop):
    if prop not in obj.PropertiesList:
        return None

    ptype = obj.getTypeIdOfProperty(prop).lower()
    value = getattr(obj, prop)
    row = QtWidgets.QHBoxLayout()
    row.addWidget(QtWidgets.QLabel(prop))

    # print([ptype], ptype)

    if "bool" in ptype:
        widget = QtWidgets.QCheckBox()
        widget.setChecked(bool(value))
        widget.toggled.connect(lambda v, p=prop: dlg._on_change(p, v))

    elif "enumeration" in ptype:
        widget = QtWidgets.QComboBox()
        widget.addItems(list(obj.getEnumerationsOfProperty(prop)))
        widget.setCurrentText(str(value))
        widget.currentTextChanged.connect(lambda v, p=prop: dlg._on_change(p, v))

    elif "string" in ptype:
        widget = QtWidgets.QLineEdit(str(value))
        widget.textChanged.connect(lambda v, p=prop: dlg._on_change(p, v))

    elif "length" in ptype:
        widget = Gui.UiLoader().createWidget("Gui::QuantitySpinBox")
        widget.setProperty("rawValue", float(getattr(obj, prop)))
        widget.setProperty("binding", f"{obj.Name}.{prop}")
        widget.valueChanged.connect(lambda v, p=prop: dlg._on_change(p, widget.property("rawValue")))
    # --------------------------------
    # Angle
    # --------------------------------
    elif "angle" in ptype:
        widget = Gui.UiLoader().createWidget("Gui::QuantitySpinBox")
        widget.setProperty("binding", f"{obj.Name}.{prop}")
        widget.setProperty("unit", "deg")
        widget.setProperty("singleStep", 0.5)
        widget.setProperty("rawValue", float(getattr(obj, prop)))
        widget.valueChanged.connect(lambda v, p=prop: dlg._on_change(p, widget.property("rawValue")))

    elif "float" in ptype:
        widget = Gui.UiLoader().createWidget("Gui::QuantitySpinBox")
        widget.setProperty("binding", f"{obj.Name}.{prop}")
        widget.setProperty("singleStep", 0.5)
        widget.setProperty("rawValue", float(getattr(obj, prop)))
        widget.valueChanged.connect(lambda v, p=prop: dlg._on_change(p, widget.property("rawValue")))

    elif "integer" in ptype:
        widget = QtWidgets.QSpinBox()
        widget.setRange(-2147483647, 2147483647)
        widget.setValue(int(value))
        widget.valueChanged.connect(lambda v, p=prop: dlg._on_change(p, v))

    else:
        return None

    row.addWidget(widget)
    if hasattr(dlg, "_spinboxes"):
        dlg._spinboxes[prop] = widget
    return row
