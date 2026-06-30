# Spec-002 网络药理学「研究闭环」扩展

状态: 进行中 · 负责人: pipeline · 关联: [[spec-001 基础管道]](../需求文档.md) · 方法: SDD（先 spec → 先验证 → 后实现 → 回写需求）

## 1. 背景与目标

现有管道（spec-001）止于「药物靶点」：药材 → 成分 → ADME 筛选 → 成分-靶点 → UniProt 蛋白表。
面向中药学学生做一篇可投稿/可结题的网络药理学研究，还缺论文后半段的核心环节。
本 spec 把工具从「半成品」补成「完整研究闭环」，并坚持 **P3 不造假**：所有数据来自真实公开 API，
离线代理/占位一律显式标注，测试用注入缓存而非伪造业务数值。

## 2. 范围（任务切分）

| 任务 | 名称 | 交付 | 数据源（免密钥优先） | 状态 |
|---|---|---|---|---|
| **T1** | 疾病靶点 + 交集 | 输入疾病名 → 疾病基因表；与药物靶点取交集（韦恩就绪结构）；新增 2 个 Excel sheet | Open Targets GraphQL（免密钥） | ✅ 本次实现 |
| T2 | 韦恩图 PNG | 由 T1 交集结构渲染高清韦恩图，网页预览 + 下载 | matplotlib-venn | 待办 |
| T3 | STRING PPI 网络 | 交集靶点 → STRING 互作；导出 Cytoscape 可读 graphml + hub（按 degree） | STRING API（免密钥） | ✅ 本次实现 |
| T4 | GO/KEGG 富集 | 交集靶点 → 富集表 + 气泡图 | Enrichr / g:Profiler（免密钥） | ✅ 本次实现 |
| T5 | 方法学 & 引用自动生成 | 输出可粘贴的中文「材料与方法」段 + 各库规范引用（版本/访问日期） | 本地模板 | ✅ 本次实现 |
| T6 | 网页可视化 | 韦恩/富集/网络在线预览 + 高清下载 | matplotlib + Streamlit | ✅ 本次实现 |

本次提交只实现 **T1**；T2–T6 列为后续切片，spec 先行声明接口与验收，便于增量。

## 3. T1 详细规格

### 3.1 功能需求
- **FR-T1.1** 入参新增可选 `disease`（疾病名，中英皆可，由数据源负责检索匹配）。`run_herb(query, disease=None)`。
- **FR-T1.2** `DiseaseClient.disease_targets(name, score_min)` 返回该疾病的人类相关基因（gene symbol）及关联分数，按 `score_min` 阈值过滤；带本地缓存（ns=`disease`），可复现。
- **FR-T1.3** 交集逻辑 `intersect_targets(drug_genes, disease_genes)` 为纯函数，返回 `intersection / drug_only / disease_only / counts`，结构可直接喂韦恩图。
- **FR-T1.4** 提供疾病时，Excel 增加 `疾病靶点` 与 `交集靶点` 两个 sheet；不提供疾病时行为与现状完全一致（向后兼容）。
- **FR-T1.5** 口径集中在 `config/pipeline.yaml` 的 `disease` 段（source / score_min / base_url / timeout），改动记 CHANGELOG。

### 3.2 验收标准（= 测试，先写）
- **AC-1** `intersect_targets({'A','B','C'}, {'B','C','D'})` ⇒ intersection `['B','C']`、drug_only `['A']`、disease_only `['D']`、counts `{drug:3,disease:3,intersection:2}`，且各列表已排序。
- **AC-2** 空集鲁棒：任一侧为空时不报错，交集为空，counts 正确。
- **AC-3** `DiseaseClient._pick_disease(search_json)` 从 Open Targets 搜索响应中取首个 EFO 命中（id+label）；无命中返回 `(None, None)`。
- **AC-4** `DiseaseClient._parse_associations(json, score_min)` 仅保留 `score >= score_min` 的靶点，输出按分数降序的 `{symbol, score}`，丢弃无 symbol 项。
- **AC-5** `DiseaseClient.disease_targets` 命中缓存时**不发起网络请求**（注入 cache，断言返回等于注入值）——证明可复现 + 离线可测。
- **AC-6** 端到端结构契约：给定 drug `gene_set` 与注入的 disease 结果，`run_herb` 产出的 result 带 `disease`、`intersection` 字段且 counts 自洽（用 monkeypatch 注入，避免真实网络/全量库依赖）。
- **AC-7** 向后兼容：`disease=None` 时 result 的 `disease`/`intersection` 为 `None`，Excel 不含新 sheet。

