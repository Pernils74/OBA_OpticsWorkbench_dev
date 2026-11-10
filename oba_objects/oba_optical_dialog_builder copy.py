from PySide import QtWidgets


class OBADialogBuilder:

    def __init__(self, dlg, obj, layout):
        self.dlg = dlg
        self.obj = obj
        self.layout = layout

    # -------------------------
    # SHAPE UI
    # -------------------------
    def build_shape(self):
        from . import oba_optical_shapes

        props = oba_optical_shapes.SHAPE_PROPERTIES.get(self.obj.ShapeType, [])

        box = QtWidgets.QGroupBox("Shape")
        lay = QtWidgets.QVBoxLayout(box)

        for p in props:
            row = create_widget(self.dlg, self.obj, p["name"])
            if row:
                lay.addLayout(row)

        self.layout.addWidget(box)

    # -------------------------
    # MODULE UI
    # -------------------------
    def build_module(self, mod):
        if not mod:
            return

        # Override från modul
        if hasattr(mod, "build_dialog"):
            mod.build_dialog(self.dlg, self.obj, self.layout)
            return

        if hasattr(mod, "EXTRA_PROPERTIES"):
            box = QtWidgets.QGroupBox("Optical")
            lay = QtWidgets.QVBoxLayout(box)

            for p in mod.EXTRA_PROPERTIES:
                row = create_widget(self.dlg, self.obj, p["name"])
                if row:
                    lay.addLayout(row)

            self.layout.addWidget(box)

    # -------------------------
    # BEHAVIOUR UI
    # -------------------------
    def build_behaviour(self, beh):
        if not beh or not hasattr(beh, "OPTICAL_PROPERTIES"):
            return

        box = QtWidgets.QGroupBox(self.obj.OpticalModel)
        lay = QtWidgets.QVBoxLayout(box)

        for p in beh.OPTICAL_PROPERTIES:
            row = create_widget(self.dlg, self.obj, p["name"])
            if row:
                lay.addLayout(row)

        self.layout.addWidget(box)


def create_widget(dlg, obj, prop):
    if prop not in obj.PropertiesList:
        return None
    ptype = obj.getTypeIdOfProperty(prop).lower()
    val = getattr(obj, prop)
    row = QtWidgets.QHBoxLayout()
    row.addWidget(QtWidgets.QLabel(prop))
    # ------------------------
    # FLOAT
    # ------------------------
    if "float" in ptype:
        w = QtWidgets.QDoubleSpinBox()
        w.setRange(-1e9, 1e9)
        w.setValue(float(val))
        w.valueChanged.connect(lambda v, p=prop: dlg._on_change(p, v))
    # ------------------------
    # BOOL
    # ------------------------
    elif "bool" in ptype:
        w = QtWidgets.QCheckBox()
        w.setChecked(bool(val))
        w.toggled.connect(lambda v, p=prop: dlg._on_change(p, v))
    # ------------------------
    # STRING
    # ------------------------
    elif "string" in ptype:
        w = QtWidgets.QLineEdit()
        w.setText(str(val))
        w.textChanged.connect(lambda v, p=prop: dlg._on_change(p, v))
    # ------------------------
    # ENUM
    # ------------------------
    elif "enumeration" in ptype:
        w = QtWidgets.QComboBox()
        items = obj.getEnumerationsOfProperty(prop)
        w.addItems(items)
        w.setCurrentText(str(val))
        w.currentTextChanged.connect(lambda v, p=prop: dlg._on_change(p, v))
    else:
        print("Unknown type:", prop, ptype)
        return None
    row.addWidget(w)
    return row
