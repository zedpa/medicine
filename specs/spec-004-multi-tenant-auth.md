# Spec-004 账号授权与多租户（按用户隔离）

状态: ✅ 完成（T1–T3） · 负责人: web · 关联: [[spec-003 对话历史]](spec-003-conversation-history.md) · 方法: SDD（先 spec → 先验证 → 后实现 → 回写需求）

## 1. 背景与目标

现状：`web/app.py` **无任何认证**，对话历史（spec-003）全局共享一张 `conversations` 表 —— 任何能打开页面的人都看到**所有人**的历史。生产部署仅靠 Nginx basic-auth 兜底（单一口令，无账号概念、无数据隔离）。

目标：引入**账号授权**（登录/注册/登出）与**多租户数据隔离**（每个账号只见自己的对话历史）。

### 调研结论（开源社区 · 优先成熟方案）

| 方案 | 成熟度 | 取舍 |
|---|---|---|
| **streamlit-authenticator** v0.4.2 · 2.1k★ · 活跃维护 | 高 | ✅ **采用**：自包含，无需外部 IdP；bcrypt 哈希、Cookie/JWT 会话、注册/改密/找回控件、角色（admin/user）。账号表归本项目所有，正好挂到历史层做 owner 隔离 |
| 原生 `st.login()` + OIDC | 官方内置（≥1.42） | ❌ 需额外运维 Keycloak/Auth0；本项目自托管、无企业 IdP，偏重 |
| Authlib / 自研 | 高 | ❌ 重复造轮子，违背「优先成熟方案」 |

- **认证库**：`streamlit-authenticator`（bcrypt + Cookie，`Hasher.hash` / `Hasher.check_pw`，`Authenticate(credentials, cookie_name, cookie_key, cookie_expiry_days)`）。
- **租户模型**：**按用户隔离**（每账号一片历史），不引入组织/租户层级（YAGNI）。

坚持本项目原则：
- **P3 不造假**：账号只存真实注册用户；历史按真实登录用户归属。
- **P5 口径集中**：账号库位置、Cookie 有效期、是否开放注册、默认角色写进 `config/pipeline.yaml › auth`，改动记 CHANGELOG。
- **离线可测**：账号存储层（`UserStore`）与历史隔离逻辑为 sqlite 之上的纯持久化逻辑，临时库即可单测；**不触网、不依赖 Streamlit 运行时、不在库内做哈希/取时钟**。
- **密钥不入库**：Cookie 加密 key（`AUTH_COOKIE_KEY`）、初始管理员口令（`ADMIN_USER`/`ADMIN_PASSWORD`）仅来自环境变量 / `.env`；密码以 bcrypt **哈希**入库，绝不存明文；`data/auth.sqlite` 与历史库一并 gitignore。

## 2. 范围（任务切分）

| 任务 | 名称 | 交付 | 状态 |
|---|---|---|---|
| **T1** | 账号存储层 `UserStore` | sqlite 持久化账号（增/查/列/改密/删 + 产 stauth credentials dict），纯逻辑可单测 | ✅ 8 单测绿 |
| **T2** | 历史层按 `owner` 隔离 | `HistoryStore` 所有方法加 `owner` scope + 列迁移；跨用户不可见/不可改/不可删 | ✅ history 17 单测绿 |
| **T3** | web 集成 | `web/app.py` 接 streamlit-authenticator（登录/注册/登出、admin 种子），历史按登录用户 scope；Playwright E2E 验隔离 | ✅ 2 E2E 绿 + 实景验收 |

## 3. 数据模型

### 3.1 账号（auth.sqlite，独立于 history.sqlite / cache.sqlite）

```
users(
  username     TEXT PRIMARY KEY,   # 登录名（唯一）
  name         TEXT,               # 展示名
  email        TEXT,
  password_hash TEXT,              # bcrypt 哈希（UI/bootstrap 层用 Hasher.hash 生成后注入）
  role         TEXT,               # "admin" | "user"，默认 "user"
  created_at   TEXT                # ISO8601，调用方注入
)
```

- 密码**只存哈希**。哈希与时间戳由**调用方注入**，`UserStore` 不调 `Hasher` / `datetime.now()` —— 保证存储层纯净、确定性可单测（与 spec-003 时间外部注入同理）。
- `credentials()` 产出 streamlit-authenticator 所需结构：
  ```
  {"usernames": {username: {"name":.., "email":.., "password": <hash>, "roles": [role]}}}
  ```

