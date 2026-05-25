import importlib
import sys
import os
from PySide import QtCore
import FreeCADGui as Gui


# =======================================================
# REGISTER COMMAND
# =======================================================


def deep_reload(mod):
    importlib.reload(mod)
    prefix = mod.__name__ + "."
    for name, module in list(sys.modules.items()):
        if name.startswith(prefix) and module is not None:
            try:
                importlib.reload(module)
            except Exception:
                pass
    return mod


class ReloadingCommandProxy:
    def __init__(self, impl_module, entry_name, fallback_name="main", ui_factory_name=None, ui_closer_name=None):

        self._impl_module_name = impl_module
        self._entry_name = entry_name
        self._fallback_name = fallback_name
        self._ui_factory_name = ui_factory_name
        self._ui_closer_name = ui_closer_name
        self._current_ui = None

    def GetResources(self):
        return getattr(self, "_resources", {})

    def Activated(self):
        mod = importlib.import_module(self._impl_module_name)
        mod = deep_reload(mod)

        fn = getattr(mod, self._entry_name, None)
        if callable(fn):
            fn()
            return

        fb = getattr(mod, self._fallback_name, None)
        if callable(fb):
            fb()
            return

        raise RuntimeError(f"{self._impl_module_name} missing {self._entry_name}()")

    def IsActive(self):
        return True

    def GetClassName(self):
        return "Gui::Command"


def register_command(**kwargs):
    proxy = ReloadingCommandProxy(
        impl_module=kwargs["impl_module"],
        entry_name=kwargs["command"],
        fallback_name=kwargs.get("fallback", "main"),
        ui_factory_name=kwargs.get("ui_factory"),
        ui_closer_name=kwargs.get("ui_closer"),
    )

    proxy._resources = {
        "MenuText": kwargs["menu"],
        "ToolTip": kwargs["tooltip"],
        "Pixmap": kwargs.get("pixmap", ""),
    }

    Gui.addCommand(kwargs["command"], proxy)


# =======================================================
# HOT RELOAD CORE
# =======================================================

_RELOADING = False


def unload_package(pkg_name):
    for m in list(sys.modules.keys()):
        if m == pkg_name or m.startswith(pkg_name + "."):
            del sys.modules[m]


def unregister_commands(prefix):
    for c in list(Gui.listCommands()):
        if c.startswith(prefix):
            try:
                del Gui.Commands[c]
            except:
                pass


def reload_workbench(pkg_name="sa_optics", cmd_prefix="OBA_"):
    global _RELOADING

    if _RELOADING:
        return

    _RELOADING = True

    try:
        import sys, os

        print(f"\n[HotReload] Reloading {pkg_name}")

        # 🔥 FIX: säkerställ att parent directory finns i sys.path
        mod_dir = os.path.dirname(os.path.abspath(__file__))
        parent_dir = os.path.dirname(mod_dir)

        if parent_dir not in sys.path:
            sys.path.insert(0, parent_dir)
            print(f"[HotReload] Added to sys.path: {parent_dir}")

        # 🔧 rensa gamla commands + moduler
        unregister_commands(cmd_prefix)
        unload_package(pkg_name)

        # 🔁 importera om hela paketet
        mod = importlib.import_module(pkg_name)

        # 🔁 aktivera workbench (utan loop)
        try:
            if not Gui.activeWorkbench() or Gui.activeWorkbench().name() != "OBA_Optics":
                Gui.activateWorkbench("OBA_Optics")
        except Exception:
            Gui.activateWorkbench("OBA_Optics")

        print("[HotReload] Done\n")

        return mod

    finally:
        _RELOADING = False


class OBA_Reload_Command:

    def GetResources(self):
        icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icons", "hot_reload.svg")

        return {"MenuText": "Reload OBA Workbench", "ToolTip": "Reload all Python modules in OBA_Optics", "Pixmap": icon_path}

    # def GetResources(self):
    #     return {
    #         "MenuText": "Reload OBA Workbench",
    #         "ToolTip": "Reload all Python modules",
    #     }

    def Activated(self):
        reload_workbench()

    def IsActive(self):
        return True


Gui.addCommand("OBA_ReloadWorkbench", OBA_Reload_Command())


# =======================================================
# AUTO RELOAD
# =======================================================


class AutoReloader(QtCore.QObject):

    def __init__(self, package_root, cmd_prefix="OBA_", parent=None):
        super().__init__(parent)

        self.package_root = package_root
        self.cmd_prefix = cmd_prefix

        self.watcher = QtCore.QFileSystemWatcher()
        self.watcher.fileChanged.connect(self._on_change)

        self._scan(package_root)

    def _scan(self, root):
        for r, _, files in os.walk(root):
            for f in files:
                if f.endswith(".py"):
                    self.watcher.addPath(os.path.join(r, f))

    def _on_change(self, path):
        print("[AutoReload] Changed:", path)
        QtCore.QTimer.singleShot(300, self._reload)

    def _reload(self):
        reload_workbench("sa_optics", self.cmd_prefix)

    def stop(self):
        self.watcher.deleteLater()


_auto = None


def start_auto_reload():
    global _auto

    if _auto:
        return _auto

    root = os.path.dirname(os.path.abspath(__file__))
    _auto = AutoReloader(root)
    print("[AutoReload] Started")

    return _auto


def stop_auto_reload():
    global _auto

    if _auto:
        _auto.stop()
        _auto = None
        print("[AutoReload] Stopped")
