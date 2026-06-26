"""轻量本地缓存：sqlite key-value，按 namespace 隔离。

用于缓存 PubChem / UniProt / mygene 的在线查询结果，满足 NFR（可复现 + 在线请求带本地缓存）。
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
from typing import Any, Optional

_LOCK = threading.Lock()


class Cache:
    def __init__(self, db_path: str):
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS kv (ns TEXT, k TEXT, v TEXT, PRIMARY KEY (ns, k))"
        )
        self._conn.commit()

    def get(self, ns: str, key: str) -> Optional[Any]:
        cur = self._conn.execute("SELECT v FROM kv WHERE ns=? AND k=?", (ns, str(key)))
        row = cur.fetchone()
        return json.loads(row[0]) if row else None

    def set(self, ns: str, key: str, value: Any) -> None:
        with _LOCK:
            self._conn.execute(
                "INSERT OR REPLACE INTO kv (ns, k, v) VALUES (?, ?, ?)",
                (ns, str(key), json.dumps(value, ensure_ascii=False)),
            )
            self._conn.commit()
