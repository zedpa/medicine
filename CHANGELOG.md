# 变更日志（口径 / 阈值）

记录所有归一化口径、阈值、物种、去重规则的变更（见 `config/pipeline.yaml`）。

## 2026-06-30 · 前端 UI 重设计（spec-006）
- 依据 Anthropic frontend-design skill 两遍式设计法，让主题（中药 × 网络药理学）
  驱动美学：「本草典籍 × 分子网络」。
- 设计 token（`.streamlit/config.toml` + `web/app.py` 注入 CSS）：松绿 `#1f6b4f`(主色)、
  矿物冷白 `#FAFBF8`(背景)、苔绿 `#EBF0EA`(卡片/侧栏)、松墨 `#1b2a23`(正文)、
  朱砂 `#B23A2E`(招牌色)；字族 思源宋体(标题)+Inter(正文)+Space Mono(计量)。
- 招牌：朱砂印章「本」+ 宋体题名 + 节点母题(成分→靶点→蛋白→网络, 末节点朱砂)；
  指标卡片化、按钮/表单/数据表圆角、选项卡选中转松绿。
- 质量底线：键盘焦点可见、`prefers-reduced-motion` 关动效。
- 纯视觉改动：保留全部 E2E 依赖的文案/控件名；66 单测 + 13 E2E 重设计后仍全绿。

## 2026-06-30 · 账号管理后台 + 统计看板（spec-005）
- 新增 `config/pipeline.yaml › admin`：`herb_top_n`(看板热门药材 Top N)、
  `activity_days`(活跃趋势回看天数)。
- 新增统计聚合层 `src/stats.py`（纯函数 `overview/per_user/herb_popularity/
  activity_by_day`，「今天」由调用方注入 → 确定性可测；热门药材基于**真实跑出的
  结果快照**，名称优先级 chinese>latin>query，仅计 found=True 为成功命中）。
- store 支撑：`UserStore.set_role`；`HistoryStore.list_all/export_all`（跨 owner，仅 admin 调用）。
- web 管理后台（仅 `role==admin` 可见可达）：统计看板（4 指标 + 热门药材条形图 +
  近 N 天活跃折线 + 各用户活跃度表）；账号管理（新建/改角色/重置密码/删除用户）。
- 安全护栏：**不可删除自己**、**不可删除或降级最后一个 admin**（系统至少留 1 admin）；
  新建/重置密码走 stauth 口令策略 + bcrypt 哈希。
- 测试：T1 stats 9 单测（含 set_role/export_all）；T2 E2E 角色门 + 看板 + 增删改用户 +
  末位 admin 保护 4 用例。口径仅在 config，记此。

## 2026-06-30 · 账号授权与多租户（spec-004）
- 引入 `streamlit-authenticator`（v0.4.2，bcrypt + Cookie/JWT 会话）做登录/注册/登出，
  调研后取自包含方案而非外部 OIDC/IdP（自托管、无企业 IdP，最契合）。
- 新增 `config/pipeline.yaml › auth`：`enabled / db_path / cookie_name /
  cookie_expiry_days / allow_self_register / default_role`。
- 新增账号存储层 `src/auth.py`（`UserStore`，sqlite，密码**只存 bcrypt 哈希**，
  哈希与时间由调用方注入 → 纯净可单测）；账号库 `data/auth.sqlite`，独立于历史/缓存库。
- 多租户：`conversations` 表加 `owner` 列，`HistoryStore` 全部读写按 `owner` scope
  （`get/list/set_title/delete/prune` 均带 owner），跨用户不可见/不可改/不可删。
  旧库 `ALTER TABLE ADD COLUMN owner`；旧行 owner=NULL 默认不归属，
  可经 env `HISTORY_LEGACY_OWNER` 一次性认领。
- 密钥口径：`AUTH_COOKIE_KEY` / `ADMIN_USER` / `ADMIN_PASSWORD` 仅来自环境变量，
  绝不入库；首启账号库为空且配了 admin 凭据则种入一个 admin（role=admin）。
- 测试：T1 账号层 8 单测、T2 历史隔离 5 新增单测（history 共 17）、T3 E2E
  登录门 + 跨用户隔离 + 重登归属 2 用例。口径变更仅在 config，记此。

## 2026-06-25 · 初始口径冻结
- 物种：Homo sapiens / 9606
- ADME：OB ≥ 30%，DL ≥ 0.18；无 TCMSP 时用 RDKit 代理（QED ≥ 0.30，Lipinski 违反 ≤ 1），
  标注 `adme_source=rdkit_proxy`
