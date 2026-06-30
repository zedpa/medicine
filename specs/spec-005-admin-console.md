# Spec-005 账号管理后台 + 统计看板

状态: ✅ 完成（T1–T2） · 负责人: web · 关联: [[spec-004 账号授权]](spec-004-multi-tenant-auth.md) · 方法: SDD（先 spec → 先验证 → 后实现 → 回写需求）

## 1. 背景与目标

spec-004 已落地账号授权(登录/注册)与按用户隔离的对话历史，且每个账号带 `role`(admin/user)，但 admin 角色目前**只用于 bootstrap 标识**，没有任何管理界面：admin 无法看全站用户、改角色、重置密码、删账号，也看不到整体使用情况。

目标：给 **admin** 一个后台视图，含两块：
1. **统计看板**：全站使用概览（用户/会话/消息规模、各用户活跃度、热门查询药材、按日活跃趋势）。
2. **账号管理**：列出所有用户，支持新建用户、改角色、重置密码、删除用户。

坚持本项目原则：
- **P3 不造假**：统计只来自真实的账号库与历史库聚合，无预置/编造数字；空库如实显示 0。
- **P5 口径集中**：看板「热门药材 Top N」「趋势天数」等展示口径写进 `config/pipeline.yaml › admin`，改动记 CHANGELOG。
- **离线可测**：统计为**纯聚合函数**(`src/stats.py`)，输入是 users/conversations 列表，输出是聚合 dict，临时数据即可单测；不触网、不依赖 Streamlit。
- **最小权限**：后台仅 `role==admin` 可见可达；非 admin 即便构造请求也拿不到（视图在服务端按角色渲染）。

## 2. 范围（任务切分）

| 任务 | 名称 | 交付 | 状态 |
|---|---|---|---|
| **T1** | 统计聚合层 + store 支撑 | `src/stats.py` 纯聚合函数；`UserStore.set_role`；`HistoryStore.export_all`/`list_all`(跨 owner) | ✅ 9 单测绿 |
| **T2** | 管理后台 UI | `web/app.py` 加 admin 门控视图：统计看板(指标+图表) + 账号管理(增/删/改角色/重置密码) | ✅ 4 E2E 绿 + 实景验收 |

## 3. 数据来源与模型

聚合输入（均已存在，T1 仅补跨 owner 读取）：
- `users`：`{username, name, email, role, created_at}`（`UserStore.list_users()`）。
- `conversations`：`{owner, created_at, updated_at, n_messages}` + 结果快照里的 `results[].result.{query,herb,found}`。

聚合输出（纯函数，全部可 JSON 序列化）：

```
overview(users, convs) -> {
  "n_users": int, "n_admins": int, "n_conversations": int,
  "n_messages": int, "active_users": int,          # 至少 1 条会话的用户数
}
per_user(users, convs) -> [ {
  "username","role","n_conversations","n_messages","last_active"  # last_active=最近 updated_at|None
}, ... ]                                            # 按 n_conversations 降序, 再按 username
herb_popularity(convs, top_n) -> [ {
  "herb": str, "count": int, "found": int          # herb=结果的 chinese|latin|query; found=found=True 次数
}, ... ]                                            # 按 count 降序, 取前 top_n
activity_by_day(convs, days) -> [ {"date": "YYYY-MM-DD", "count": int}, ... ]
                                                    # 近 days 天每天新建会话数, 升序, 缺失日补 0
```

## 4. T1 详细规格

### 4.1 store 支撑方法
- **FR-T1.1** `UserStore.set_role(username, role)`：仅改 `role`；不存在的 username 幂等忽略。
- **FR-T1.2** `HistoryStore.list_all(limit=None)`：跨 owner 返回会话元信息(含 `owner`)，`updated_at` 降序——供后台总览/调试，不做隔离（仅 admin 调用）。
- **FR-T1.3** `HistoryStore.export_all() -> list[dict]`：返回**全量**会话(含 `owner/created_at/updated_at/messages/results`)，供统计聚合。

### 4.2 纯聚合函数 `src/stats.py`
- **FR-T1.4** `overview / per_user / herb_popularity / activity_by_day` 如 §3；纯函数，不取时钟（`activity_by_day` 的「今天」由调用方注入 `today` 参数，保持确定性可测——同 spec-003/004 时间外部注入原则）。
- **FR-T1.5** `herb` 名取优先级：`result.herb.chinese` → `result.herb.latin` → `result.query`；`found` 仅统计 `result.found is True`。
- **FR-T1.6** 健壮性：缺字段/空 results/坏 JSON 不抛异常，按缺省(0/跳过)处理。