### 3.2 历史归属（在 spec-003 表上演进）

`conversations` 表加列 `owner TEXT`（= `username`）。所有读写按 `owner` scope；跨 owner 的 `get/set_title/delete` 视同不存在（隔离在查询层强制，不靠 UI 自觉）。

## 4. T1 详细规格（UserStore）

### 4.1 功能需求
- **FR-T1.1** `UserStore(db_path)`：建表幂等；并发安全（沿用 `_LOCK`）。
- **FR-T1.2** `upsert(user: dict)`：按 `username` upsert；字段 `username/name/email/password_hash/role/created_at`。
- **FR-T1.3** `get(username) -> dict | None`：不存在返回 `None`（含 `password_hash`，供登录校验/迁移）。
- **FR-T1.4** `list_users() -> list[dict]`：按 `created_at` 升序返回 `username/name/email/role/created_at`（**不含** `password_hash`），供管理。
- **FR-T1.5** `set_password(username, password_hash)`：仅改哈希；不存在的 username 幂等忽略。
- **FR-T1.6** `delete(username)`：删单条；幂等。
- **FR-T1.7** `count() -> int`：账号数（供 bootstrap 判断是否需种子 admin）。
- **FR-T1.8** `credentials() -> dict`：产 streamlit-authenticator 结构（含哈希），`roles` 为 `[role]`。空库 ⇒ `{"usernames": {}}`。

### 4.2 验收标准（= 测试，先写 `tests/test_auth.py`，离线临时库）
- **AC-1** `upsert` 后 `get` 深度还原（含 unicode 名字/邮箱）；`get` 含 `password_hash`、`role`、`created_at`。
- **AC-2** `get("缺")` ⇒ `None`。
- **AC-3** 同 `username` 再 `upsert` ⇒ 覆盖，不产生第二行（`count()==1`）。
- **AC-4** `list_users()` 按 `created_at` 升序；**不含** `password_hash`；含 `role`。
- **AC-5** `set_password` 只改哈希、不动 name/email/role；改不存在的 username 不报错。
- **AC-6** `delete` 幂等（删两次、删不存在不报错），删后 `get` ⇒ `None`、`count` 减一。
- **AC-7** `credentials()` 结构正确：`{"usernames": {u: {"name","email","password","roles":[role]}}}`；空库 ⇒ `{"usernames": {}}`。
- **AC-8** 落盘：新实例读同一文件能取到（证明持久化非内存）。

## 5. T2 详细规格（HistoryStore 按 owner 隔离）

### 5.1 功能需求
- **FR-T2.1** 建表/迁移：`conversations` 加 `owner TEXT` 列（旧库 `ALTER TABLE ADD COLUMN`）。旧行 `owner` 为 NULL ⇒ 对任何登录用户**不可见**（不丢数据，仅不归属）；可经环境变量 `HISTORY_LEGACY_OWNER` 一次性认领（`UPDATE … WHERE owner IS NULL`）。
- **FR-T2.2** `save(conv)`：`conv` 含 `owner`，随会话落库。
- **FR-T2.3** `get(conv_id, owner) -> dict | None`：`WHERE id=? AND owner=?`；owner 不匹配 ⇒ `None`（隔离）。
- **FR-T2.4** `list(owner, limit=None)`：`WHERE owner=?`，其余同 spec-003（updated_at 降序、仅元信息）。
- **FR-T2.5** `set_title(conv_id, owner, title)`：`WHERE id=? AND owner=?`；跨 owner 无效（幂等）。
- **FR-T2.6** `delete(conv_id, owner)`：`WHERE id=? AND owner=?`；跨 owner 无效。
- **FR-T2.7** `prune(owner, keep)`：**按 owner 各自** prune（A 的历史不挤掉 B 的）。

