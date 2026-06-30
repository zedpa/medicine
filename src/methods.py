"""方法学 & 引用自动生成（T5）：纯本地、零网络、可复现。

依据 result 实际跑出的模块与真实数字/口径，生成可粘贴的中文「材料与方法」段，
以及仅含本次实际用到的数据库的规范引用（含版本/年份/URL/访问日期）。

不造假（P3）：未跑的模块不写、未用的库不引；所有数字取自 result，口径取自 config_snapshot。
"""
from __future__ import annotations

from typing import Optional

# 固定引用模板：(key, name, 版本/年份, url, 引文)
_REF_TABLE = {
    "batman": ("BATMAN-TCM 2.0",
               "Kong et al., Nucleic Acids Res, 2024",
               "http://bionet.ncpsb.org.cn/batman-tcm/",
               "Kong X, et al. BATMAN-TCM 2.0: an enhanced platform for target prediction and "
               "functional analysis of traditional Chinese medicine. Nucleic Acids Res. 2024."),
    "pubchem": ("PubChem",
                "Kim et al., Nucleic Acids Res, 2023",
                "https://pubchem.ncbi.nlm.nih.gov/",
                "Kim S, et al. PubChem 2023 update. Nucleic Acids Res. 2023;51(D1):D1373-D1380."),
    "tcmsp": ("TCMSP",
              "Ru et al., J Cheminform, 2014",
              "https://www.tcmsp-e.com/",
              "Ru J, et al. TCMSP: a database of systems pharmacology for drug discovery from "
              "herbal medicines. J Cheminform. 2014;6:13."),
    "rdkit": ("RDKit",
              "RDKit: Open-source cheminformatics",
              "https://www.rdkit.org/",
              "RDKit: Open-source cheminformatics. https://www.rdkit.org."),
    "mygene": ("mygene.info",
               "Wu et al., Genome Biol, 2016",
               "https://mygene.info/",
               "Wu C, et al. BioGPS and MyGene.info. Genome Biol. 2016;17:91."),
    "uniprot": ("UniProt",
                "UniProt Consortium, Nucleic Acids Res, 2023",
                "https://www.uniprot.org/",
                "The UniProt Consortium. UniProt: the Universal Protein Knowledgebase in 2023. "
                "Nucleic Acids Res. 2023;51(D1):D523-D531."),
    "opentargets": ("Open Targets Platform",
                    "Ochoa et al., Nucleic Acids Res, 2023",
                    "https://platform.opentargets.org/",
                    "Ochoa D, et al. The next-generation Open Targets Platform. "
                    "Nucleic Acids Res. 2023;51(D1):D1353-D1359."),
    "string": ("STRING",
               "Szklarczyk et al., Nucleic Acids Res, 2023",
               "https://string-db.org/",
               "Szklarczyk D, et al. The STRING database in 2023. "
               "Nucleic Acids Res. 2023;51(D1):D638-D646."),
    "enrichr": ("Enrichr",
                "Xie et al., Curr Protoc, 2021",
                "https://maayanlab.cloud/Enrichr/",
                "Xie Z, et al. Gene set knowledge discovery with Enrichr. "
                "Curr Protoc. 2021;1:e90."),
}


def _adme_is_proxy(snap: dict) -> bool:
    return "rdkit" in str(snap.get("adme_mode", "")).lower()


def _used_refs(result) -> list:
    """本次实际用到的库 key 列表(有序)。"""
    snap = result.config_snapshot or {}
    keys = ["batman", "pubchem"]
    if _adme_is_proxy(snap):
        keys.append("rdkit")
    else:
        keys.append("tcmsp")
    keys += ["mygene", "uniprot"]
    if getattr(result, "intersection", None) is not None:
        keys.append("opentargets")
    if getattr(result, "ppi", None) is not None:
        keys.append("string")
    if getattr(result, "enrichment", None) is not None:
        keys.append("enrichr")
    return keys


def build_references(result, access_date: str) -> list:
    """仅列本次实际用到的数据库引用。每条 {name, version, url, access_date, citation}。"""
    out = []
    for k in _used_refs(result):
        name, version, url, citation = _REF_TABLE[k]
        out.append({"name": name, "version": version, "url": url,
                    "access_date": access_date, "citation": citation})
    return out


