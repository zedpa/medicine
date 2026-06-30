"""对话历史持久化存储层 (spec-003 T1)。

sqlite 之上的会话增/查/列/改/删/裁剪。设计要点:
- 时间戳与 id 由调用方注入, 存储层不调 datetime.now()/uuid -> 纯净、确定性可单测;
- list() 只返回元信息(不含 messages 正文), 历史很长时不拉全文;
- 并发写沿用 cache.py 的进程内 _LOCK + "最后写入胜"(upsert)。
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
from typing import Optional

_LOCK = threading.Lock()


def _derive_title(messages: list, max_len: int) -> str:
    """取首条 user 消息为标题, 去首尾空白, 超 max_len 截断加省略号; 无 user 回退「新对话」。"""
    for m in messages or []:
        if m.get("role") == "user":
            text = (m.get("content") or "").strip()
            if text:
                return text if len(text) <= max_len else text[:max_len] + "…"
    return "新对话"


class HistoryStore:
    def __init__(self, db_path: str):
        d = os.path.dirname(db_path)
        if d:
            os.makedirs(d, exist_ok=True)
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS conversations ("
            "id TEXT PRIMARY KEY, owner TEXT, title TEXT, created_at TEXT, "
            "updated_at TEXT, messages_json TEXT, results_json TEXT)"
        )
        # 迁移: 旧库可能缺 results_json(spec-003 T3) / owner(spec-004 T2) 列 -> 补列。
        #   旧行 owner=NULL -> 对任何登录用户不可见(不丢数据), 可经 HISTORY_LEGACY_OWNER 一次性认领。
        cols = {r[1] for r in self._conn.execute("PRAGMA table_info(conversations)")}
        if "results_json" not in cols:
            self._conn.execute("ALTER TABLE conversations ADD COLUMN results_json TEXT")
        if "owner" not in cols:
            self._conn.execute("ALTER TABLE conversations ADD COLUMN owner TEXT")
        self._conn.commit()
        legacy = os.environ.get("HISTORY_LEGACY_OWNER")
        if legacy:
            with _LOCK:
                self._conn.execute(
                    "UPDATE conversations SET owner=? WHERE owner IS NULL", (legacy,))
                self._conn.commit()

    def save(self, conv: dict) -> None:
        """按 id upsert。conv 须含 owner(=username); messages 序列化为 messages_json。"""
        with _LOCK:
            self._conn.execute(
                "INSERT OR REPLACE INTO conversations "
                "(id, owner, title, created_at, updated_at, messages_json, results_json) "
                "VALUES (?,?,?,?,?,?,?)",
                (
                    conv["id"],
                    conv.get("owner", ""),
                    conv.get("title", ""),
                    conv.get("created_at", ""),
                    conv.get("updated_at", ""),
                    json.dumps(conv.get("messages", []), ensure_ascii=False),
                    json.dumps(conv.get("results", []), ensure_ascii=False),
                ),
            )
            self._conn.commit()

    def get(self, conv_id: str, owner: str) -> Optional[dict]:
        """取单条; owner 不匹配视同不存在(返回 None)-> 跨用户隔离在查询层强制。"""
        cur = self._conn.execute(
            "SELECT id, title, created_at, updated_at, messages_json, results_json "
            "FROM conversations WHERE id=? AND owner=?", (conv_id, owner)
        )
        row = cur.fetchone()
        if not row:
            return None
        return {
            "id": row[0], "title": row[1], "created_at": row[2],
            "updated_at": row[3], "messages": json.loads(row[4] or "[]"),
            "results": json.loads(row[5] or "[]"),   # 旧库 NULL -> [](向后兼容)
        }

    def list(self, owner: str, limit: Optional[int] = None) -> list:
        """按 updated_at 降序返回该 owner 的会话元信息(含 n_messages, 不含正文)。"""
        sql = ("SELECT id, title, created_at, updated_at, messages_json "
               "FROM conversations WHERE owner=? ORDER BY updated_at DESC")
        if limit is not None:
            sql += f" LIMIT {int(limit)}"
        out = []
        for r in self._conn.execute(sql, (owner,)).fetchall():
            try:
                n = len(json.loads(r[4] or "[]"))
            except (ValueError, TypeError):
                n = 0
            out.append({"id": r[0], "title": r[1], "created_at": r[2],
                        "updated_at": r[3], "n_messages": n})
        return out

    def list_all(self, limit: Optional[int] = None) -> list:
        """跨 owner 返回会话元信息(含 owner), updated_at 降序。仅供 admin 后台总览。"""
        sql = ("SELECT id, owner, title, created_at, updated_at, messages_json "
               "FROM conversations ORDER BY updated_at DESC")
        if limit is not None:
            sql += f" LIMIT {int(limit)}"
        out = []
        for r in self._conn.execute(sql).fetchall():
            try:
                n = len(json.loads(r[5] or "[]"))
            except (ValueError, TypeError):
                n = 0
            out.append({"id": r[0], "owner": r[1], "title": r[2], "created_at": r[3],
                        "updated_at": r[4], "n_messages": n})
        return out

    def export_all(self) -> list:
        """跨 owner 返回全量会话(含 messages + results), 供统计聚合。仅供 admin 调用。"""
        rows = self._conn.execute(
            "SELECT id, owner, title, created_at, updated_at, messages_json, results_json "
            "FROM conversations"
        ).fetchall()
        return [{
            "id": r[0], "owner": r[1], "title": r[2], "created_at": r[3],
            "updated_at": r[4], "messages": json.loads(r[5] or "[]"),
            "results": json.loads(r[6] or "[]"),
        } for r in rows]

    def set_title(self, conv_id: str, owner: str, title: str) -> None:
        """仅更新标题(重命名)。跨 owner 或不存在的 id 静默忽略(幂等)。"""
        with _LOCK:
            self._conn.execute(
                "UPDATE conversations SET title=? WHERE id=? AND owner=?",
                (title, conv_id, owner))
            self._conn.commit()

    def delete(self, conv_id: str, owner: str) -> None:
        """删单条; 跨 owner 或删不存在的 id 不报错(幂等)。"""
        with _LOCK:
            self._conn.execute(
                "DELETE FROM conversations WHERE id=? AND owner=?", (conv_id, owner))
            self._conn.commit()

    def prune(self, owner: str, keep: int) -> None:
        """按 owner 各自只保留 updated_at 最新的 keep 条(A 的历史不挤掉 B 的)。"""
        with _LOCK:
            self._conn.execute(
                "DELETE FROM conversations WHERE owner=? AND id NOT IN ("
                "SELECT id FROM conversations WHERE owner=? "
                "ORDER BY updated_at DESC LIMIT ?)",
                (owner, owner, int(keep)),
            )
            self._conn.commit()
