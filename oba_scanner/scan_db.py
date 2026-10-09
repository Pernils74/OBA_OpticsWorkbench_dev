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
                hit_target TEXT,
                move_target TEXT,
                emitter_id TEXT,
                optical_type TEXT,
                moved_objects TEXT,
                wx REAL,
                wy REAL,
                wz REAL,

                hits INTEGER,
                power_in REAL,
                power_out REAL,
                absorbed_power REAL,
                PRIMARY KEY (
                    step_id,
                    hit_target,
                    move_target,                    
                    emitter_id,
                    optical_type,
                    moved_objects,
                    wx, wy, wz
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
            step_id, hit_target, move_target, emitter, opticalType, moved_objects_str, wx, wy, wz, hits, pin, pout, absorbed = r
            fixed_rows.append(
                (
                    step_id,
                    hit_target,
                    move_target,
                    emitter,
                    opticalType,
                    moved_objects_str,
                    trunc(wx),
                    trunc(wy),
                    trunc(wz),
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
                    hit_target,
                    move_target,
                    emitter_id,
                    optical_type,
                    moved_objects,
                    wx,wy, wz,
                    hits,
                    power_in,
                    power_out,
                    absorbed_power
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(
                    step_id,
                    hit_target,
                    move_target,                    
                    emitter_id,
                    optical_type,
                    moved_objects,
                    wx, wy, wz
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
    def read_grid(self, hit_target, emitter_id, step_id):
        with self._lock:
            cur = self.conn.execute(
                """
                SELECT wx, wy, wz,
                       hits,
                       power_in,
                       power_out,
                       move_target,
                       moved_objects
                FROM hits
                WHERE hit_target=? AND emitter_id=? AND step_id=?
                ORDER BY wx, wy, wz
                """,
                (hit_target, emitter_id, step_id),
            )
            rows = cur.fetchall()

        WX, WY, WZ, H, PIN, POUT, MOVE_OBJECT, MOVED_OBJECTS = (
            [],
            [],
            [],
            [],
            [],
            [],
            [],
            [],
        )

        for wx, wy, wz, h, pin, pout, move_object, moved_objects in rows:
            WX.append(wx)
            WY.append(wy)
            WZ.append(wz)
            H.append(h)
            PIN.append(pin)
            POUT.append(pout)
            MOVE_OBJECT.append(move_object)
            MOVED_OBJECTS.append(moved_objects)

        return WX, WY, WZ, H, PIN, POUT, MOVE_OBJECT, MOVED_OBJECTS

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
                SELECT DISTINCT hit_target
                FROM hits
                ORDER BY hit_target
            """)
            return [r[0] for r in cur.fetchall()]

    def list_emitters(self, hit_target):
        with self._lock:
            cur = self.conn.execute(
                """
                SELECT DISTINCT emitter_id
                FROM hits
                WHERE hit_target=?
                ORDER BY emitter_id
                """,
                (hit_target,),
            )
            return [r[0] for r in cur.fetchall()]

    def get_optical_type(self, hit_target):
        with self._lock:
            cur = self.conn.execute(
                """
                SELECT optical_type
                FROM hits
                WHERE hit_target=?
                LIMIT 1
                """,
                (hit_target,),
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

    def clear_step(self, step_id):
        with self._lock:
            self.conn.execute(
                """
                 DELETE FROM hits
                 WHERE step_id=?
                 """,
                (step_id,),
            )
            self.conn.commit()
