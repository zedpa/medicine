"""spec-003 T1 验收 AC-1…AC-8: 对话历史存储层(离线临时 sqlite, 时间外部注入)。

存储层保持纯净: 不调 datetime.now()/uuid, 时间与 id 由调用方注入 -> 确定性可测。
"""
from src.history import HistoryStore, _derive_title


def _conv(cid, ts, messages, title=None):
    return {
        "id": cid,
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
    conv = _conv("c1", "2026-06-30T10:00:00", msgs)
    store.save(conv)
    got = store.get("c1")
    assert got["messages"] == msgs            # 深度相等, 中文/特殊字符不坏
    assert got["title"] == "黄芪、当归 → 高血压?"
    assert got["created_at"] == "2026-06-30T10:00:00"


def test_get_missing_returns_none(tmp_path):  # AC-3
    store = HistoryStore(str(tmp_path / "h.sqlite"))
    assert store.get("nope") is None


def test_save_upsert_overwrites(tmp_path):  # AC-4
    store = HistoryStore(str(tmp_path / "h.sqlite"))
    store.save(_conv("c1", "2026-06-30T10:00:00", [{"role": "user", "content": "v1"}]))
    store.save(_conv("c1", "2026-06-30T11:00:00", [{"role": "user", "content": "v2"}]))
    got = store.get("c1")
    assert got["messages"] == [{"role": "user", "content": "v2"}]   # 取最新
    assert len(store.list()) == 1                                   # 不产生两行


def test_list_order_meta_and_limit(tmp_path):  # AC-5
    store = HistoryStore(str(tmp_path / "h.sqlite"))
    store.save(_conv("a", "2026-06-30T09:00:00", [{"role": "user", "content": "早"}]))
    store.save(_conv("b", "2026-06-30T12:00:00",
                     [{"role": "user", "content": "晚"}, {"role": "assistant", "content": "x"}]))
    store.save(_conv("c", "2026-06-30T10:00:00", [{"role": "user", "content": "中"}]))
    lst = store.list()
    assert [r["id"] for r in lst] == ["b", "c", "a"]   # updated_at 降序
    assert lst[0]["n_messages"] == 2
    assert "messages" not in lst[0]                    # 列表只含元信息
    assert [r["id"] for r in store.list(limit=2)] == ["b", "c"]


def test_delete_idempotent(tmp_path):  # AC-6
    store = HistoryStore(str(tmp_path / "h.sqlite"))
    store.save(_conv("c1", "2026-06-30T10:00:00", [{"role": "user", "content": "x"}]))
    store.delete("c1")
    assert store.get("c1") is None
    assert all(r["id"] != "c1" for r in store.list())
    store.delete("c1")          # 删不存在不报错
    store.delete("never")


def test_set_title_rename(tmp_path):  # 重命名(三点菜单)
    store = HistoryStore(str(tmp_path / "h.sqlite"))
    store.save(_conv("c1", "2026-06-30T10:00:00", [{"role": "user", "content": "肉桂"}]))
    store.set_title("c1", "肉桂→高血压 研究")
    assert store.get("c1")["title"] == "肉桂→高血压 研究"
    # 重命名不动消息
    assert store.get("c1")["messages"] == [{"role": "user", "content": "肉桂"}]
    # 列表也反映新标题
    assert store.list()[0]["title"] == "肉桂→高血压 研究"
    store.set_title("nope", "x")          # 不存在的 id 不报错


def test_prune_keeps_newest(tmp_path):  # AC-7
    store = HistoryStore(str(tmp_path / "h.sqlite"))
    for i in range(5):
        store.save(_conv(f"c{i}", f"2026-06-30T1{i}:00:00",
                         [{"role": "user", "content": f"q{i}"}]))
    store.prune(keep=3)
    ids = {r["id"] for r in store.list()}
    assert ids == {"c2", "c3", "c4"}      # 最新 3 条; 最旧 c0/c1 被删


def test_persists_to_disk(tmp_path):  # AC-8
    db = str(tmp_path / "h.sqlite")
    HistoryStore(db).save(_conv("c1", "2026-06-30T10:00:00",
                                [{"role": "user", "content": "落盘?"}]))
    # 新实例读同一文件 -> 能读到 (证明持久化, 非内存)
    again = HistoryStore(db)
    assert again.get("c1")["messages"] == [{"role": "user", "content": "落盘?"}]
