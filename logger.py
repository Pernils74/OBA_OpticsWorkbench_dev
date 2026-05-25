import threading
import time
from datetime import datetime
import FreeCAD as App
import FreeCADGui as Gui


class Logger:
    _instance = None
    _lock = threading.Lock()
    _show_log = False

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(Logger, cls).__new__(cls)
                cls._instance._sections = {}  # id -> section data
                cls._instance._order = []  # to maintain order
                # cls._instance._global_start = time.time()

                cls._instance._data_lock = threading.Lock()
            return cls._instance

    # -----------------------------------------------
    # Start a timed log section
    # -----------------------------------------------
    def start(self, section_id: str, message: str = ""):
        with self._data_lock:
            self._sections[section_id] = {"start": time.time(), "end": None, "logs": [], "header": message}
            self._order.append(section_id)

    # -----------------------------------------------
    # Add log message to section
    # -----------------------------------------------
    def log(self, section_id: str, message: str):
        timestamp = datetime.now().strftime("%H:%M:%S")
        with self._data_lock:
            if section_id not in self._sections:
                raise ValueError(f"Section '{section_id}' not started!")
            self._sections[section_id]["logs"].append(f"{timestamp}  {message}")

    # -----------------------------------------------
    # Update msg for Id
    # -----------------------------------------------

    def update_header(self, section_id: str, new_header: str):
        with self._data_lock:
            if section_id not in self._sections:
                raise ValueError(f"Section '{section_id}' not started!")
            self._sections[section_id]["header"] = new_header

    # -----------------------------------------------
    # End a section and calculate duration
    # -----------------------------------------------

    def end(self, section_id: str, message: str = ""):
        with self._data_lock:
            if section_id not in self._sections:
                raise ValueError(f"Section '{section_id}' not started!")
            # Spara sluttid
            self._sections[section_id]["end"] = time.time()
            # Lägg till ett meddelande om användaren angav ett
            if message:
                timestamp = datetime.now().strftime("%H:%M:%S")
                self._sections[section_id]["logs"].append(f"{timestamp}  {message}")

    # -----------------------------------------------
    # Print everything at the end
    # -----------------------------------------------

    def flush(self, extra_str=""):
        if self._show_log:
            now_str = datetime.now().strftime("%H:%M:%S")
            App.Console.PrintLog(f"\n================= TRACE LOG [{now_str}] {extra_str} =================")

            for sec_id in self._order:
                sec = self._sections[sec_id]
                start = sec["start"]
                end = sec["end"] if sec["end"] else time.time()
                duration = end - start

                # *** Duration först ***
                App.Console.PrintLog(f"\n({duration:.4f} s) ▶ {sec_id} — {sec['header']}")

                for line in sec["logs"]:
                    App.Console.PrintLog("   " + line)

        self.clear()
        # total = time.time() - self._global_start
        # App.Console.PrintLog("\n-------------------------------------------------")
        # App.Console.PrintLog(f"TOTAL RUNTIME: {total:.4f} s")
        # App.Console.PrintLog("=================================================\n")

    def clear(self):
        with self._data_lock:
            self._sections.clear()
            self._order.clear()


if "LoggerSingleton" not in globals():
    LoggerSingleton = Logger()


def get_logger(show_log=False):
    LoggerSingleton._show_log = show_log
    return LoggerSingleton


def _ClearLogger():
    log = get_logger()
    log.clear()
    App.Console.PrintLog("Logger cleared.\n")


# Användar exempel

# from logger import Logger
# import time

# log = Logger()

# log.start("RayCollector", "starting tracing")
# time.sleep(0.003)
# log.log("RayCollector", "Executing…")

# log.start("TraceModeMesh", "TraceMode: Mesh")
# time.sleep(0.005)
# log.log("TraceModeMesh", "Emitter 'Emitter' traced")

# log.end("TraceModeMesh")
# log.end("RayCollector")

# log.flush()
