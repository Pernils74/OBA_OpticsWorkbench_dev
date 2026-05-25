# -*- coding: utf-8 -*-
# scan_db.py

import os
import sqlite3
import threading
import FreeCAD as App
import math


# --------------------------------------------------
# Paths
# --------------------------------------------------
def get_oba_mod_dir():
    here = os.path.dirname(os.path.abspath(__file__))
    while True:
        parent = os.path.dirname(here)
        if os.path.basename(parent).lower() == "mod":
            return here
        if parent == here:
            break
        here = parent
    raise RuntimeError("Could not determine workbench directory")


def get_default_db_path():
    return os.path.join(get_oba_mod_dir(), "hits.sqlite.db")


# --------------------------------------------------
# DB class
# --------------------------------------------------
class HitsDB:
    def __init__(self, path=None):
        self.path = path or get_default_db_path()
        self._lock = threading.Lock()

        self._pending_writes = 0
        self._commit_interval = 20

        # Persistent connection
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")

        self._init_schema()

    def close(self):
        with self._lock:
            self.conn.commit()
            self.conn.close()

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass

    # --------------------------------------------------
    # Schema + migration
    # --------------------------------------------------

    def _init_schema(self):
        c = self.conn.cursor()

        c.execute("""
            CREATE TABLE IF NOT EXISTS hits (
                doc_name TEXT,
                target_object TEXT,
                emitter_id TEXT,
                optical_type TEXT,
                x REAL,
                y REAL,
                z REAL,
                hits INTEGER,
                power_in REAL,
                power_out REAL,
                absorbed_power REAL,
                PRIMARY KEY (
                    doc_name,
                    target_object,
                    emitter_id,
                    x, y, z
                )
            )
            """)

        # ---- migration ----
        c.execute("PRAGMA table_info(hits)")
        cols = {row[1] for row in c.fetchall()}

        def add(col, ddl):
            if col not in cols:
                c.execute(ddl)
                App.Console.PrintLog(f"[HitsDB] Added column {col}\n")

        add("target_object", "ALTER TABLE hits ADD COLUMN target_object TEXT")

        add("emitter_id", "ALTER TABLE hits ADD COLUMN emitter_id TEXT")

        add("optical_type", "ALTER TABLE hits ADD COLUMN optical_type TEXT")

        add("moved_objects", "ALTER TABLE hits ADD COLUMN moved_objects TEXT")

        add("power_in", "ALTER TABLE hits ADD COLUMN power_in REAL DEFAULT 0.0")

        add("power_out", "ALTER TABLE hits ADD COLUMN power_out REAL DEFAULT 0.0")

        add("absorbed_power", "ALTER TABLE hits ADD COLUMN absorbed_power REAL DEFAULT 0.0")

        # Bakåtkompatibilitet: om gamla "power" finns → mappa till power_out
        if "power" in cols and "power_out" in cols:
            c.execute("UPDATE hits SET power_out = power WHERE power_out = 0.0")
            App.Console.PrintLog("[HitsDB] Migrated power → power_out\n")

        self.conn.commit()

    # --------------------------------------------------
    # FAST WRITE (batch)
    # --------------------------------------------------

    def write_hits_batch(self, rows):
        if not rows:
            return

        def trunc(v):
            decimals = 6
            factor = 10**decimals
            return math.trunc(v * factor) / factor

        fixed_rows = []
        for r in rows:
            # unpack
            doc, target, emitter, optical, moved, x, y, z, hits, pin, pout, absorbed = r
            # ✅ kvantisera här
            x = trunc(x)
            y = trunc(y)
            z = trunc(z)

            fixed_rows.append((doc, target, emitter, optical, moved, x, y, z, hits, pin, pout, absorbed))
        with self._lock:
            self.conn.executemany(
                """
                INSERT INTO hits (
                    doc_name,
                    target_object,
                    emitter_id,
                    optical_type,
                    moved_objects,
                    x, y, z,
                    hits,
                    power_in,
                    power_out,
                    absorbed_power
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(
                    doc_name,
                    target_object,
                    emitter_id,
                    x, y, z
                )
                DO UPDATE SET
                    hits = excluded.hits,
                    power_in = excluded.power_in,
                    power_out = excluded.power_out,
                    absorbed_power = excluded.absorbed_power,
                    moved_objects = excluded.moved_objects
                """,
                fixed_rows,
            )

    def write_hits_batch_old(self, rows):
        """
        rows = [
            (doc, target, emitter, optical, x, y, z,
             hits, power_in, power_out, absorbed_power),
            ...
        ]
        """
        if not rows:
            return

        with self._lock:
            self.conn.executemany(
                """
                INSERT INTO hits (
                    doc_name,
                    target_object,
                    emitter_id,
                    optical_type,
                    moved_objects,
                    x, y, z,
                    hits,
                    power_in,
                    power_out,
                    absorbed_power
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(
                    doc_name,
                    target_object,
                    emitter_id,
                    x, y, z
                )
                DO UPDATE SET
                    hits = excluded.hits,
                    power_in = excluded.power_in,
                    power_out = excluded.power_out,
                    absorbed_power = excluded.absorbed_power,
                    moved_objects = excluded.moved_objects
                """,
                rows,
            )

    def commit(self):
        with self._lock:
            self.conn.commit()
            self._pending_writes = 0

    def flush_if_needed(self):
        self._pending_writes += 1

        if self._pending_writes >= self._commit_interval:
            self.commit()
            self._pending_writes = 0

    # --------------------------------------------------
    # Read
    # --------------------------------------------------
    def read_grid(self, doc_name, target_object, emitter_id):
        with self._lock:
            cur = self.conn.execute(
                """
                SELECT x, y, z,
                       hits,
                       power_in,
                       power_out,
                       moved_objects
                FROM hits
                WHERE doc_name=? AND target_object=? AND emitter_id=?
                ORDER BY z, y, x
                """,
                (doc_name, target_object, emitter_id),
            )
            rows = cur.fetchall()

        X, Y, Z, H, P_IN, P_OUT, MOVED_OBJ = [], [], [], [], [], [], []
        for x, y, z, h, pin, pout, moved_objects in rows:
            X.append(x)
            Y.append(y)
            Z.append(z)
            H.append(h)
            P_IN.append(pin)
            P_OUT.append(pout)
            MOVED_OBJ.append(moved_objects)

        return X, Y, Z, H, P_IN, P_OUT, MOVED_OBJ

    # --------------------------------------------------
    # Listing helpers
    # --------------------------------------------------
    def list_documents(self):
        with self._lock:
            cur = self.conn.execute("SELECT DISTINCT doc_name FROM hits ORDER BY doc_name")
            return [r[0] for r in cur.fetchall()]

    def list_target_objects(self, doc_name):
        with self._lock:
            cur = self.conn.execute(
                """
                SELECT DISTINCT target_object
                FROM hits
                WHERE doc_name=?
                ORDER BY target_object
                """,
                (doc_name,),
            )
            return [r[0] for r in cur.fetchall()]

    def list_emitters(self, doc_name, target_object):
        with self._lock:
            cur = self.conn.execute(
                """
                SELECT DISTINCT emitter_id
                FROM hits
                WHERE doc_name=? AND target_object=?
                ORDER BY emitter_id
                """,
                (doc_name, target_object),
            )
            return [r[0] for r in cur.fetchall()]

    def get_optical_type(self, doc_name, target_object):
        with self._lock:
            cur = self.conn.execute(
                """
                SELECT optical_type
                FROM hits
                WHERE doc_name=? AND target_object=?
                LIMIT 1
                """,
                (doc_name, target_object),
            )
            row = cur.fetchone()
            return row[0] if row else None

    # --------------------------------------------------
    # Delete
    # --------------------------------------------------
    def delete_document(self, doc_name):
        if not doc_name or "<" in doc_name:
            return 0

        with self._lock:
            cur = self.conn.execute(
                "DELETE FROM hits WHERE doc_name=?",
                (doc_name,),
            )
            self.conn.commit()
            self.conn.execute("VACUUM")
            return cur.rowcount