### 5.2 验收标准（更新 `tests/test_history.py` + 新隔离用例；`tests/test_snapshot.py` 同步签名）
- **AC-9** A、B 各存若干会话：`list("A")` 只见 A 的；`list("B")` 只见 B 的。
- **AC-10** `get(A_conv, owner="B")` ⇒ `None`（跨用户不可读）。
- **AC-11** `delete(A_conv, owner="B")` 无效（A 仍在）；`delete(A_conv, owner="A")` 生效。
- **AC-12** `set_title(A_conv, owner="B", …)` 无效；`owner="A"` 生效。
- **AC-13** `prune("A", keep=2)` 只裁 A 的历史，B 的不受影响。
- **AC-14** spec-003 原有 AC（标题派生、roundtrip、快照）在带 owner 后仍绿。

## 6. T3 详细规格（web 集成）

### 6.1 功能需求
- **FR-T3.1** 启动 bootstrap：若 `UserStore.count()==0` 且设了 `ADMIN_USER`/`ADMIN_PASSWORD`，用 `Hasher.hash` 种入 admin（role=admin，created_at 注入）。
- **FR-T3.2** `Authenticate(store.credentials(), cookie_name, AUTH_COOKIE_KEY, cookie_expiry_days)`；`AUTH_COOKIE_KEY` 缺失则随机生成并告警（重启即失效，仅开发兜底）。
- **FR-T3.3** 登录门：`authenticator.login()`；`authentication_status` 为 None/False 时只渲染登录（+ 注册，若 `allow_self_register`）后 `st.stop()`，主应用不渲染。
- **FR-T3.4** 注册：`authenticator.register_user()` 成功后把新账号（bcrypt 哈希、created_at 注入、role=default_role）持久化到 `UserStore`。
- **FR-T3.5** 登录后：侧边栏顶部显示当前用户 + `authenticator.logout()`；**所有** `HistoryStore` 调用传 `owner=st.session_state["username"]`。
- **FR-T3.6** 历史 `_history()` / `_save_current()` / `_open_conversation()` 全部按当前登录用户 scope。

### 6.2 验收标准（Playwright E2E，临时 auth+history 库隔离）
- **AC-15** 未登录访问 ⇒ 见登录表单，**看不到**聊天输入框 / 历史列表。
- **AC-16** 注册用户 A → 登录 → 提问产生一轮对话 → 登出 → 注册/登录用户 B：B 的侧边栏**看不到** A 的会话（隔离）。
- **AC-17** A 重新登录 ⇒ 仍见自己的历史（跨会话持久 + 归属正确）。

## 7. 配置（`config/pipeline.yaml › auth`，P5 集中口径）

```yaml
auth:
  enabled: true
  db_path: "data/auth.sqlite"      # 独立账号库
  cookie_name: "tcm_auth"
  cookie_expiry_days: 7            # 免登天数
  allow_self_register: true        # 是否开放自助注册
  default_role: "user"             # 自助注册默认角色
```

环境变量（**不入库**）：`AUTH_COOKIE_KEY`（Cookie 加密）、`ADMIN_USER`/`ADMIN_PASSWORD`（首启种子 admin）、`AUTH_DB_PATH`（E2E 隔离覆盖）。

## 8. SDD 执行顺序

1. T1：先写 `tests/test_auth.py`（红）→ 实现 `src/auth.py`（绿）。
2. T2：更新/新增 `tests/test_history.py` 隔离用例（红）→ 改造 `HistoryStore`（绿）→ `tests/test_snapshot.py` 同步签名。
3. T3：写/调 E2E（红）→ 改 `web/app.py` 接入（绿）→ Playwright 实景验收 UI。
4. 回写：CHANGELOG、需求文档、requirements、本 spec 标 ✅。

## 9. 风险与边界

- **并发写**：沿用进程内 `_LOCK` + sqlite「最后写入胜」，小规模（数十用户）足够；非高并发 SaaS。
- **Cookie key 轮换**：更换 `AUTH_COOKIE_KEY` 会使所有现存会话失效（需重登），属预期。
- **无邮件找回**：`forgot_password` 仅生成新口令于界面显示（无 SMTP），由 admin 转交；不接邮件服务。
- **legacy 历史**：迁移不删旧行，但默认不归属任何人；如需保留单人旧历史，部署时设 `HISTORY_LEGACY_OWNER` 认领。
- **角色用途**：本期只存 role，admin 暂仅用于 bootstrap 标识；账号管理后台（增删用户）列为后续，不在本 spec。
- **部署**：仍建议置于 Nginx 之后（HTTPS）；应用层认证替代/补强 basic-auth，安全组只放 80/443。
