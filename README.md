# 中药网络药理学一站式工具

输入任意中药名（中文 / 拼音 / 拉丁学名，支持批量）→ 自动跑通
**药材 → 成分 → ADME 筛选 → 靶点 → 基因/蛋白归一化** → 导出多 sheet Excel，
并提供对话式网页前端。

## 数据来源（真实，无 mock）

| 环节 | 来源 | 接入 |
|---|---|---|
| 药材 → 成分（含 PubChem CID） | **BATMAN-TCM 2.0**（8404 味全库 dump） | 本地 `data/raw/batman/` |
| 成分 → 已知/预测靶点 | BATMAN-TCM 2.0 known + predicted TTI | 本地 dump |
| 成分 → SMILES / InChIKey / 名称 | **PubChem** PUG-REST | 在线 + 缓存 |
| 预测靶点 Entrez ID → 基因符号 | **mygene.info**（限人类） | 在线 + 缓存 |
| 靶点 → UniProt 蛋白信息表 | **UniProt** REST（Swiss-Prot 优先，物种 9606） | 在线 + 缓存 |
| ADME（OB/DL）筛选 | TCMSP：①静态表 `data/raw/tcmsp/` ②`tcmsp_live` 实时抓取；缺失时 RDKit 代理 | 见下 |
| 疾病靶点 + 药物×疾病交集（T1） | **Open Targets** Platform GraphQL（免密钥） | 在线 + 缓存 |
| PPI 蛋白互作网络 + hub 核心靶点（T3） | **STRING** API（免密钥） | 在线 + 缓存 |
| GO / KEGG 通路富集分析（T4） | **Enrichr**（免密钥） | 在线 + 缓存 |

