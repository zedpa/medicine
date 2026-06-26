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

## 2026-06-25 · 修复
- 修复 BATMAN `predicted_browse_by_ingredients` 解析：该文件为**空格分隔**（known 为 TAB），
  原 TAB 切分导致预测靶点全部丢失。改为按首 token(CID)/末 token(靶点串)解析。
