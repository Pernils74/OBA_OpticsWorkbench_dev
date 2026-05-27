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
def get_default_db_path():
    # fallback om dokument inte är sparat
    return os.path.join(App.getUserAppDataDir(), "temp_hits.db")


def get_doc_db_path(doc=None):
    doc = doc or App.ActiveDocument
    if not doc:
        return get_default_db_path()

    # måste vara sparad
    if not doc.FileName:
        return get_default_db_path()

    folder = os.path.dirname(doc.FileName)
    name = os.path.splitext(os.path.basename(doc.FileName))[0]

    return os.path.join(folder, f"{name}_hits.db")


# --------------------------------------------------
# DB class
# --------------------------------------------------
class HitsDB:

    def __init__(self, path=None):
        self.path = path or get_doc_db_path()

        self._lock = threading.Lock()
        self._pending_writes = 0
        self._commit_interval = 20

        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")

        self._init_schema()

    # --------------------------------------------------
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
    # Schema
    # --------------------------------------------------
    def _init_schema(self):
        c = self.conn.cursor()

        c.execute("""
            CREATE TABLE IF NOT EXISTS hits (
                step_id TEXT,
                target_object TEXT,
                emitter_id TEXT,
                optical_type TEXT,
                moved_objects TEXT,
                x REAL,
                y REAL,
                z REAL,
                hits INTEGER,
                power_in REAL,
                power_out REAL,
                absorbed_power REAL,
                PRIMARY KEY (
                    step_id,
                    target_object,
                    emitter_id,
                    x, y, z
                )
            )
        """)

        self.conn.commit()

    # --------------------------------------------------
    # WRITE
    # --------------------------------------------------
    def write_hits_batch(self, rows):
        if not rows:
            return

        def trunc(v):
            f = 10**6
            return math.trunc(v * f) / f

        fixed_rows = []
        for r in rows:
            step_id, target, emitter, optical, moved, x, y, z, hits, pin, pout, absorbed = r
            fixed_rows.append(
                (
                    step_id,
                    target,
                    emitter,
                    optical,
                    moved,
                    trunc(x),
                    trunc(y),
                    trunc(z),
                    hits,
                    pin,
                    pout,
                    absorbed,
                )
            )

        with self._lock:
            self.conn.executemany(
                """
                INSERT INTO hits (
                    step_id,
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
                    step_id,
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

    def commit(self):
        with self._lock:
            self.conn.commit()
            self._pending_writes = 0

    def flush_if_needed(self):
        self._pending_writes += 1
        if self._pending_writes >= self._commit_interval:
            self.commit()

    # --------------------------------------------------
    # READ
    # --------------------------------------------------
    def read_grid(self, target_object, emitter_id, step_id):
        with self._lock:
            cur = self.conn.execute(
                """
                SELECT x, y, z,
                       hits,
                       power_in,
                       power_out,
                       moved_objects
                FROM hits
                WHERE target_object=? AND emitter_id=? AND step_id=?
                ORDER BY z, y, x
                """,
                (target_object, emitter_id, step_id),
            )
            rows = cur.fetchall()

        X, Y, Z, H, PIN, POUT, MOVED = [], [], [], [], [], [], []

        for x, y, z, h, pin, pout, moved in rows:
            X.append(x)
            Y.append(y)
            Z.append(z)
            H.append(h)
            PIN.append(pin)
            POUT.append(pout)
            MOVED.append(moved)

        return X, Y, Z, H, PIN, POUT, MOVED

    # --------------------------------------------------
    # LIST
    # --------------------------------------------------
    def list_steps(self):
        with self._lock:
            cur = self.conn.execute("""
                SELECT DISTINCT step_id
                FROM hits
                ORDER BY step_id
            """)
            return [r[0] for r in cur.fetchall() if r[0]]

    def list_target_objects(self):
        with self._lock:
            cur = self.conn.execute("""
                SELECT DISTINCT target_object
                FROM hits
                ORDER BY target_object
            """)
            return [r[0] for r in cur.fetchall()]

    def list_emitters(self, target_object):
        with self._lock:
            cur = self.conn.execute(
                """
                SELECT DISTINCT emitter_id
                FROM hits
                WHERE target_object=?
                ORDER BY emitter_id
                """,
                (target_object,),
            )
            return [r[0] for r in cur.fetchall()]

    def get_optical_type(self, target_object):
        with self._lock:
            cur = self.conn.execute(
                """
                SELECT optical_type
                FROM hits
                WHERE target_object=?
                LIMIT 1
                """,
                (target_object,),
            )
            row = cur.fetchone()
            return row[0] if row else None

    # --------------------------------------------------
    # CLEANUP
    # --------------------------------------------------
    def clear_all(self):
        with self._lock:
            self.conn.execute("DELETE FROM hits")
            self.conn.commit()
            self.conn.execute("VACUUM")