- 预测靶点（BATMAN）分数阈值 ≥ 0.5
- 成分主键 InChIKey / PubChem CID；靶点主键 HGNC gene symbol；UniProt 优先 Swiss-Prot
- 去重：(成分 CID, 基因) 去重，已知证据优先于预测，分数取最大

## 2026-06-25 · 阈值调整
- `targets.predicted_score_min` 0.5 → **0.4**（用户要求，纳入更多预测靶点）

## 2026-06-25 · 启用 tcmsp_live + 放宽 DL
- `adme.mode` auto → **tcmsp_live**（默认用实时 TCMSP OB/DL）
- `adme.dl_min` 0.18 → **0.1**（肉桂等小分子药材，最大 DL≈0.15，严格阈值会筛到 0）

## 2026-06-25 · 新增 TCMSP 实时抓取 (tcmsp_live)
- 新增 `src/tcmsp.py`：模拟人工浏览 tcmsp-e.com（token + 按药材查询 + 解析成分网格），
  仅抓查询药材，取真实 OB/DL。参考开源项目 shujuecn/TCMSP-Spider。
- `adme.mode: tcmsp_live`：实时抓 TCMSP OB/DL，经 PubChem 把分子名解析为 InChIKey，
  与 BATMAN 成分按 InChIKey 连接做 OB≥30 & DL≥0.18 筛选；未命中回退 RDKit 代理。
- 验证：肉桂 TCMSP 99 分子→77 解析 InChIKey；肉桂醛真实 OB=32.0/DL=0.023。
  注：肉桂全库最大 DL=0.154<0.18，严格阈值下 0 通过（真实数据，非 bug）。

## 2026-06-30 · 侧边栏改 Claude 网页版风格 + 管理收进「⋯」三点菜单
- `web/app.py` 侧边栏重构(仿 Claude)：顶部醒目「✚ 新建对话」(primary)、「最近对话」分组列表、
  当前会话用 primary 高亮选中态(替代 🟢 emoji)；LLM 后端/示例/清空收进底部 `ℹ️` expander，列表更聚焦。
- 每条会话右侧「⋯」三点菜单(`st.popover`)：内含 ✏️ 重命名(文本框+保存) / 🗑 删除对话。
- 新增 `HistoryStore.set_title(id, title)`(仅改标题列, 不动消息, 幂等)，配套 `test_set_title_rename`。
- E2E 适配：删除改为先开「⋯」popover 再点删除(`stPopoverBody` 作用域)、「新建对话」按钮文案匹配更新。
- 纯 UI/交互改进，无口径变更。验证：单测 **44 passed**；E2E **7 passed**；实景目检三点菜单+重命名+删除均通过。

## 2026-06-30 · PPI 图改环形布局 + 对话历史实景走查 (Playwright MCP)
- 实景走查对话历史(LLM 模式「分析肉桂治疗高血压」)：新建对话→历史保留、点回会话→结果面板+图表
  经快照重显、跨服务重启历史仍在，全部通过。
- 实景目检发现 PPI 力导向布局对「密集核心+悬挂节点」会塌成重叠团且贴边被裁 → `src/viz.py`
  `network_png` 改**按度数排序的环形布局**：节点均布圆周零重叠、标签置圈外按角度对齐、加 degree 色条。
  纯渲染改进，无口径/阈值变更；`test_viz.py` 5 passed、全套 43 + E2E 7 无回归。

## 2026-06-30 · 结果快照: 切换历史会话重显结果面板 (spec-003 T3) — 历史 T1–T3 全部完成
- 新增 `src/pipeline.py › result_to_snapshot/snapshot_to_result` 纯函数：PipelineResult 全字段本就
  JSON 可序列化 → 快照只做字段选取 + JSON 往返；图表(venn/ppi/enrichment)切回会话时由 viz 从 dict
  现场重渲，不持久化 PNG。
- `src/history.py`：会话记录增 `results`(快照列表) → `results_json` 列；旧库自动迁移
  (`ALTER TABLE ADD COLUMN`)，旧会话 `get` 返回 `results=[]`(向后兼容)。
- `web/app.py`：`_save_current` 把 `session_state.results` 转快照随会话落库；点击历史会话用
  `snapshot_to_result` 重建结果，表/图/下载面板随之重现。Excel 若已不在 outputs/ 则仅少一个下载按钮。
- SDD 红-绿：新增 `tests/test_snapshot.py` 4 条(JSON 可序列化 / dataclass 往返相等 / 历史携带快照 /
  无快照向后兼容)；E2E 增 AC-15(跑出图表→新建→点回该会话→PPI 图重现)。
- 验证：单测 **43 passed**；E2E **7 passed**。spec-003(侧边栏对话历史)T1–T3 收口。