### 3.3 非功能
- 离线可测：所有 T1 测试不触网（缓存注入 / 纯函数 / monkeypatch）。
- 礼貌限频：真实查询每次 sleep，复用现有 `_get` 重试。
- 不造假：疾病基因必须来自 Open Targets 真实响应；无命中就如实返回 found=False，不编造。

## 5. T3 详细规格（STRING PPI 网络）

### 5.1 功能需求
- **FR-T3.1** 对靶点集合构建蛋白互作网络：有疾病交集且交集 ≥2 时用**交集靶点**，否则用全部药物靶点；<2 个基因时跳过（不报错）。
- **FR-T3.2** `StringClient.network(genes)` 返回 `{nodes, edges:[{a,b,score}], n_nodes, n_edges}`；按 `ppi.score_min`（STRING combined score，0~1）过滤；带缓存（ns=`string`），可复现。
- **FR-T3.3** `hub_genes(edges)` 纯函数：按节点度数(degree)降序返回 `[{gene, degree}]`，识别核心靶点。
- **FR-T3.4** `to_graphml(nodes, edges)` 纯函数：产出 Cytoscape 可直接打开的 GraphML（节点带 degree，边带 score）。
- **FR-T3.5** Excel 增 `PPI边表`、`Hub靶点` 两 sheet；并写出 `outputs/<药材>.graphml`。
- **FR-T3.6** 口径集中于 `config/pipeline.yaml › ppi`（enabled/base_url/species/score_min/max_nodes/timeout），改动记 CHANGELOG。

### 5.2 验收标准（= 测试，先写）
- **AC-8** `_parse_network_tsv(tsv, score_min)`：从 STRING TSV 解析 `preferredName_A/B + score`，仅留 `score>=score_min`，无向边去重（A,B 与 B,A 视为同一条）。
- **AC-9** `hub_genes(edges)`：度数统计正确、降序；孤立基因不在边表则不计。
- **AC-10** `to_graphml(nodes, edges)` 产出可被 `xml.etree` 解析，节点数/边数与输入一致，命名空间为 graphml。
- **AC-11** `StringClient.network` 命中缓存**不触网**（注入 cache + ExplodingSession）。
- **AC-12** `_attach_ppi`：注入缓存下挂载 `result.ppi`；当存在非空交集时**优先用交集靶点**；基因 <2 时 `result.ppi=None`（跳过）。
- **AC-13** 向后兼容/开关：`ppi.enabled=false` 时 `result.ppi=None`，不触网。

### 5.3 非功能
- 离线可测；真实查询礼貌限频；不造假（边来自 STRING 真实响应）。
- STRING combined score 为 0~1（network 端点），阈值默认 0.4（中等置信，对应 STRING 400）。

## 6. T4 详细规格（GO / KEGG 富集分析）

### 6.1 功能需求
- **FR-T4.1** 对靶点集合做通路/功能富集：优先用交集靶点（非空），否则全部药物靶点；<3 基因或 disabled 时跳过（富集对极小集合无意义）。
- **FR-T4.2** `EnrichrClient.enrich(genes, library)` 返回 `[{term, p_value, adj_p_value, combined_score, overlap_genes, n_overlap}]`，按 `enrichment.adj_p_max` 过滤、按 combined_score 降序、截断 `top_n`；带缓存(ns=`enrichr`)，可复现。
- **FR-T4.3** 跑多个库：默认 `GO_Biological_Process_2021` + `KEGG_2021_Human`（可配）；结果按库分组挂到 `result.enrichment`。
- **FR-T4.4** Excel 增 `GO富集`、`KEGG富集` sheet（库→sheet 映射可配）；同时写气泡图就绪的长表。
- **FR-T4.5** 口径集中于 `config/pipeline.yaml › enrichment`（enabled/base_url/libraries/adj_p_max/top_n/timeout），改动记 CHANGELOG。

### 6.2 数据源与口径
Enrichr REST：`https://maayanlab.cloud/Enrichr`。两步：① POST `addList`(genes) → `userListId`；
② GET `enrich?userListId=&backgroundType=<library>` → 每条 `[rank, term, p, z, combined, overlap_genes, adj_p, ...]`。
默认库 GO_Biological_Process_2021 / KEGG_2021_Human；`adj_p_max=0.05`(BH 校正显著)；`top_n=20`。

