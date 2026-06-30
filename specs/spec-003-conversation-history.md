# Spec-003 侧边栏对话历史记录

状态: ✅ 完成（T1–T3） · 负责人: web · 关联: [[spec-002 研究闭环]](spec-002-research-closed-loop.md) · 方法: SDD（先 spec → 先验证 → 后实现 → 回写需求）

## 1. 背景与目标

现状（`web/app.py`）：对话与结果只存活在 `st.session_state`（单标签页内存），**浏览器刷新 / 新开标签页 / 重启服务即全部丢失**；侧边栏仅有「清空对话」。
学生连着查多味药、跨天对比时，无法回看「上次查黄芪治糖尿病」那一轮。

目标：在侧边栏加一个**持久化的对话历史列表**（类 ChatGPT 左栏），支持：列出历史会话 → 点击切换载入 → 新建会话 → 删除会话。
跨刷新、跨标签页、跨重启可恢复。

坚持本项目原则：
- **P3 不造假**：历史只存真实跑过的对话与产物路径，不预置/编造会话。
- **P5 口径集中**：存储位置、保留条数等写进 `config/pipeline.yaml › history`，改动记 CHANGELOG。
- **离线可测**：存储层为 sqlite 之上的纯持久化逻辑，用临时库即可单测，不触网、不依赖 Streamlit 运行时。

## 2. 范围（任务切分）

| 任务 | 名称 | 交付 | 状态 |
|---|---|---|---|
| **T1** | 历史存储层 `HistoryStore` | sqlite 持久化会话（增/查/列/改/删），纯逻辑可单测 | ✅ 已实现（8 单测绿） |
| **T2** | 侧边栏 UI 接入 | 侧边栏渲染历史列表 + 切换/新建/删除按钮，与 `session_state` 双向同步 | ✅ 已实现（3 E2E 绿） |
| **T3** | 结果快照 | 会话内分析结果的可序列化摘要随会话持久化，切换会话时重显结果面板 | ✅ 已实现（4 单测 + AC-15 E2E 绿） |

本次提交聚焦 **T1 存储层**（先写测试→实现）与 **T2 UI 契约**声明；T3 列为后续。

## 3. 数据模型

一条会话（conversation）记录，全部 JSON 可序列化：

```
{
  "id":         str,    # 主键，稳定唯一（调用方注入，见 NFR — 不在库内用时钟/随机生成）
  "title":      str,    # 展示标题，默认取首条用户消息前 N 字（_derive_title）
  "created_at": str,    # ISO8601，调用方注入
  "updated_at": str,    # ISO8601，调用方注入；列表按此降序
  "messages":   [ {"role": "user"|"assistant", "content": str}, ... ]
}
```

- 持久化：sqlite 表 `conversations(id PRIMARY KEY, title, created_at, updated_at, messages_json)`，
  与现有 `data/cache/cache.sqlite` 物理同库不同表，或独立 `data/history.sqlite`（由 config 指定，默认后者）。
- `id` / `created_at` / `updated_at` 由 **调用方注入**，存储层不自造时间戳——保证存储层纯净、可确定性单测
  （与 workflow 脚本禁用 `Date.now()` 同理：时间是输入，不是副作用）。

## 4. T1 详细规格（HistoryStore）

### 4.1 功能需求
- **FR-T1.1** `HistoryStore(db_path)`：建表幂等（`CREATE TABLE IF NOT EXISTS`），可并发安全（沿用 `cache.py` 的 `_LOCK` 模式）。
- **FR-T1.2** `save(conv: dict)`：按 `id` upsert（`INSERT OR REPLACE`）；`messages` 序列化为 `messages_json`。
- **FR-T1.3** `get(id) -> dict | None`：取单条并反序列化 `messages`；不存在返回 `None`。
- **FR-T1.4** `list(limit=None) -> list[dict]`：按 `updated_at` **降序**返回会话**元信息**（`id/title/created_at/updated_at` + `n_messages`，**不含**完整 `messages`，避免列表页加载全部正文）；`limit` 截断。
- **FR-T1.5** `delete(id)`：删除单条；删不存在的 id 不报错（幂等）。
- **FR-T1.6** `_derive_title(messages, max_len)` 纯函数：取首条 `role=="user"` 的 `content`，去首尾空白，超 `max_len` 截断加「…」；无用户消息时回退 `"新对话"`。
- **FR-T1.7** 保留上限：`list`/存储遵守 `history.max_conversations`，由 UI 层在保存时调用 `prune(keep)` 删除最旧的超额会话（按 `updated_at` 升序删，留最近 `keep` 条）。