## 2026-06-30 · 侧边栏对话历史 UI 接入 (spec-003 T2) — 历史 T1+T2 完成
- `web/app.py`：侧边栏增「💬 对话历史」区(最近在上)：➕ 新建对话 / 点击切换载入 / 🗑 删除；
  每轮回复后自动落库当前会话(`_save_current` + `prune`)；「清空对话」改为「清空当前对话内容」
  (仅清屏不删历史库)。`conv_id`/时间戳由 UI 层(uuid4/datetime)生成后注入存储层(存储层保持纯净)。
  store 用 `@st.cache_resource` 复用连接；db_path 可被 `HISTORY_DB_PATH` 覆盖(供 E2E 隔离)。
- `tests/e2e/`：新增 `test_e2e_history.py`(AC-9 刷新后历史仍在并可点击重现 / AC-10 新建保留旧会话可恢复 /
  AC-11 删除从侧栏消失且刷新不复现)；conftest 把历史库指向临时文件并清空，不污染真实数据。
- 边界(如实声明)：切换历史会话只重现**对话文本**，**不重显图表/结果面板**(留给 T3)。
- 纯展示/持久化接入，无业务口径变更。验证：单测 39 passed；E2E 6 passed(原 3 + 历史 3)。

## 2026-06-30 · 新增 对话历史存储层 (spec-003 T1)
- 新增 `history` 段：`enabled=true`、`db_path=data/history.sqlite`(独立于 cache.sqlite)、
  `max_conversations=50`(侧边栏列出 / prune 保留上限)、`title_max_len=24`(标题截断)。
- 新增 `src/history.py`：`HistoryStore`(sqlite 持久化会话 save/get/list/delete/prune) +
  `_derive_title` 纯函数。时间戳/id 由调用方注入(存储层不调 datetime.now()/uuid)→ 确定性可单测；
  `list()` 只返回元信息(含 n_messages, 不含 messages 正文)避免历史长时拉全文。
- `.gitignore` 增 `data/*.sqlite`(本地用户数据, 不预置会话, P3)。
- 无业务口径/阈值变更(纯持久化层)，仅新增存储位置/容量配置。
- SDD 红-绿：`tests/test_history.py` 8 条(标题截断/中文不坏/upsert 覆盖/降序+limit/幂等删/
  prune 留最新 N/二次实例读落盘)全绿；全套 39 passed 无回归。T2 侧边栏 UI 接入为后续切片。

## 2026-06-30 · Playwright 实景测试发现并修复 3 个图表问题 (spec-002 §10)
- 用 LLM(DeepSeek)模式 + Playwright MCP 真浏览器跑「肉桂治疗高血压」, 目检三类图表, 暴露:
  1. **中文病名未命中**: Open Targets 检索「高血压」失败 → 加 中->英 病名别名表(`_DISEASE_ALIASES`)
     + `_search_terms` 回退; 「高血压」→hypertension→78 靶点, 交集 36 个。
  2. **负缓存粘连**: 旧的 found=False 被永久缓存, 修复后仍读到旧值 → 改为**不缓存未命中**(仅缓存命中)。
  3. **韦恩图退化**: 疾病未命中时画 772/0/0 单圈无意义 → `venn_png` 疾病侧为空返回 None,
     且网页仅在 `disease.found` 时显示韦恩图标签。
  4. **PPI 节点糊成团**: 187 节点标签重叠 → `network_png(max_nodes=60)` 只渲染度数最高的 N 个
     (完整网络仍在 Excel/GraphML), 标题注明截断数。
- 修复后实景复测: 韦恩图 736/36/90、PPI 聚焦 36 交集靶点(EDNRA/ADRA2B/GUCY1B1/PDE3A 等可读)、
  KEGG 富集变为高血压特异(血管平滑肌收缩/醛固酮分泌/心肌收缩)。单测 31 passed。

## 2026-06-30 · 新增 Playwright 端到端浏览器测试 (spec-002 §9)
- 新增 `tests/e2e/`(conftest 起真实 Streamlit 直接模式 + Playwright/Chromium 驱动)、`pytest.ini`
  (默认 `--ignore=tests/e2e`, 快测不变)。
- 6 条 E2E 断言: 页面加载/4 指标卡/标签页(PPI+富集, 直接模式无韦恩图)/图像渲染/下载按钮/未知药材告警。
- 关键修复: 禁用 macOS 系统代理(urllib ProxyHandler({}) + chromium --no-proxy-server), 否则拦 127.0.0.1。
- 依赖新增 playwright + pytest-playwright(测试用, 见 requirements-dev.txt)。验证: 单测 29 passed; e2e 3 passed。