## 安装

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt    # 或 requirements.lock 复现锁定版本
```

BATMAN dump 已下载到 `data/raw/batman/`（见该目录 `MANIFEST`）。重新获取见 `data/raw/batman/MANIFEST` 中的 `source_base`。

## 用法

### 命令行
```bash
.venv/bin/python -m src.run_cli 肉桂                 # 单味
.venv/bin/python -m src.run_cli 黄芪 当归 "Cinnamomum cassia"   # 批量
.venv/bin/python -m src.run_cli 肉桂 --disease 高血压            # 叠加疾病靶点 + 交集(T1)
# 产出 outputs/<拼音>.xlsx
```

### 对话式网页
```bash
export ANTHROPIC_API_KEY=sk-...        # 可选; 不配则进入「直接模式」(输入即药材名)
.venv/bin/streamlit run web/app.py
```
网页里输入药材名 → agent（Claude `claude-opus-4-8` 工具调用）自动跑管道 → 展示
成分表 / 成分-靶点 / 靶点蛋白 三张表并提供 Excel 下载。
若分析涉及疾病/PPI/富集，结果面板按数据存在性自动出现 **韦恩图 / PPI 网络 / 富集气泡图**
标签页，可在线预览并下载 300dpi PNG（论文配图就绪）。

## 测试

```bash
.venv/bin/python -m pytest                    # 单元测试(快, 离线/注入缓存) — 29 passed
# 端到端浏览器测试(Playwright, 起真实 Streamlit 直接模式, 模拟用户操作):
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m playwright install chromium
.venv/bin/python -m pytest tests/e2e          # 输入药材→指标/可视化标签/图像/下载 端到端校验
```
说明：E2E 用「直接模式」(不配 LLM 密钥, 输入即药材名), 跑真实管道(缓存预热后秒级)；
默认 `pytest` 已 `--ignore=tests/e2e`, 互不影响。

## 口径（集中在 `config/pipeline.yaml`，改动记 `CHANGELOG.md`）

- 物种限定人类（9606）
- ADME：OB ≥ 30%、DL ≥ 0.18（TCMSP 口径）。三种来源：
  - `mode: tcmsp_live`：实时抓取 tcmsp-e.com 该药材的真实 OB/DL（仅查询药材，低频礼貌），
    经 PubChem 解析 InChIKey 与 BATMAN 成分连接
  - `mode: tcmsp`：读 `data/raw/tcmsp/` 静态表
  - 缺失/未命中：RDKit QED/Lipinski 代理，标注 `adme_source=rdkit_proxy`，**不冒充** TCMSP 数值
  - 注：肉桂全库最大 DL≈0.15，严格阈值下几乎全不通过（真实数据），按需放宽 `dl_min`
- 预测靶点分数阈值 ≥ 0.4
- 成分主键 InChIKey / PubChem CID；靶点主键 HGNC gene symbol

## Excel 输出（sheets）

`概览` · `成分表`(CID/名称/SMILES/InChIKey/ADME) · `成分-靶点`(证据等级/分数/来源) ·
`靶点蛋白`(UniProt accession/蛋白名/长度/功能/序列) · `成分x靶点矩阵`(0/1)。
提供 `--disease` 时额外：`疾病靶点`(symbol/score) · `交集靶点`(intersection/drug_only/disease_only)。
有 PPI 网络时额外：`Hub靶点`(gene/degree) · `PPI边表`(a/b/score)，并写出同名 `.graphml`(Cytoscape 可直接打开)。
有富集结果时额外：`GO富集` · `KEGG富集`(term/p/adj_p/combined_score/n_overlap/overlap_genes)。
始终包含：`方法学`(自动生成的中文「材料与方法」草稿 + 规范引用)，并另写出 `<同名>_方法学.md`。

## 黄金标准校验（肉桂）

肉桂醛 InChIKey = `KJPRLNWUNMBNBZ-QPJJXVBHSA-N`（与权威值一致），已知靶点含
TRPA1 / PTGS2 / NFKBIA / RELA 等经典靶点；TRPA1 → UniProt `O75762`。

## 服务器部署

1. **拉代码 + 建环境 + 取数据**：
   ```bash
   git clone https://github.com/zedpa/medicine.git /opt/tcm-netpharm
   cd /opt/tcm-netpharm
   python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
   bash scripts/fetch_batman.sh         # 下载 BATMAN-TCM 2.0 dump(~23MB)
   ```
2. **配密钥**：`cp .env.example .env` 并填 `DEEPSEEK_API_KEY=...`（`.env` 已被 gitignore，不要提交）。
3. **启动**（对外可访问，读 `.env`）：
   ```bash
   bash deploy/run.sh            # 前台
   ```
   生产用 **systemd** 常驻：把 `deploy/tcm-netpharm.service` 里的 `User`/`WorkingDirectory` 改成实际值，然后
   ```bash
   sudo cp deploy/tcm-netpharm.service /etc/systemd/system/
   sudo systemctl daemon-reload && sudo systemctl enable --now tcm-netpharm
   sudo systemctl status tcm-netpharm
   ```

### 反向代理 + 访问控制（强烈建议）
Streamlit 自身**无鉴权**，且绑定 `0.0.0.0` 后任何能访问该端口的人都能触发分析、消耗 DeepSeek 额度。
生产务必加一层。Nginx + Basic Auth 示例：
```nginx
server {
    listen 80;
    server_name your.domain;
    auth_basic "restricted";
    auth_basic_user_file /etc/nginx/.htpasswd;   # htpasswd -c 生成
    location / {
        proxy_pass http://127.0.0.1:8501;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;   # WebSocket(Streamlit 必需)
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
    }
}
```
并在安全组/防火墙上**只放行 80/443，不直接暴露 8501**。

### LLM 后端切换
环境变量决定后端（见 `.env.example`）：`DEEPSEEK_API_KEY` → DeepSeek；`OPENAI_API_KEY` → OpenAI 兼容；
`ANTHROPIC_API_KEY` → Claude；都不配 → 直接模式（输入即药材名，仍可用）。

## 目录

```
config/pipeline.yaml   口径声明
data/raw/batman/       BATMAN-TCM 2.0 dump + MANIFEST
data/cache/            PubChem/UniProt/mygene 本地缓存
src/                   batman / online / adme / pipeline / excel_export
agent/agent.py         Claude 工具调用 agent
web/app.py             Streamlit 对话式前端
outputs/               导出的 Excel
```