### 4.2 验收标准（= 测试，先写 `tests/test_history.py`，离线临时库）
- **AC-1** `_derive_title([{user,"黄芪 治疗 糖尿病"} ...], max_len=10)` ⇒ `"黄芪 治疗 糖尿病"`（≤10 不截）；
  `max_len=4` ⇒ `"黄芪 治…"`；首条非 user 时跳到首个 user；无 user ⇒ `"新对话"`。
- **AC-2** `save` 后 `get(id)` 取回的 `messages` 与写入**深度相等**（中文/特殊字符不被破坏，`ensure_ascii=False`）。
- **AC-3** `get(不存在 id)` 返回 `None`，不抛异常。
- **AC-4** 同一 `id` 二次 `save`（内容不同）后 `get` 返回**最新**值（upsert 覆盖，不产生两行）。
- **AC-5** `list()` 按 `updated_at` 降序；每项含 `n_messages` 且**不含** `messages` 键；`list(limit=2)` 只返回 2 条。
- **AC-6** `delete(id)` 后 `get` 返回 `None`、`list` 不含该条；`delete(不存在 id)` 不报错。
- **AC-7** `prune(keep=3)`：插入 5 条不同 `updated_at`，prune 后只剩 `updated_at` 最新的 3 条（最旧 2 条被删）。
- **AC-8** 持久化可复现：用同一 `db_path` 新建第二个 `HistoryStore` 实例，能读到前一实例写入的会话（证明落盘，非内存）。

### 4.3 非功能
- 离线可测：全部 T1 测试用 `tmp_path` 下临时 sqlite，零网络、零 Streamlit 依赖。
- 时间外部注入：存储层不调用 `datetime.now()`；测试传入固定 ISO 串，断言确定性。
- 容量：`list` 默认不取 `messages_json`，避免历史很长时列表页拉全文。

## 5. T2 详细规格（侧边栏 UI 接入）

### 5.1 功能需求
- **FR-T2.1** 侧边栏新增「💬 对话历史」区：调用 `store.list(limit=history.max_conversations)` 渲染会话标题按钮列表（最近在上）。
- **FR-T2.2** 点击某会话 → 载入其 `messages` 到 `st.session_state.messages`，记 `st.session_state.conv_id`，`st.rerun()` 重绘对话。
- **FR-T2.3** 「➕ 新建对话」按钮：先把当前会话（若非空）`save` 落库，再清空 `session_state` 并生成新 `conv_id`。
- **FR-T2.4** 每条会话标题旁「🗑」删除按钮：`store.delete(id)`；删的是当前会话则一并清空 `session_state`。
- **FR-T2.5** 自动保存：每轮对话产生新 assistant 回复后（现有 `st.rerun()` 前），用当前 `conv_id`/注入时间戳 `save`，并 `prune(history.max_conversations)`。
- **FR-T2.6** 现有「清空对话」改为「清空当前对话内容」语义（只清屏不删历史库），与「删除会话」区分。
- **FR-T2.7** `conv_id`/`created_at`/`updated_at` 由 UI 层生成（`uuid4`/`datetime.now().isoformat()`）后注入存储层——存储层保持纯净。
- **FR-T2.8** 侧边栏风格仿 Claude 网页版：顶部醒目「✚ 新建对话」(primary)、「最近对话」分组、当前会话用
  primary 高亮选中态（替代 🟢 emoji）；LLM 后端/示例/清空收进底部 `ℹ️` expander，列表更聚焦。
- **FR-T2.9** 每条会话的管理操作收进行尾「⋯」三点菜单（`st.popover`）：✏️ 重命名（文本框+保存）、🗑 删除对话。
- **FR-T2.10** 重命名走 `HistoryStore.set_title(id, title)`（仅改标题列，不动消息/结果，幂等），单测 `test_set_title_rename` 覆盖。

### 5.2 验收标准
- **AC-9**（E2E，`tests/e2e/`）首轮查询后刷新页面，侧边栏「对话历史」仍可见该会话标题；点击能重现对话气泡。
- **AC-10**（E2E）「新建对话」后主区对话清空，但侧边栏历史仍保留上一会话；点回上一会话可恢复其消息。
- **AC-11**（E2E）「🗑 删除」某会话后该标题从侧边栏消失，刷新后不复现（确认落库删除）。
- 说明：T2 主要靠 E2E 验证（涉及 Streamlit 运行时）；存储正确性已由 T1 单测覆盖，E2E 不重复断言库内部。

