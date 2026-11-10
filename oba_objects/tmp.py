import FreeCADGui as Gui


def create_widget(dlg, obj, prop):
    if prop not in obj.PropertiesList:
        return None

    ptype = obj.getTypeIdOfProperty(prop).lower()

    row = QtWidgets.QHBoxLayout()
    row.addWidget(QtWidgets.QLabel(prop))

    # --------------------------------
    # Length
    # --------------------------------
    if "length" in ptype:
        widget = Gui.UiLoader().createWidget("Gui::QuantitySpinBox")
        widget.setProperty("rawValue", float(getattr(obj, prop)))
        widget.setProperty("binding", f"{obj.Name}.{prop}")
        widget.valueChanged.connect(lambda v, p=prop: dlg._on_change(p, widget.property("rawValue")))
    # --------------------------------
    # Angle
    # --------------------------------
    elif "angle" in ptype:
        widget = Gui.UiLoader().createWidget("Gui::QuantitySpinBox")
        widget.setProperty("unit", "deg")
        widget.setProperty("rawValue", float(getattr(obj, prop)))
        widget.valueChanged.connect(lambda v, p=prop: dlg._on_change(p, widget.property("rawValue")))

    # ...