### 6.3 验收标准（= 测试，先写）
- **AC-14** `_parse_enrich(json, library, adj_p_max, top_n)`：解析 Enrichr enrich 响应数组，映射字段(term/p/adj_p/combined/overlap)，仅留 `adj_p<=adj_p_max`，按 combined_score 降序，截断 top_n。
- **AC-15** 过滤+排序边界：高于 adj_p 阈值的条目剔除；空响应/缺库键返回 `[]` 不报错。
- **AC-16** `EnrichrClient.enrich` 命中缓存**不触网**（注入 cache + ExplodingSession）。
- **AC-17** `_attach_enrichment`：注入缓存下挂载 `result.enrichment`（按库分组）；优先交集靶点；<3 基因或 `enabled=false` 时为 None（跳过）。

### 6.4 非功能
- 离线可测；真实查询礼貌限频；不造假（富集项来自 Enrichr 真实响应）。

## 7. T5 详细规格（方法学 & 引用自动生成）

### 7.1 功能需求
- **FR-T5.1** `build_methods(result, access_date)` 纯函数：依据 result **实际跑出的模块与口径/数量**生成中文「材料与方法」段（药材解析→成分/PubChem→ADME→靶点→UniProt→[疾病交集]→[PPI]→[富集]）。未跑的模块不写（不造假，P3）。
- **FR-T5.2** `build_references(result, access_date)` 纯函数：仅列**本次实际用到**的数据库规范引用，每条含名称、版本/年份、URL、访问日期。
- **FR-T5.3** `access_date` 由调用方注入（默认取当天），保证可复现、可测。
- **FR-T5.4** Excel 增 `方法学` sheet（两区块：方法学正文 + 参考文献列表）；CLI 同时写 `outputs/<药材>_方法学.md`。
- **FR-T5.5** 口径快照（OB/DL/预测分数/物种/各阈值）直接取自 `result.config_snapshot` 与 config，不另立新阈值（不违反 P5）。

### 7.2 数据源引用清单（固定模板，版本随 config/MANIFEST）
BATMAN-TCM 2.0、PubChem、TCMSP、UniProt、mygene.info、Open Targets(T1)、STRING(T3)、Enrichr(T4)、RDKit(代理时)。
仅当对应模块在本次 result 中产生数据时才纳入引用。

### 7.3 验收标准（= 测试，先写）
- **AC-18** `build_references` 基础集：任意成功 result 至少含 BATMAN/PubChem/UniProt；每条引用含注入的 `access_date` 字符串与一个 http(s) URL。
- **AC-19** 条件引用：result 含 disease/ppi/enrichment 时分别纳入 Open Targets/STRING/Enrichr；不含时**不出现**这些引用（不造假）。
- **AC-20** `build_methods` 含药材名、成分总数、通过 ADME 数、靶点数等真实数字；提供疾病时含交集数，未提供时**不含**"疾病/交集"字样。
- **AC-21** ADME 来源忠实：`adme_mode` 为 rdkit_proxy 时方法学注明"RDKit 代理指标"并纳入 RDKit 引用；为 tcmsp/tcmsp_live 时注明 TCMSP 且**不**纳入 RDKit。
- **AC-22** `access_date` 注入可复现：同一 result + 同一 date → 输出逐字节一致（纯函数无随机/无 now()）。

### 7.4 非功能
- 纯本地、零网络、无随机。审稿可核：数字均来自 result，口径均来自 config。

## 8. T6 详细规格（网页可视化 + 高清下载）

### 8.1 功能需求
- **FR-T6.1** `venn_png(intersection)` 纯函数：由交集结构（drug_only/disease_only/intersection 计数）渲染韦恩图 PNG（300 dpi）bytes。
- **FR-T6.2** `bubble_png(rows, title)` 纯函数：富集气泡图（x=combined_score 或 -log10(adj_p)，y=term，点大小=n_overlap），PNG bytes。
- **FR-T6.3** `network_png(nodes, edges, hubs)` 纯函数：PPI 网络图（spring 布局，hub 节点按度数放大/着色），PNG bytes，无 networkx 依赖（自实现轻量布局）。
- **FR-T6.4** 所有渲染函数：数据为空/不足时返回 `None`（不报错，不画空图）；matplotlib 用 `Agg` 后端（无显示器可跑）。
- **FR-T6.5** Streamlit 在结果面板按数据存在性增加「韦恩图 / 富集气泡图 / PPI 网络 / 方法学」标签页，每图可在线预览并提供 PNG 下载按钮。
- **FR-T6.6** 不新增任何口径/阈值（纯展示层，不触 P5）；图中数字与表一致（取自 result）。

