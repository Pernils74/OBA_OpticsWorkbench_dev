"""FreeCAD view/optics refresh helpers."""

import time
import FreeCAD as App
from PySide import QtCore, QtGui
import FreeCADGui as Gui


try:
    import FreeCADGui
except Exception:
    FreeCADGui = None


def _refresh_3d_view():
    """Force update the 3D view (best-effort)."""
    try:
        if FreeCADGui:
            FreeCADGui.updateGui()
    except Exception:
        pass
    try:
        if FreeCADGui and FreeCADGui.ActiveDocument:
            vw = FreeCADGui.ActiveDocument.ActiveView
            if vw:
                vw.update()
    except Exception:
        pass


def _refresh_plot_window():
    """Update Plot window if available."""
    try:
        from FreeCAD.Plot import Plot
    except Exception:
        try:
            from freecad.plot import Plot
        except Exception:
            Plot = None
    if Plot:
        try:
            if hasattr(Plot, "update") and callable(Plot.update):
                Plot.update()
            else:
                if hasattr(Plot, "closePlot") and callable(Plot.closePlot):
                    Plot.closePlot()
                if hasattr(Plot, "figure") and callable(Plot.figure):
                    Plot.figure("HitAnalysis")
        except Exception:
            pass


def _restart_optics():
    """Restart OpticsWorkbench (best-effort)."""
    try:
        import OpticsWorkbench
    except Exception:
        return
    try:
        OpticsWorkbench.allOff()
        OpticsWorkbench.restartAll()
    except Exception:
        pass


def recompute_doc(doc, iter_index=None, note=None, restore_view=True):
    """Recompute the document, restart optics and refresh UI."""
    t0 = time.time()
    # App.console.PrintMessage("[   OBA   ] Starting recompute+optics+refresh...\n")
    prev_subwin = remember_active_subwindow()

    try:
        doc.recompute()
    except Exception as e:
        try:
            App.Console.PrintError(f"[OBA] recompute error: {e}\n")
        except Exception:
            pass
    _restart_optics()
    _refresh_3d_view()
    # _refresh_plot_window()

    if restore_view:
        restore_active_subwindow(prev_subwin)

    dt = time.time() - t0
    msg = "[  OBA    ] recompute+optics+refresh {:.3f}s".format(dt)
    if iter_index is not None:
        msg += " | iter={}".format(iter_index)
    if note:
        msg += " | " + str(note)
    try:
        App.Console.PrintMessage(msg + "\n")
    except Exception:
        pass


def remember_active_subwindow():
    """Returnera aktivt QMdiSubWindow (eller None) på ett robust sätt."""
    try:
        if not FreeCADGui:
            return None
        mw = Gui.getMainWindow()
        if not mw:
            return None
        mdi = mw.findChild(QtGui.QMdiArea)
        if not mdi:
            return None
        return mdi.activeSubWindow()
    except Exception:
        return None


def restore_active_subwindow(subwin):
    """Återaktivera tidigare aktivt QMdiSubWindow (om det fortfarande finns)."""
    if subwin is None:
        return
    try:
        if not FreeCADGui:
            return
        mw = Gui.getMainWindow()
        if not mw:
            return
        mdi = mw.findChild(QtGui.QMdiArea)
        if not mdi:
            return
        # Kontrollera att subwin fortfarande är ett barn till MDI
        if subwin in mdi.subWindowList():
            mdi.setActiveSubWindow(subwin)
            # Se till att det faktiskt blir synligt/fokuserat:
            try:
                subwin.widget().setFocus(QtCore.Qt.ActiveWindowFocusReason)
            except Exception:
                pass
    except Exception:
        pass