### 4.3 验收标准（= 测试，先写 `tests/test_stats.py`，离线构造数据）
- **AC-1** `overview`：2 用户(1 admin)、3 会话、合计 N 条消息、活跃用户=有会话的用户数，数值正确。
- **AC-2** `per_user`：按会话数降序；`last_active`=该用户最近 `updated_at`；无会话用户计 0 且 `last_active=None`。
- **AC-3** `herb_popularity`：跨会话跨结果聚合；名称优先级 chinese>latin>query；`found` 只数 found=True；按 count 降序取 top_n。
- **AC-4** `activity_by_day(today=固定值, days=7)`：返回 7 项、日期升序、含当天、无会话的日期补 0、计数按 `created_at` 的日期归集。
- **AC-5** 健壮性：空输入 ⇒ overview 全 0 / 列表为空；会话缺 results 或 results 为坏结构不报错。
- **AC-6** `UserStore.set_role` 改角色生效且不动其它字段；`HistoryStore.export_all` 跨 owner 全量返回且含 results。

## 5. T2 详细规格（管理后台 UI）

### 5.1 功能需求
- **FR-T2.1** 角色门：仅当 `role==admin`，侧边栏显示「🛠 管理后台 / ← 返回助手」切换；非 admin 完全不渲染入口与视图。
- **FR-T2.2** 视图切换用 `st.session_state.view in {"chat","admin"}`；admin 视图替换主区(不渲染聊天/结果面板)。
- **FR-T2.3** 统计看板：顶部 `st.metric` 四指标(用户/会话/消息/活跃用户)；热门药材 Top N 条形图(`st.bar_chart`)+ 表；近 N 天活跃趋势折线(`st.line_chart`)；各用户活跃度表(`st.dataframe`)。
- **FR-T2.4** 账号管理：用户表(用户名/姓名/邮箱/角色/创建时间/会话数)；每行可**改角色**(admin↔user)、**重置密码**(输入新口令→`Hasher.hash`→`set_password`)、**删除**。
- **FR-T2.5** 新建用户表单：用户名/姓名/邮箱/初始口令/角色 → 校验口令策略 → `Hasher.hash` 注入 `UserStore.upsert`(created_at 注入)。
- **FR-T2.6** 安全护栏：**不可删除自己**；**不可删除/降级最后一个 admin**(系统须至少留 1 个 admin)，否则给出明确告警并拒绝。
- **FR-T2.7** 口径集中：`herb_top_n`、`activity_days` 读 `config › admin`。

### 5.2 验收标准（Playwright E2E，临时 auth+history 库隔离）
- **AC-7** admin 登录后侧边栏可见「管理后台」入口；点击进入看到「统计看板」「账号管理」与四指标。
- **AC-8** 普通用户(user)登录后**看不到**管理后台入口(隔离)。
- **AC-9** admin 在账号管理新建一个用户 → 用户表出现该用户；改其角色为 admin 后再删除该用户 → 从表中消失。
- **AC-10** 末位 admin 保护：尝试删除/降级唯一 admin(自己)被拒并提示。

## 6. 配置（`config/pipeline.yaml › admin`，P5）

```yaml
admin:
  herb_top_n: 10          # 看板「热门药材」取前 N
  activity_days: 14       # 看板「活跃趋势」回看天数
```

## 7. SDD 执行顺序
1. T1：先写 `tests/test_stats.py`(红) → 实现 `src/stats.py` + `UserStore.set_role` + `HistoryStore.export_all/list_all`(绿)。
2. T2：写/调 E2E(红) → 改 `web/app.py` 加 admin 视图(绿) → Playwright 实景验收 UI。
3. 回写：CHANGELOG / 需求文档 / 本 spec 标 ✅。

## 8. 风险与边界
- **大库性能**：`export_all` 全量载入做聚合，小规模(数十用户/数百会话)足够；若日后量大，改为 SQL 侧聚合(`GROUP BY owner`、按日 `substr(created_at,1,10)`)，AC 不变。
- **热门药材口径**：基于结果快照(真实跑过的分析)，非用户输入文本——更准确反映「真正分析过的药材」；未跑出结果的提问不计入。
- **删除即不可逆**：删除用户不级联删其历史(历史按 owner 留存)，仅移除账号；如需连带清理，另开 spec。
- **最小权限**：后台按服务端角色渲染；非 admin 无入口、无视图代码路径。
