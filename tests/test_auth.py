"""spec-004 T1 验收 AC-1…AC-8: 账号存储层 UserStore(离线临时 sqlite)。

存储层保持纯净: 不调 Hasher/datetime.now(), 哈希与时间由调用方注入 -> 确定性可测。
password_hash 此处用占位串(真实 bcrypt 哈希在 UI/bootstrap 层生成), 存储层只负责存取。
"""
from src.auth import UserStore


def _user(username, ts, name=None, email=None, role="user", pwd="HASH"):
    return {
        "username": username,
        "name": name or username,
        "email": email or f"{username}@ex.com",
        "password_hash": pwd,
        "role": role,
        "created_at": ts,
    }


def test_upsert_get_roundtrip_unicode(tmp_path):  # AC-1
    store = UserStore(str(tmp_path / "u.sqlite"))
    store.upsert(_user("li", "2026-06-30T10:00:00", name="李明",
                       email="李@例.com", role="admin", pwd="$2b$12$abc"))
    got = store.get("li")
    assert got["name"] == "李明"
    assert got["email"] == "李@例.com"
    assert got["role"] == "admin"
    assert got["password_hash"] == "$2b$12$abc"   # 含哈希(供登录校验)
    assert got["created_at"] == "2026-06-30T10:00:00"


def test_get_missing_returns_none(tmp_path):  # AC-2
    store = UserStore(str(tmp_path / "u.sqlite"))
    assert store.get("nobody") is None


def test_upsert_overwrites(tmp_path):  # AC-3
    store = UserStore(str(tmp_path / "u.sqlite"))
    store.upsert(_user("li", "2026-06-30T10:00:00", name="旧名"))
    store.upsert(_user("li", "2026-06-30T11:00:00", name="新名"))
    assert store.get("li")["name"] == "新名"
    assert store.count() == 1                      # 不产生两行


def test_list_users_order_no_hash(tmp_path):  # AC-4
    store = UserStore(str(tmp_path / "u.sqlite"))
    store.upsert(_user("b", "2026-06-30T12:00:00"))
    store.upsert(_user("a", "2026-06-30T09:00:00", role="admin"))
    store.upsert(_user("c", "2026-06-30T10:00:00"))
    lst = store.list_users()
    assert [u["username"] for u in lst] == ["a", "c", "b"]   # created_at 升序
    assert "password_hash" not in lst[0]                     # 列表不泄哈希
    assert lst[0]["role"] == "admin"


def test_set_password_only_changes_hash(tmp_path):  # AC-5
    store = UserStore(str(tmp_path / "u.sqlite"))
    store.upsert(_user("li", "2026-06-30T10:00:00", name="李", role="admin", pwd="OLD"))
    store.set_password("li", "NEW")
    got = store.get("li")
    assert got["password_hash"] == "NEW"
    assert got["name"] == "李" and got["role"] == "admin"    # 其余不动
    store.set_password("nope", "X")                          # 不存在不报错


def test_delete_idempotent(tmp_path):  # AC-6
    store = UserStore(str(tmp_path / "u.sqlite"))
    store.upsert(_user("li", "2026-06-30T10:00:00"))
    store.delete("li")
    assert store.get("li") is None
    assert store.count() == 0
    store.delete("li")          # 删两次不报错
    store.delete("never")


def test_credentials_shape(tmp_path):  # AC-7
    store = UserStore(str(tmp_path / "u.sqlite"))
    assert store.credentials() == {"usernames": {}}          # 空库
    store.upsert(_user("li", "2026-06-30T10:00:00", name="李明",
                       email="li@ex.com", role="admin", pwd="$2b$12$h"))
    cred = store.credentials()
    assert cred == {"usernames": {"li": {
        "name": "李明", "email": "li@ex.com",
        "password": "$2b$12$h", "roles": ["admin"]}}}


def test_persists_to_disk(tmp_path):  # AC-8
    db = str(tmp_path / "u.sqlite")
    UserStore(db).upsert(_user("li", "2026-06-30T10:00:00", pwd="$2b$12$disk"))
    again = UserStore(db)                                    # 新实例读同一文件
    assert again.get("li")["password_hash"] == "$2b$12$disk"
