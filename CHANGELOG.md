# 变更日志（口径 / 阈值）

记录所有归一化口径、阈值、物种、去重规则的变更（见 `config/pipeline.yaml`）。

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
