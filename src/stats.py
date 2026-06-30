"""使用统计聚合层 (spec-005 T1)。

纯函数: 输入 users / conversations 列表(dict), 输出可序列化的聚合 dict。
- 不取时钟: activity_by_day 的「今天」由调用方注入 today, 保持确定性可测;
- 健壮: 缺字段 / 空 results / 坏结构按缺省(0/跳过)处理, 不抛异常。
"""
from __future__ import annotations

import datetime
from collections import Counter, defaultdict


def _n_messages(conv: dict) -> int:
    msgs = conv.get("messages")
    return len(msgs) if isinstance(msgs, list) else 0


def overview(users: list, convs: list) -> dict:
    """全站概览: 用户/管理员/会话/消息规模 + 活跃用户(≥1 会话)。"""
    owners_with_conv = {c.get("owner") for c in convs if c.get("owner")}
    return {
        "n_users": len(users),
        "n_admins": sum(1 for u in users if u.get("role") == "admin"),
        "n_conversations": len(convs),
        "n_messages": sum(_n_messages(c) for c in convs),
        "active_users": len(owners_with_conv),
    }


def per_user(users: list, convs: list) -> list:
    """各用户活跃度: 会话数/消息数/最近活跃; 按会话数降序, 再按 username。"""
    n_conv = Counter()
    n_msg = Counter()
    last = {}
    for c in convs:
        o = c.get("owner")
        if not o:
            continue
        n_conv[o] += 1
        n_msg[o] += _n_messages(c)
        ts = c.get("updated_at") or ""
        if ts and ts > last.get(o, ""):
            last[o] = ts
    rows = [{
        "username": u["username"],
        "role": u.get("role", "user"),
        "n_conversations": n_conv.get(u["username"], 0),
        "n_messages": n_msg.get(u["username"], 0),
        "last_active": last.get(u["username"]),
    } for u in users]
    rows.sort(key=lambda r: (-r["n_conversations"], r["username"]))
    return rows


def _herb_name(result: dict) -> str:
    herb = result.get("herb") or {}
    if isinstance(herb, dict):
        name = herb.get("chinese") or herb.get("latin")
        if name:
            return name
    return result.get("query") or "?"


def herb_popularity(convs: list, top_n: int) -> list:
    """跨会话跨结果的热门药材: count=出现次数, found=found=True 次数; count 降序取 top_n。

    基于结果快照(真正跑过分析的药材), 名称优先级 chinese>latin>query。
    """
    count = Counter()
    found = Counter()
    for c in convs:
        for r in (c.get("results") or []):
            res = r.get("result") if isinstance(r, dict) else None
            if not isinstance(res, dict):
                continue
            name = _herb_name(res)
            count[name] += 1
            if res.get("found") is True:
                found[name] += 1
    ranked = sorted(count.items(), key=lambda kv: (-kv[1], kv[0]))
    return [{"herb": h, "count": n, "found": found.get(h, 0)} for h, n in ranked[:top_n]]


def activity_by_day(convs: list, today: str, days: int) -> list:
    """近 days 天每天新建会话数(按 created_at 日期), 升序, 缺失日补 0。today=YYYY-MM-DD。"""
    by_day = defaultdict(int)
    for c in convs:
        d = (c.get("created_at") or "")[:10]
        if d:
            by_day[d] += 1
    end = datetime.date.fromisoformat(today)
    out = []
    for i in range(days - 1, -1, -1):
        d = (end - datetime.timedelta(days=i)).isoformat()
        out.append({"date": d, "count": by_day.get(d, 0)})
    return out