## 5b. T3 详细规格（结果快照 → 切换会话重显结果面板）

前提勘误：`PipelineResult` 全部字段为 dict/list/str/bool（见 `src/pipeline.py`），**本就 JSON 可序列化**。
故无需存大体积二进制——快照只需选取字段做 JSON 往返；图表（venn/ppi/enrichment PNG）切回会话时由
`src/viz.py` 从这些 dict **现场重渲**，不持久化 PNG。

### 5b.1 功能需求
- **FR-T3.1** `result_to_snapshot(result, excel_path=None) -> dict` 纯函数：抽取渲染所需字段
  （query/found/herb/config_snapshot/compounds/compound_targets/proteins/disease/intersection/ppi/enrichment/stats/message）
  + `excel_path`；产出 **JSON 可序列化**（`json.dumps` 不报错）。
- **FR-T3.2** `snapshot_to_result(snap) -> (PipelineResult, excel_path)` 纯函数：从快照重建 `PipelineResult`，
  与原对象字段相等（往返无损）。
- **FR-T3.3** `HistoryStore` 会话记录可携带 `results`（快照列表）：`save` 多存 `results_json`，
  `get` 多返回 `results`；旧库（无该列）自动迁移（`ALTER TABLE ADD COLUMN`），旧会话 `get` 返回 `results=[]`（向后兼容）。
- **FR-T3.4** `web/app.py`：`_save_current` 把 `session_state.results` 转快照随会话落库；
  点击历史会话时用 `snapshot_to_result` 重建 `session_state.results`，结果面板（表/图/下载）随之重现。
  Excel 路径若文件已不在 `outputs/` 则仅不显示下载按钮（不报错）。

### 5b.2 验收标准（= 测试，先写）
- **AC-12** `result_to_snapshot(r)` 含全部渲染字段且 `json.dumps(snap)` 成功（无非 JSON 值）。
- **AC-13** `snapshot_to_result(result_to_snapshot(r, "p.xlsx"))` 经 JSON 往返后重建的 `PipelineResult`
  与原 `r` **字段相等**，且 `excel_path == "p.xlsx"`。
- **AC-14** `HistoryStore`：`save` 带 `results` 的会话后 `get` 返回等价 `results`（经 sqlite 往返）；
  不带 `results` 的会话 `get` 返回 `results == []`（向后兼容）。
- **AC-15**（E2E）跑出带图表的分析 → 新建对话 → 点回该会话：结果面板与 PPI/富集图重新出现
  （证明快照重显，而非空白）。

### 5b.3 边界
- 快照存的是**生成时的数据**；不重新联网。Excel 若被清理则只少一个下载按钮。
- 仍坚持 P3：快照只来自真实跑出的 result，不编造。

## 6. 配置与变更（P5）

`config/pipeline.yaml` 新增 `history` 段：

```yaml
history:
  enabled: true
  db_path: data/history.sqlite      # 独立于 cache.sqlite
  max_conversations: 50             # 侧边栏列出 / 保留上限
  title_max_len: 24                 # 标题截断长度
```

- 上述任何阈值/路径变更须记 `CHANGELOG.md`。
- `data/history.sqlite` 属本地用户数据，**加入 `.gitignore`（`data/*.sqlite` 已被 `data/cache/` 覆盖则补一行）**，不入库（P3：不预置会话）。

## 7. SDD 执行顺序（本切片）
1. 写本 spec（已）。
2. 写 `tests/test_history.py`（AC-1…AC-8，红）。
3. 实现 `src/history.py` 使测试转绿。
4. T2：写/扩 `tests/e2e/`（AC-9…AC-11），改 `web/app.py` + `config/pipeline.yaml` + `.gitignore`。
5. 回写 `需求文档.md`（新增 FR-H1…）与 `CHANGELOG.md`（history 段口径）。

## 8. 风险与边界
- **结果面板恢复**：T1/T2 仅持久化**对话文本**，切换历史会话**不自动重显图表/结果面板**（PipelineResult 体积大、含非 JSON 字段）。重显结果留给 T3（存可序列化摘要），或由用户在恢复的会话里重新提问触发。本切片如实标注此边界，不假装已恢复结果。
- **并发写**：多标签页同时写同一 `conv_id` 以「最后写入胜」（upsert），可接受；学生单人使用场景无强一致需求。
