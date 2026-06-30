"""spec-003 T1 + spec-004 T2 验收: 对话历史存储层(离线临时 sqlite, 时间外部注入)。

存储层保持纯净: 不调 datetime.now()/uuid, 时间与 id 由调用方注入 -> 确定性可测。
spec-004: 所有读写按 owner(=username) 隔离, 跨用户不可见/不可改/不可删。
"""
from src.history import HistoryStore, _derive_title


def _conv(cid, ts, messages, owner="u1", title=None):
    return {
        "id": cid,
        "owner": owner,
        "title": title or _derive_title(messages, 24),
        "created_at": ts,
        "updated_at": ts,
        "messages": messages,
    }


def test_derive_title():  # AC-1
    msgs = [{"role": "user", "content": "黄芪 治疗 糖尿病"},
            {"role": "assistant", "content": "好的"}]
    assert _derive_title(msgs, 10) == "黄芪 治疗 糖尿病"      # ≤10 不截
    assert _derive_title(msgs, 4) == "黄芪 治…"               # 截 4 + 省略号
    # 首条非 user -> 跳到首个 user
    msgs2 = [{"role": "assistant", "content": "你好"},
             {"role": "user", "content": "肉桂"}]
    assert _derive_title(msgs2, 24) == "肉桂"
    # 无 user 消息 -> 回退
    assert _derive_title([{"role": "assistant", "content": "x"}], 24) == "新对话"
    assert _derive_title([], 24) == "新对话"
    # 首尾空白去除
    assert _derive_title([{"role": "user", "content": "  当归  "}], 24) == "当归"


def test_save_get_roundtrip_unicode(tmp_path):  # AC-2
    store = HistoryStore(str(tmp_path / "h.sqlite"))
    msgs = [{"role": "user", "content": "黄芪、当归 → 高血压?"},
            {"role": "assistant", "content": "已分析 ✓"}]
    conv = _conv("c1", "2026-06-30T10:00:00", msgs, owner="li")
    store.save(conv)
    got = store.get("c1", owner="li")
    assert got["messages"] == msgs            # 深度相等, 中文/特殊字符不坏
    assert got["title"] == "黄芪、当归 → 高血压?"
    assert got["created_at"] == "2026-06-30T10:00:00"


def test_get_missing_returns_none(tmp_path):  # AC-3
    store = HistoryStore(str(tmp_path / "h.sqlite"))
    assert store.get("nope", owner="u1") is None


def test_save_upsert_overwrites(tmp_path):  # AC-4
    store = HistoryStore(str(tmp_path / "h.sqlite"))
    store.save(_conv("c1", "2026-06-30T10:00:00", [{"role": "user", "content": "v1"}]))
    store.save(_conv("c1", "2026-06-30T11:00:00", [{"role": "user", "content": "v2"}]))
    got = store.get("c1", owner="u1")
    assert got["messages"] == [{"role": "user", "content": "v2"}]   # 取最新
    assert len(store.list("u1")) == 1                               # 不产生两行


def test_list_order_meta_and_limit(tmp_path):  # AC-5
    store = HistoryStore(str(tmp_path / "h.sqlite"))
    store.save(_conv("a", "2026-06-30T09:00:00", [{"role": "user", "content": "早"}]))
    store.save(_conv("b", "2026-06-30T12:00:00",
                     [{"role": "user", "content": "晚"}, {"role": "assistant", "content": "x"}]))
    store.save(_conv("c", "2026-06-30T10:00:00", [{"role": "user", "content": "中"}]))
    lst = store.list("u1")
    assert [r["id"] for r in lst] == ["b", "c", "a"]   # updated_at 降序
    assert lst[0]["n_messages"] == 2
    assert "messages" not in lst[0]                    # 列表只含元信息
    assert [r["id"] for r in store.list("u1", limit=2)] == ["b", "c"]


def test_delete_idempotent(tmp_path):  # AC-6
    store = HistoryStore(str(tmp_path / "h.sqlite"))
    store.save(_conv("c1", "2026-06-30T10:00:00", [{"role": "user", "content": "x"}]))
    store.delete("c1", owner="u1")
    assert store.get("c1", owner="u1") is None
    assert all(r["id"] != "c1" for r in store.list("u1"))
    store.delete("c1", owner="u1")          # 删不存在不报错
    store.delete("never", owner="u1")