### 8.2 验收标准（= 测试，先写）
- **AC-23** `venn_png` 对非空交集返回以 PNG magic（`\x89PNG`）开头的非空 bytes；对空交集（三区全空）返回 None。
- **AC-24** `bubble_png` 对非空富集行返回 PNG bytes；对空列表返回 None。
- **AC-25** `network_png` 对 ≥1 边返回 PNG bytes；对空边返回 None；hub 缺失不报错。
- **AC-26** 纯函数无副作用：连续两次调用均成功、不依赖网络、Agg 后端不弹窗。

### 8.3 非功能
- 离线可测（matplotlib Agg）；图 300 dpi 适合论文；中文标签用安全英文/基因符号避免字体缺失（term/基因均为英文，无需中文字体）。

## 9. E2E 浏览器测试（Playwright）

真实启动 Streamlit（直接模式，无 LLM 密钥，输入即药材名）→ Playwright/Chromium 模拟用户操作，
验证整条管道在浏览器端的端到端呈现。坐实「一站式网页」需求，非 mock。

### 9.1 验收标准（= 测试）
- **E2E-1** 页面加载：标题「中药网络药理学一站式助手」可见，侧栏显示「直接模式」，输入框就绪。
- **E2E-2** 输入「肉桂」提交 → 结果面板出现，4 个指标卡（成分总数/通过 ADME/去重靶点/UniProt 命中）可见。
- **E2E-3** 标签页含 成分表/成分-靶点/靶点蛋白 + PPI 网络 + 富集气泡图；直接模式无疾病，故**不出现**韦恩图。
- **E2E-4** 点开 PPI 网络 / 富集气泡图标签 → 渲染出 `<img>`（300dpi 图）。
- **E2E-5** 下载按钮（完整 Excel + PNG）存在。
- **E2E-6**（负向）输入不存在的药材 → 友好「未在 BATMAN-TCM 中找到」告警框，不崩溃。

### 9.2 工程注记
- `tests/e2e/conftest.py`：session 级夹具起 Streamlit（端口 8599，过滤掉 LLM 密钥 → 直接模式），
  健康检查与浏览器均**禁用 macOS 系统代理**（urllib `ProxyHandler({})`、chromium `--no-proxy-server`），
  否则系统代理拦截 127.0.0.1 导致连接失败。
- `pytest.ini` 默认 `--ignore=tests/e2e`，快速单测不受影响；端到端用 `pytest tests/e2e` 显式运行。
- 现状：`pytest`（单元）29 passed；`pytest tests/e2e` 3 passed（缓存预热后 ~12s）。

## 10. 实景图表测试发现的问题与修复（Playwright MCP + LLM 模式）

用 DeepSeek LLM 模式 + Playwright 真浏览器跑「肉桂治疗高血压」并**目检三类图表**，发现仅靠
「存在 `<img>`」的断言无法暴露的真问题，已修复并补单测：

| 发现 | 根因 | 修复 | 测试 |
|---|---|---|---|
| 中文「高血压」疾病未命中 | Open Targets 检索对中文支持差 | `_DISEASE_ALIASES` 中→英别名 + `_search_terms` 回退 | `test_search_terms_cn_alias` |
| 修复后仍读到旧 found=False | 负结果被永久缓存 | 仅缓存命中结果（不缓存未命中） | （行为变更，缓存命中测试不受影响） |
| 韦恩图退化成单圈 | 疾病侧为空仍渲染 | `venn_png` 疾病侧空→None；网页仅 `disease.found` 显示该标签 | `test_venn_png_and_empty` 扩展 |
| PPI 187 节点标签糊 | 渲染未限制节点数 | `network_png(max_nodes=60)` 取度数 top-N，余数在 Excel/GraphML | `test_network_png_caps_large_graph` |

修复后实景复测（截图存档）：韦恩 736/36/90、PPI 聚焦 36 交集靶点且标签可读、KEGG 富集转为
高血压特异通路（血管平滑肌收缩 / 醛固酮分泌 / 心肌收缩）。教训：**图表类需求必须真浏览器目检**，
断言「图存在」远不够，要核对图的**语义正确性**（节点可读、交集非退化、通路与疾病相关）。

## 4. 数据源说明
Open Targets Platform GraphQL：`https://api.platform.opentargets.org/api/v4/graphql`，免密钥。
两步：① `search(queryString, entityNames:["disease"])` → EFO id；② `disease(efoId){associatedTargets}` → `target.approvedSymbol` + `score`。
分数为 0–1 关联强度，默认阈值 0.1（可调）。
