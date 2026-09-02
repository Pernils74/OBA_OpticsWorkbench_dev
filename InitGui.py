IS_ACTIVE = True

if IS_ACTIVE:
    import os
    import FreeCAD as App
    import FreeCADGui as Gui
    from PySide import QtCore

    # def get_module_path():
    #     if "__file__" in globals() and globals()["__file__"]:
    #         return os.path.abspath(globals()["__file__"]).lower()
    #     return App.getUserAppDataDir().lower()

    # module_path = get_module_path().lower()

    # IS_DEV_MODULE = "dev" in module_path
    # MODULE_VARIANT = "DEV" if IS_DEV_MODULE else "PUBLIC"

    # --- fungerar i alla lägen ---

    # def initialize_icons():
    #     icon_path = os.path.join(get_module_dir(), "Resources", "icons")
    #     if os.path.isdir(icon_path) and icon_path not in Gui.listIconPaths():
    #         Gui.addIconPath(icon_path)

    # initialize_icons()

    class OBA_Optics(Gui.Workbench):

        MenuText = f"OBA optics "

        # ToolTip = "OBA optik- och simuleringsverktyg"

        COMMAND_PREFIX = "OBA_"

        @staticmethod
        def get_module_dir():
            if "__file__" in globals() and globals()["__file__"]:
                return os.path.dirname(os.path.abspath(__file__))
            return os.path.join(App.getUserAppDataDir(), "Mod", "OBA_OpticsWorkbench_dev")  # sa_optics

        def Initialize(self):
            import hot_reload  # 🔥 lokal import (viktig!)

            module_dir = self.get_module_dir()
            icon_dir = os.path.join(module_dir, "icons")

            def get_icon(name):
                p = os.path.join(icon_dir, name)
                return p if os.path.exists(p) else ""

            # -------------------------
            # --- Optical objekt ---
            # -------------------------
            hot_reload.register_command(
                command="OBA_CreateBeam",
                impl_module="oba_objects.oba_beam",
                menu="Skapa Beam",
                tooltip="Skapar beam",
                pixmap=get_icon("oba_beam.svg"),
            )

            hot_reload.register_command(
                command="OBA_CreateMirror",
                impl_module="oba_objects.oba_mirror",
                menu="Skapa Mirror",
                tooltip="Skapar mirror",
                pixmap=get_icon("oba_mirror.svg"),
            )

            hot_reload.register_command(
                command="OBA_CreateEmitter",
                impl_module="oba_objects.oba_emitter",
                menu="Skapa Emitter",
                tooltip="Skapar emitter",
                pixmap=get_icon("oba_emitter.svg"),
            )

            hot_reload.register_command(
                command="OBA_CreateAbsorber",
                impl_module="oba_objects.oba_absorber",
                menu="Skapa Absorber",
                tooltip="Skapar absorber",
                pixmap=get_icon("oba_absorber.svg"),
            )
            hot_reload.register_command(
                command="OBA_CreateDetector",
                impl_module="oba_objects.oba_detector",
                menu="Skapa Detector",
                tooltip="Skapar detector",
                pixmap=get_icon("oba_detector.svg"),
            )

            hot_reload.register_command(
                command="OBA_CreateLens",
                impl_module="oba_objects.oba_lens",
                menu="Skapa Lense",
                tooltip="Skapar lins",
                pixmap=get_icon("oba_lens.svg"),
            )

            hot_reload.register_command(
                command="OBA_CreateGrating",
                impl_module="oba_objects.oba_grating",
                menu="Skapa Grating",
                tooltip="Skapar grating",
                pixmap=get_icon("oba_grating.svg"),
            )

            hot_reload.register_command(
                command="OBA_CreateRayConfig",
                impl_module="oba_objects.oba_ray_config",
                menu="Ray Collector",
                tooltip="Ray Collector",
                pixmap=get_icon("oba_rayconfig.svg"),
            )

            # -------------------------
            # --------- Builders --------
            # -------------------------

            hot_reload.register_command(
                command="OBA_CreateOpticalObject",
                impl_module="oba_objects.oba_optical_base",
                menu="Nya optial object",
                tooltip="Rensa logger",
                pixmap=get_icon("oba_optical_object.svg"),
            )

            hot_reload.register_command(
                command="OBA_CreateEllipsoid",
                impl_module="oba_toolbox.oba_ellipsoid",
                menu="Ellipsoid builder",
                tooltip="Ellipsoid builder",
                pixmap=get_icon("oba_mirrorbuilder2.svg"),
            )
            hot_reload.register_command(
                command="OBA_CreateEllipsoid_old",
                impl_module="oba_toolbox.oba_ellipsoid_copy",
                menu="Ellipsoid builder OLD",
                tooltip="Ellipsoid builder OLD",
                pixmap=get_icon("oba_mirrorbuilder2.svg"),
            )

            hot_reload.register_command(
                command="OBA_CreateMainMirror",
                impl_module="oba_toolbox.oba_main_mirror",
                menu="Main mirror builder",
                tooltip="Main mirror builder",
                pixmap=get_icon("oba_mirrorbuilder2.svg"),
            )

            hot_reload.register_command(
                command="OBA_CreateComponentMirror",
                impl_module="oba_toolbox.oba_component_mirror",
                menu="Component mirror builder",
                tooltip="Component mirror builder",
                pixmap=get_icon("oba_mirrorbuilder2.svg"),
            )
            hot_reload.register_command(
                command="OBA_CreateLightDome",
                impl_module="oba_toolbox.oba_light_dome",
                menu="Light dome builder",
                tooltip="Light dome builder",
                pixmap=get_icon("oba_mirrorbuilder2.svg"),
            )

            # hot_reload.register_command(
            #     command="OBA_CreateLensBuilder",
            #     impl_module="oba_objects.oba_lensbuilder",
            #     menu="Lens builder",
            #     tooltip="Lens builder",
            #     pixmap=get_icon("oba_lensbuilder.svg"),
            # )

            # hot_reload.register_command(
            #     command="OBA_CreatePlaneBuilder",
            #     impl_module="oba_objects.oba_planebuilder",
            #     menu="Plane builder",
            #     tooltip="Plane builder",
            #     pixmap=get_icon("oba_planebuilder.svg"),
            # )

            # -------------------------
            # --------- Utils --------
            # -------------------------

            hot_reload.register_command(
                command="OBA_ShowRayBounceRange",
                impl_module="oba_rayengine.oba_bounce_range_controller",
                menu="Ray bounce dialog",
                tooltip="Ray bounce dialog",
                pixmap=get_icon("oba_bounce_range.svg"),
            )

            hot_reload.register_command(
                command="OBA_ShowBatchDialog",
                impl_module="oba_scanner.dialog_batch_edit",
                menu="Batch group dialog",
                tooltip="Batch dialog",
                pixmap=get_icon("scanner_batch_dialog.svg"),
            )

            hot_reload.register_command(
                command="OBA_ShowXYZLiveList",
                impl_module="oba_plots.show_xyz_live_list",
                menu="Show xyz list",
                tooltip="Visa XYZ-lista",
                pixmap=get_icon("xyz_list.svg"),
            )

            hot_reload.register_command(
                command="OBA_ShowLiveSheetsDock",
                impl_module="liveSheet",
                menu="Live spreadsheet",
                tooltip="Live spreadsheet",
                pixmap=get_icon("live_spreadsheet.svg"),
            )

            # -------------------------
            # --------- Plots  --------
            # -------------------------

            hot_reload.register_command(
                command="ShowClusterPlotDialog",
                impl_module="oba_plots.cluster_plot",
                menu="För att plotta",
                tooltip="Plotta cluster",
                pixmap=get_icon("plot_ray_cluster.svg"),
            )

            hot_reload.register_command(
                command="ShowPowerDensityPlotDialog",
                impl_module="oba_plots.power_density_plot",
                menu="För att plotta power",
                tooltip="Plotta cluster power",
                pixmap=get_icon("plot_power_density.svg"),
            )

            hot_reload.register_command(
                command="ShowPowerVsHitPlotDialog",
                impl_module="oba_plots.power_vs_hit_plot",
                menu="För att plotta power",
                tooltip="Plotta cluster power",
                pixmap=get_icon("plot_power_vs_hit.svg"),
            )

            # --------------------------
            # ----- Examples   ------
            # --------------------------

            hot_reload.register_command(
                command="OBA_ExampleHerriottCell",
                impl_module="examples.herriot_cell",
                menu="Example Herriot cell",
                tooltip="Herriot cell for testing and demonstration",
                pixmap=get_icon("example_herriot.svg"),
            )

            hot_reload.register_command(
                command="OBA_ExamplePrismGradient",
                impl_module="examples.prisma_gradient",
                menu="Example Prism Gradient",
                tooltip="Prism gradient for testing and demonstration",
                pixmap=get_icon("example_prisma_gradient.svg"),
            )

            # --------------------------
            # ----- Optuna  ------
            # --------------------------

            # hot_reload.register_command(
            #     command="ShowOptimizeDialog",
            #     impl_module="Optimize.optimize_dialog",
            #     menu="Visa optimeringsnurran",
            #     tooltip="Visa optimeringsnurran",
            #     pixmap=get_icon("optimize.svg"),
            # )

            hot_reload.register_command(
                command="ShowOptimizeDialog",
                impl_module="OPTIMIZER.optimize_dialog",
                menu="Visa optimeringsnurran",
                tooltip="Visa optimeringsnurran",
                pixmap=get_icon("optimize.svg"),
            )

            # --------------------------
            # ----- Debugg stuff  ------
            # --------------------------

            hot_reload.register_command(
                command="OBA_FeatureScan",
                impl_module="debug.ShowFeatureInfo",
                menu="Visa Info om Feature",
                tooltip="Batch dialog",
                pixmap=get_icon("batch_movedddd.svg"),
            )

            hot_reload.register_command(
                command="OBA_ListObjects",
                impl_module="debug.ListObjects",
                menu="Visa Info om alla object",
                tooltip="Visar info om alla object",
                pixmap=get_icon("batch_moveddd.svg"),
            )

            hot_reload.register_command(
                command="_ClearLogger",
                impl_module="logger",
                menu="Rensa logger",
                tooltip="Rensa logger",
                pixmap=get_icon("batch_movedddd.svg"),
            )

            hot_reload.register_command(
                command="OBA_ShowRayHistory",
                impl_module="oba_rayengine.oba_ray_debug",
                menu="För att visa ray hits",
                tooltip="Rensa logger",
                pixmap=get_icon("batch_movedddd.svg"),
            )

            # --- Reload command ---
            Gui.addCommand("OBA_ReloadWorkbench", hot_reload.OBA_Reload_Command())

            def SEP():
                return "Separator"

            self.list = [
                "OBA_CreateBeam",
                "OBA_CreateEmitter",
                "OBA_CreateMirror",
                "OBA_CreateAbsorber",
                "OBA_CreateDetector",
                "OBA_CreateLens",
                "OBA_CreateGrating",
                "OBA_CreateRayConfig",
                "OBA_ShowRayBounceRange",
                SEP(),  # builders
                "OBA_CreateOpticalObject",
                # "OBA_CreateMirrorBuilder",
                # "OBA_CreateLensBuilder",
                # "OBA_CreatePlaneBuilder",
                SEP(),  # utils
                "ShowClusterPlotDialog",
                "ShowPowerDensityPlotDialog",
                "ShowPowerVsHitPlotDialog",
                SEP(),
                "ShowOptimizeDialog",
                SEP(),
                "OBA_CreateEllipsoid",
                "OBA_CreateEllipsoid_old",
                "OBA_CreateMainMirror",
                "OBA_CreateComponentMirror",
                "OBA_CreateLightDome",
                SEP(),
                "OBA_ShowBatchDialog",
                "OBA_ShowXYZLiveList",
                "OBA_ShowLiveSheetsDock",
                SEP(),
                "OBA_ExampleHerriottCell",
                "OBA_ExamplePrismGradient",
                SEP(),
                "OBA_ReloadWorkbench",
                "OBA_FeatureScan",
                SEP(),
                "OBA_ListObjects",
                "_ClearLogger",
                "OBA_ShowRayHistory",
                SEP(),
                SEP(),
            ]

            self.appendToolbar("OBA Tools", self.list)
            self.appendMenu("OBA optics", self.list + ["OBA_ExampleHerriottCell", "OBA_ExamplePrismGradient"])

        def Activated(self):

            import hot_reload

            hot_reload.start_auto_reload()

            # import hot_reload
            # hot_reload.start_auto_reload()

            # 2. Öppna testfil
            file_path = r"C:\temp\S12_orginal.FCStd"
            file_path = r"C:\temp\test_med_scan.FCStd"
            file_path = r"C:\temp\test2.FCStd"
            file_path = r"C:\temp\__OBA_optiskt_modell_för_AI_med_kupor____.FCStd"

            if os.path.exists(file_path):
                doc = next(
                    (d for d in App.listDocuments().values() if d.FileName and os.path.normpath(d.FileName) == os.path.normpath(file_path)),
                    None,
                )
                if not doc:
                    doc = App.openDocument(file_path)
                App.setActiveDocument(doc.Name)
                Gui.SendMsgToActiveView("ViewFit")
                # QtCore.QTimer.singleShot(500, lambda: Gui.SendMsgToActiveView("ViewFit"))

            Gui.activateWorkbench("OBA_Optics")

        def Deactivated(self):
            import hot_reload

            hot_reload.stop_auto_reload()
            # import hot_reload
            # hot_reload.stop_auto_reload()

        def GetClassName(self):
            return "Gui::PythonWorkbench"

    Gui.addWorkbench(OBA_Optics())