def test_set_title_rename(tmp_path):  # 重命名(三点菜单)
    store = HistoryStore(str(tmp_path / "h.sqlite"))
    store.save(_conv("c1", "2026-06-30T10:00:00", [{"role": "user", "content": "肉桂"}]))
    store.set_title("c1", "u1", "肉桂→高血压 研究")
    assert store.get("c1", owner="u1")["title"] == "肉桂→高血压 研究"
    # 重命名不动消息
    assert store.get("c1", owner="u1")["messages"] == [{"role": "user", "content": "肉桂"}]
    # 列表也反映新标题
    assert store.list("u1")[0]["title"] == "肉桂→高血压 研究"
    store.set_title("nope", "u1", "x")          # 不存在的 id 不报错


def test_prune_keeps_newest(tmp_path):  # AC-7
    store = HistoryStore(str(tmp_path / "h.sqlite"))
    for i in range(5):
        store.save(_conv(f"c{i}", f"2026-06-30T1{i}:00:00",
                         [{"role": "user", "content": f"q{i}"}]))
    store.prune("u1", keep=3)
    ids = {r["id"] for r in store.list("u1")}
    assert ids == {"c2", "c3", "c4"}      # 最新 3 条; 最旧 c0/c1 被删


def test_persists_to_disk(tmp_path):  # AC-8
    db = str(tmp_path / "h.sqlite")
    HistoryStore(db).save(_conv("c1", "2026-06-30T10:00:00",
                                [{"role": "user", "content": "落盘?"}], owner="li"))
    # 新实例读同一文件 -> 能读到 (证明持久化, 非内存)
    again = HistoryStore(db)
    assert again.get("c1", owner="li")["messages"] == [{"role": "user", "content": "落盘?"}]


# ---- spec-004 T2: 按 owner 隔离 ----

def test_list_isolates_by_owner(tmp_path):  # AC-9
    store = HistoryStore(str(tmp_path / "h.sqlite"))
    store.save(_conv("a1", "2026-06-30T10:00:00", [{"role": "user", "content": "A的"}], owner="A"))
    store.save(_conv("a2", "2026-06-30T11:00:00", [{"role": "user", "content": "A的2"}], owner="A"))
    store.save(_conv("b1", "2026-06-30T12:00:00", [{"role": "user", "content": "B的"}], owner="B"))
    assert {r["id"] for r in store.list("A")} == {"a1", "a2"}
    assert {r["id"] for r in store.list("B")} == {"b1"}


def test_get_cross_owner_denied(tmp_path):  # AC-10
    store = HistoryStore(str(tmp_path / "h.sqlite"))
    store.save(_conv("a1", "2026-06-30T10:00:00", [{"role": "user", "content": "A的"}], owner="A"))
    assert store.get("a1", owner="A") is not None
    assert store.get("a1", owner="B") is None      # B 读不到 A 的会话


def test_delete_cross_owner_denied(tmp_path):  # AC-11
    store = HistoryStore(str(tmp_path / "h.sqlite"))
    store.save(_conv("a1", "2026-06-30T10:00:00", [{"role": "user", "content": "A的"}], owner="A"))
    store.delete("a1", owner="B")                  # B 删不动 A 的
    assert store.get("a1", owner="A") is not None
    store.delete("a1", owner="A")                  # A 自己删生效
    assert store.get("a1", owner="A") is None


def test_set_title_cross_owner_denied(tmp_path):  # AC-12
    store = HistoryStore(str(tmp_path / "h.sqlite"))
    store.save(_conv("a1", "2026-06-30T10:00:00", [{"role": "user", "content": "原标题"}],
                     owner="A", title="原标题"))
    store.set_title("a1", "B", "B 改的")           # 跨 owner 无效
    assert store.get("a1", owner="A")["title"] == "原标题"
    store.set_title("a1", "A", "A 改的")           # 本人生效
    assert store.get("a1", owner="A")["title"] == "A 改的"


def test_prune_isolates_by_owner(tmp_path):  # AC-13
    store = HistoryStore(str(tmp_path / "h.sqlite"))
    for i in range(4):
        store.save(_conv(f"a{i}", f"2026-06-30T1{i}:00:00",
                         [{"role": "user", "content": f"a{i}"}], owner="A"))
    store.save(_conv("b0", "2026-06-30T09:00:00", [{"role": "user", "content": "b0"}], owner="B"))
    store.prune("A", keep=2)                        # 只裁 A 的
    assert {r["id"] for r in store.list("A")} == {"a2", "a3"}
    assert {r["id"] for r in store.list("B")} == {"b0"}   # B 不受影响
