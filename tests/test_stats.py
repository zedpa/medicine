"""spec-005 T1 验收 AC-1…AC-6: 统计聚合(纯函数, 时间外部注入) + store 支撑。

聚合输入是 users / conversations 列表(dict), 输出可序列化 dict -> 离线构造即可测,
不触网、不依赖 Streamlit。activity_by_day 的「今天」由调用方注入, 保持确定性。
"""
from src.stats import overview, per_user, herb_popularity, activity_by_day
from src.auth import UserStore
from src.history import HistoryStore


def _users():
    return [
        {"username": "admin", "name": "管理员", "email": "a@x.com",
         "role": "admin", "created_at": "2026-06-20T09:00:00"},
        {"username": "li", "name": "李", "email": "l@x.com",
         "role": "user", "created_at": "2026-06-21T09:00:00"},
        {"username": "wang", "name": "王", "email": "w@x.com",
         "role": "user", "created_at": "2026-06-22T09:00:00"},   # 无会话
    ]


def _result(query, chinese=None, latin=None, found=True):
    return {"result": {"query": query, "found": found,
                       "herb": {"chinese": chinese, "latin": latin}}}


def _convs():
    return [
        {"owner": "admin", "created_at": "2026-06-25T10:00:00",
         "updated_at": "2026-06-25T10:30:00", "messages": [{"role": "user", "content": "肉桂"},
         {"role": "assistant", "content": "ok"}],
         "results": [_result("肉桂", chinese="肉桂")]},
        {"owner": "li", "created_at": "2026-06-25T11:00:00",
         "updated_at": "2026-06-26T08:00:00",
         "messages": [{"role": "user", "content": "黄芪"}],
         "results": [_result("黄芪", chinese="黄芪"), _result("肉桂", chinese="肉桂")]},
        {"owner": "li", "created_at": "2026-06-26T09:00:00",
         "updated_at": "2026-06-26T09:10:00",
         "messages": [{"role": "user", "content": "x"}, {"role": "assistant", "content": "y"},
                      {"role": "user", "content": "z"}],
         "results": [_result("unknownherb", found=False)]},
    ]


def test_overview():  # AC-1
    o = overview(_users(), _convs())
    assert o["n_users"] == 3
    assert o["n_admins"] == 1
    assert o["n_conversations"] == 3
    assert o["n_messages"] == 2 + 1 + 3       # 各会话 messages 累加
    assert o["active_users"] == 2             # admin, li 有会话; wang 无


def test_overview_empty():  # AC-5
    o = overview([], [])
    assert o == {"n_users": 0, "n_admins": 0, "n_conversations": 0,
                 "n_messages": 0, "active_users": 0}


def test_per_user():  # AC-2
    rows = per_user(_users(), _convs())
    by = {r["username"]: r for r in rows}
    assert [r["username"] for r in rows][0] == "li"     # li 2 会话, 居首
    assert by["li"]["n_conversations"] == 2
    assert by["li"]["n_messages"] == 1 + 3
    assert by["li"]["last_active"] == "2026-06-26T09:10:00"   # 最近 updated_at
    assert by["admin"]["n_conversations"] == 1
    assert by["wang"]["n_conversations"] == 0
    assert by["wang"]["last_active"] is None
    assert by["wang"]["role"] == "user"


def test_herb_popularity():  # AC-3
    pop = herb_popularity(_convs(), top_n=10)
    by = {r["herb"]: r for r in pop}
    assert by["肉桂"]["count"] == 2          # admin 1 + li 1
    assert by["肉桂"]["found"] == 2
    assert by["黄芪"]["count"] == 1
    assert by["unknownherb"]["count"] == 1
    assert by["unknownherb"]["found"] == 0   # found=False 不计入 found
    assert pop[0]["herb"] == "肉桂"           # count 降序
    assert len(herb_popularity(_convs(), top_n=1)) == 1   # top_n 截断


def test_herb_name_priority():  # AC-3 名称优先级 chinese>latin>query
    convs = [{"owner": "u", "created_at": "2026-06-25T10:00:00",
              "updated_at": "2026-06-25T10:00:00", "messages": [],
              "results": [_result("cinnamon", chinese=None, latin="Cinnamomum cassia"),
                          _result("ginseng", chinese=None, latin=None)]}]
    by = {r["herb"]: r for r in herb_popularity(convs, top_n=10)}
    assert "Cinnamomum cassia" in by          # 无 chinese 退到 latin
    assert "ginseng" in by                    # 无 chinese/latin 退到 query


def test_activity_by_day():  # AC-4
    rows = activity_by_day(_convs(), today="2026-06-26", days=7)
    assert len(rows) == 7
    assert [r["date"] for r in rows] == sorted(r["date"] for r in rows)   # 升序
    assert rows[-1]["date"] == "2026-06-26"            # 含当天
    by = {r["date"]: r["count"] for r in rows}
    assert by["2026-06-25"] == 2                        # 2 个会话 created 于 25 日
    assert by["2026-06-26"] == 1
    assert by["2026-06-24"] == 0                        # 无会话日补 0


def test_robust_to_bad_results():  # AC-5
    convs = [{"owner": "u", "created_at": "2026-06-25T10:00:00",
              "updated_at": "2026-06-25T10:00:00", "messages": [{"role": "user", "content": "q"}]},
             {"owner": "u", "created_at": "2026-06-25T11:00:00",
              "updated_at": "2026-06-25T11:00:00", "messages": [], "results": []}]
    assert overview([], convs)["n_messages"] == 1       # 缺 results 不报错
    assert herb_popularity(convs, top_n=5) == []        # 无结果 -> 空


def test_set_role(tmp_path):  # AC-6 (UserStore.set_role)
    store = UserStore(str(tmp_path / "u.sqlite"))
    store.upsert({"username": "li", "name": "李", "email": "l@x.com",
                  "password_hash": "H", "role": "user", "created_at": "2026-06-21T09:00:00"})
    store.set_role("li", "admin")
    got = store.get("li")
    assert got["role"] == "admin"
    assert got["name"] == "李" and got["password_hash"] == "H"   # 不动其它字段
    store.set_role("nope", "admin")                              # 不存在不报错


def test_history_export_all(tmp_path):  # AC-6 (HistoryStore.export_all/list_all)
    store = HistoryStore(str(tmp_path / "h.sqlite"))
    store.save({"id": "a1", "owner": "A", "title": "t", "created_at": "2026-06-25T10:00:00",
                "updated_at": "2026-06-25T10:00:00",
                "messages": [{"role": "user", "content": "肉桂"}],
                "results": [_result("肉桂", chinese="肉桂")]})
    store.save({"id": "b1", "owner": "B", "title": "t", "created_at": "2026-06-25T11:00:00",
                "updated_at": "2026-06-25T11:00:00", "messages": []})
    allc = store.export_all()
    assert {c["owner"] for c in allc} == {"A", "B"}          # 跨 owner 全量
    a = next(c for c in allc if c["owner"] == "A")
    assert a["results"][0]["result"]["herb"]["chinese"] == "肉桂"   # 含 results
    assert {c["owner"] for c in store.list_all()} == {"A", "B"}
    assert "n_messages" in store.list_all()[0]