## 2026-06-30 · 新增 网页可视化 (spec-002 T6) — 研究闭环 T1–T6 全部完成
- 新增 `src/viz.py`：`venn_png`/`bubble_png`/`network_png`(纯函数→300dpi PNG bytes, Agg 后端, 离线可测)。
  PPI 自实现轻量 Fruchterman-Reingold 布局(确定性, 无 networkx 依赖)。
- `web/app.py`：结果面板按数据存在性动态增「韦恩图/PPI 网络/富集气泡图」标签页, 在线预览 + PNG 下载。
- 依赖新增 matplotlib + matplotlib-venn(已加入 requirements.txt)。
- 纯展示层, 无新口径/阈值, 不触 P5。
- SDD 红-绿：`tests/` 全绿(29 passed)；三图渲染目检通过(韦恩 3/2/4、气泡着色、PPI hub 加粗)。

## 2026-06-30 · 新增 方法学&引用自动生成 (spec-002 T5)
- 新增 `src/methods.py`：`build_methods`/`build_references`/`methods_and_refs`(纯本地, 零网络, 可复现)。
  按 result 实际跑出的模块与真实数字/口径生成中文「材料与方法」；仅引用实际用到的库。
- `excel_export.export(result, out_path, access_date=None)`：增 `方法学` sheet，另写 `_方法学.md`。
  ADME 为 rdkit_proxy 时方法学注明「RDKit 代理」并引 RDKit；tcmsp/live 时注明 TCMSP 不引 RDKit(不造假)。
- 无新口径/阈值(数字取自 result、口径取自 config_snapshot)，不触 P5。
- SDD 红-绿：`tests/` 全绿(25 passed)；E2E 导出 11 sheet + _方法学.md + .graphml。

## 2026-06-30 · 新增 GO/KEGG 富集分析 (spec-002 T4)
- 新增 `enrichment` 段：数据源 Enrichr（免密钥），`enabled=true`、
  `libraries=[GO_Biological_Process_2021, KEGG_2021_Human]`、`adj_p_max=0.05`(BH 校正)、
  `top_n=20`、`timeout=30`。
- 新增 `src/enrichment.py`：`EnrichrClient`(addList→enrich, 解析/过滤/排序, 带缓存)。
- 靶点优先用 药物×疾病 交集，否则全部药物靶点；<3 基因跳过。Excel 增 `GO富集`/`KEGG富集`。
- 重构：`pipeline._pick_genes` 抽出「交集优先」选取逻辑(T3/T4 共用)。
- SDD 红-绿：`tests/` 全绿(20 passed)；真实 API 冒烟 10 个高血压基因→KEGG「Renin-angiotensin
  system」、GO「systemic arterial blood pressure 调控」(adj_p<1e-7)。

## 2026-06-26 · 新增 PPI 蛋白互作网络 (spec-002 T3)
- 新增 `ppi` 段：数据源 STRING（免密钥），`ppi.enabled=true`、`ppi.score_min=0.4`(combined 0~1)、
  `ppi.max_nodes=200`、`ppi.species=9606`、`ppi.timeout=30`。
- 新增 `src/ppi.py`：`StringClient.network`(带缓存)、`hub_genes`(度数→核心靶点)、`to_graphml`(Cytoscape)。
- 靶点优先用 药物×疾病 交集，否则全部药物靶点；<2 基因跳过。Excel 增 `Hub靶点`/`PPI边表`，
  并写 `outputs/<药材>.graphml`。
- SDD 红-绿：`tests/` 全绿(14 passed)；真实 API 冒烟 8 个高血压基因→STRING 22 边，hub AGT/ACE/AGTR1。

## 2026-06-26 · 新增疾病靶点 + 交集 (spec-002 T1)
- 新增 `disease` 段：数据源 Open Targets GraphQL（免密钥），`disease.score_min=0.1`、
  `disease.max_targets=3000`、`disease.timeout=30`。
- 新增 `src/disease.py`（疾病名→人类基因+关联分数，带缓存）、`src/intersect.py`（药物×疾病交集纯函数）。
- `run_herb`/`analyze_herbs`/CLI 新增可选 `disease`；提供时 Excel 增 `疾病靶点`、`交集靶点` sheet。
- 向后兼容：`disease=None` 时行为不变。SDD 红-绿：`tests/` 全绿(7 passed)；
  真实 API 冒烟 hypertension→AGTR1/ACE/REN(高血压病理一致)。

## 2026-06-25 · 修复
- 修复 BATMAN `predicted_browse_by_ingredients` 解析：该文件为**空格分隔**（known 为 TAB），
  原 TAB 切分导致预测靶点全部丢失。改为按首 token(CID)/末 token(靶点串)解析。
