"""账号存储层 (spec-004 T1)。

sqlite 之上的账号增/查/列/改密/删, 并产出 streamlit-authenticator 所需的 credentials dict。
设计要点(同 spec-003 历史层):
- 密码只存 bcrypt **哈希**; 哈希与时间戳由调用方注入, 本层不调 Hasher/datetime.now()
  -> 纯净、确定性可单测, 也避免存储层耦合认证库;
- list_users() 不返回 password_hash(管理视图不泄哈希);
- 并发写沿用 cache.py 的进程内 _LOCK + upsert(「最后写入胜」)。
"""
from __future__ import annotations

import os
import sqlite3
import threading
from typing import Optional

_LOCK = threading.Lock()


class UserStore:
    def __init__(self, db_path: str):
        d = os.path.dirname(db_path)
        if d:
            os.makedirs(d, exist_ok=True)
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS users ("
            "username TEXT PRIMARY KEY, name TEXT, email TEXT, "
            "password_hash TEXT, role TEXT, created_at TEXT)"
        )
        self._conn.commit()

    def upsert(self, user: dict) -> None:
        """按 username upsert。password_hash 须为调用方预先哈希后的串。"""
        with _LOCK:
            self._conn.execute(
                "INSERT OR REPLACE INTO users "
                "(username, name, email, password_hash, role, created_at) "
                "VALUES (?,?,?,?,?,?)",
                (
                    user["username"],
                    user.get("name", ""),
                    user.get("email", ""),
                    user.get("password_hash", ""),
                    user.get("role", "user"),
                    user.get("created_at", ""),
                ),
            )
            self._conn.commit()

    def get(self, username: str) -> Optional[dict]:
        """取单条(含 password_hash, 供登录校验/迁移); 不存在返回 None。"""
        cur = self._conn.execute(
            "SELECT username, name, email, password_hash, role, created_at "
            "FROM users WHERE username=?", (username,)
        )
        row = cur.fetchone()
        if not row:
            return None
        return {"username": row[0], "name": row[1], "email": row[2],
                "password_hash": row[3], "role": row[4], "created_at": row[5]}

    def list_users(self) -> list:
        """按 created_at 升序返回管理元信息(不含 password_hash)。"""
        rows = self._conn.execute(
            "SELECT username, name, email, role, created_at "
            "FROM users ORDER BY created_at ASC"
        ).fetchall()
        return [{"username": r[0], "name": r[1], "email": r[2],
                 "role": r[3], "created_at": r[4]} for r in rows]

    def set_password(self, username: str, password_hash: str) -> None:
        """仅改哈希(改密); 不存在的 username 静默忽略(幂等)。"""
        with _LOCK:
            self._conn.execute("UPDATE users SET password_hash=? WHERE username=?",
                               (password_hash, username))
            self._conn.commit()

    def delete(self, username: str) -> None:
        """删单条; 删不存在的 username 不报错(幂等)。"""
        with _LOCK:
            self._conn.execute("DELETE FROM users WHERE username=?", (username,))
            self._conn.commit()

    def count(self) -> int:
        return self._conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]

    def credentials(self) -> dict:
        """产 streamlit-authenticator 结构(含哈希): {"usernames": {u: {...}}}。"""
        rows = self._conn.execute(
            "SELECT username, name, email, password_hash, role FROM users"
        ).fetchall()
        return {"usernames": {r[0]: {
            "name": r[1], "email": r[2], "password": r[3], "roles": [r[4]],
        } for r in rows}}
