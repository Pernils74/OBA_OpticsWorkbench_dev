# -*- coding: utf-8 -*-
# scan_db.py

import os
import sqlite3
import threading
import FreeCAD as App


# --------------------------------------------------
# Paths
# --------------------------------------------------
def get_oba_mod_dir():
    base_mod = os.path.join(App.getUserAppDataDir(), "Mod")
    oba = os.path.join(base_mod, "Oba")
    os.makedirs(oba, exist_ok=True)
    return oba


def get_default_db_path():
    return os.path.join(get_oba_mod_dir(), "hits.sqlite.db")


# --------------------------------------------------
# DB class
# --------------------------------------------------
class HitsDB:
    def __init__(self, path=None):
        self.path = path or get_default_db_path()
        self._lock = threading.Lock()
        self._init_schema()

    # --------------------------------------------------
    # Schema + MIGRATION
    # --------------------------------------------------
    def _init_schema(self):
        with sqlite3.connect(self.path) as conn:
            c = conn.cursor()

            # 1️⃣ Create table if it does not exist (new installs)
            c.execute(
                """
                CREATE TABLE IF NOT EXISTS hits (
                    doc_name TEXT,
                    optical_type TEXT,
                    emitter_id TEXT,
                    x REAL,
                    y REAL,
                    z REAL,
                    value REAL,
                    PRIMARY KEY (doc_name, optical_type, emitter_id, x, y, z)
                )
            """
            )

            # 2️⃣ Inspect existing schema (old installs)
            c.execute("PRAGMA table_info(hits)")
            existing_cols = {row[1] for row in c.fetchall()}

            # 3️⃣ Migration: add missing columns safely
            migrations = {
                "optical_type": "TEXT",
                "emitter_id": "TEXT",
                "value": "REAL",
            }

            for col, col_type in migrations.items():
                if col not in existing_cols:
                    c.execute(f"ALTER TABLE hits ADD COLUMN {col} {col_type}")
                    App.Console.PrintLog(f"[HitsDB] Added column '{col}'\n")

            # 4️⃣ Handle legacy 'hits' → 'value'
            if "hits" in existing_cols and "value" not in existing_cols:
                # keep old column as-is; new writes go to 'value'
                pass

            conn.commit()

    # --------------------------------------------------
    # Write
    # --------------------------------------------------
    def write_hit(self, doc_name, optical_type, emitter_id, x, y, z, value):
        with self._lock:
            with sqlite3.connect(self.path) as conn:
                conn.execute(
                    """
                    INSERT INTO hits(
                        doc_name, optical_type, emitter_id, x, y, z, value
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(doc_name, optical_type, emitter_id, x, y, z)
                    DO UPDATE SET value=excluded.value
                    """,
                    (doc_name, optical_type, emitter_id, x, y, z, value),
                )
                conn.commit()

    # --------------------------------------------------
    # Read (Heatmap)
    # --------------------------------------------------
    def read_grid(self, doc_name, optical_type, emitter_id):
        with self._lock:
            with sqlite3.connect(self.path) as conn:
                cur = conn.execute(
                    """
                    SELECT x, y, z, value
                    FROM hits
                    WHERE doc_name=? AND optical_type=? AND emitter_id=?
                    ORDER BY z, y, x
                    """,
                    (doc_name, optical_type, emitter_id),
                )
                rows = cur.fetchall()

        X, Y, Z, V = [], [], [], []
        for x, y, z, v in rows:
            X.append(x)
            Y.append(y)
            Z.append(z)
            V.append(v)

        return X, Y, Z, V

    # --------------------------------------------------
    # Listing helpers
    # --------------------------------------------------
    def list_documents(self):
        with self._lock:
            with sqlite3.connect(self.path) as conn:
                cur = conn.execute("SELECT DISTINCT doc_name FROM hits ORDER BY doc_name ASC")
                return [r[0] for r in cur.fetchall()]

    def list_optical_types(self, doc_name):
        with self._lock:
            with sqlite3.connect(self.path) as conn:
                cur = conn.execute(
                    """
                    SELECT DISTINCT optical_type
                    FROM hits
                    WHERE doc_name=? AND optical_type IS NOT NULL
                    ORDER BY optical_type
                    """,
                    (doc_name,),
                )
                return [r[0] for r in cur.fetchall()]

    def list_emitters(self, doc_name, optical_type):
        with self._lock:
            with sqlite3.connect(self.path) as conn:
                cur = conn.execute(
                    """
                    SELECT DISTINCT emitter_id
                    FROM hits
                    WHERE doc_name=? AND optical_type=? AND emitter_id IS NOT NULL
                    ORDER BY emitter_id
                    """,
                    (doc_name, optical_type),
                )
                return [r[0] for r in cur.fetchall()]

    # --------------------------------------------------
    # Delete
    # --------------------------------------------------
    def delete_document(self, doc_name):
        if not doc_name or "<" in doc_name:
            return 0

        with self._lock:
            with sqlite3.connect(self.path) as conn:
                cur = conn.execute("DELETE FROM hits WHERE doc_name=?", (doc_name,))
                conn.commit()
                conn.execute("VACUUM")
                return cur.rowcount