def build_methods(result, access_date: str) -> str:
    """生成中文「材料与方法」段(markdown)。所有数字取自 result, 口径取自 config_snapshot。"""
    herb = result.herb or {}
    snap = result.config_snapshot or {}
    stats = result.stats or {}
    name = herb.get("chinese") or herb.get("latin") or result.query
    latin = herb.get("latin", "")
    n_total = stats.get("ingredients_total", len(result.compounds))
    n_pass = stats.get("compounds_passed_adme",
                       sum(1 for c in result.compounds if c.get("adme_passed")))
    n_targets = stats.get("unique_targets", 0)
    n_uniprot = stats.get("targets_with_uniprot", 0)
    ob, dl = snap.get("ob_min"), snap.get("dl_min")
    score_min = snap.get("predicted_score_min")
    taxon = snap.get("taxon_id")

    if _adme_is_proxy(snap):
        adme_sent = (f"由于缺少 TCMSP 实测 ADME 值，采用 RDKit 计算的成药性代理指标"
                     f"（QED 与 Lipinski 规则）进行筛选，并在结果中显式标注 adme_source=rdkit_proxy，"
                     f"不等同于 TCMSP 的口服生物利用度（OB）/类药性（DL）。")
    else:
        adme_sent = (f"以 TCMSP 数据库的口服生物利用度（OB ≥ {ob}%）与类药性"
                     f"（DL ≥ {dl}）为标准进行活性成分筛选。")

    L = []
    L.append("## 材料与方法（自动生成草稿，请人工核对后使用）\n")
    L.append("### 活性成分的获取与筛选")
    L.append(
        f"以 {name}（{latin}）为研究对象，自 BATMAN-TCM 2.0 数据库检索其全部化学成分，"
        f"共获得成分 {n_total} 个。各成分经 PubChem 解析标准化学结构（SMILES、InChIKey）。"
        f"{adme_sent}经筛选，最终纳入 {n_pass} 个活性成分用于后续靶点分析。\n")

    L.append("### 成分靶点的预测与归一化")
    L.append(
        f"活性成分的作用靶点来自 BATMAN-TCM 2.0 的已知（known）与预测（predicted）"
        f"靶点-相互作用数据（预测靶点保留打分 ≥ {score_min} 的条目）。"
        f"预测靶点的 Entrez 基因 ID 经 mygene.info 映射为标准 HGNC 基因符号"
        f"（限定人类，taxon {taxon}）。靶点对应蛋白信息（UniProt 登录号、蛋白名、序列、功能注释）"
        f"自 UniProt 数据库获取（优先 Swiss-Prot 审阅条目）。"
        f"共得到去重靶点 {n_targets} 个，其中 {n_uniprot} 个成功匹配 UniProt 蛋白记录。\n")

    if getattr(result, "intersection", None) is not None:
        dz = result.disease or {}
        c = (result.intersection or {}).get("counts", {})
        L.append("### 疾病靶点与交集")
        L.append(
            f"以「{dz.get('query')}」为目标疾病，自 Open Targets Platform 检索疾病相关基因"
            f"{('（共 ' + str(dz.get('n', 0)) + ' 个）') if dz.get('found') else ''}。"
            f"将药物靶点与疾病靶点取交集，得到潜在作用靶点 {c.get('intersection', 0)} 个，"
            f"作为后续网络与富集分析的核心靶点集。\n")

    if getattr(result, "ppi", None) is not None:
        ppi = result.ppi
        hubs = ", ".join(h["gene"] for h in (ppi.get("hubs") or [])[:5])
        L.append("### 蛋白互作（PPI）网络构建")
        L.append(
            f"将核心靶点提交 STRING 数据库（物种人类，combined score 阈值见配置）构建蛋白互作网络，"
            f"得到节点 {ppi.get('n_nodes', 0)} 个、互作边 {ppi.get('n_edges', 0)} 条，"
            f"并按节点度数（degree）识别核心（hub）靶点"
            f"{('，度数靠前者为 ' + hubs) if hubs else ''}。"
            f"网络以 GraphML 格式导出，可由 Cytoscape 直接打开。\n")

    if getattr(result, "enrichment", None) is not None:
        libs = list((result.enrichment or {}).keys())
        lib_zh = []
        for lb in libs:
            if "GO" in lb:
                lib_zh.append("基因本体（GO，生物学过程）")
            elif "KEGG" in lb:
                lib_zh.append("KEGG 通路")
            else:
                lib_zh.append(lb)
        n_terms = sum(len(v) for v in (result.enrichment or {}).values())
        L.append("### GO / KEGG 富集分析")
        L.append(
            f"以核心靶点经 Enrichr 进行功能富集分析，库包括 {'、'.join(lib_zh)}；"
            f"以 Benjamini-Hochberg 校正后 P 值 < 0.05 为显著性标准，"
            f"共得到显著富集条目 {n_terms} 条。\n")

    L.append("### 数据可得性与版本")
    L.append(
        f"所有外部数据库于 {access_date} 访问；具体版本与引用见下方「参考文献」。"
        f"在线查询结果均本地缓存以保证可复现。\n")

    L.append("## 参考文献")
    for i, ref in enumerate(build_references(result, access_date), 1):
        L.append(f"{i}. {ref['citation']} {ref['url']}（访问日期：{ref['access_date']}）")
    return "\n".join(L)


def _today() -> str:
    """当天日期 YYYY-MM-DD（调用方未注入时的默认）。"""
    import datetime
    return datetime.date.today().isoformat()


def methods_and_refs(result, access_date: Optional[str] = None):
    """便捷封装：返回 (methods_md, references_list)。access_date 缺省取当天。"""
    if access_date is None:
        access_date = _today()
    return build_methods(result, access_date), build_references(result, access_date)
