"""多 sheet Excel 导出。

sheets:
  概览 Summary          : 药材信息 + 口径快照 + 统计
  成分表 Compounds       : CID / 名称 / SMILES / InChIKey / ADME(OB,DL 或 QED) / 是否通过
  成分-靶点 CompoundTarget: 成分 -> 靶点(gene symbol) long, 含证据等级/分数/来源
  靶点蛋白 Proteins      : gene symbol -> UniProt(accession, 蛋白名, 长度, 功能, 序列)
  疾病靶点 DiseaseTargets : (仅 disease) symbol/score, 来自 Open Targets
  交集靶点 Intersection   : (仅 disease) category(intersection/drug_only/disease_only)/gene
  Hub靶点 Hub            : (仅 PPI) gene/degree, STRING 网络度数排序
  PPI边表 Edges          : (仅 PPI) a/b/score (combined 0~1)
  GO富集/KEGG富集 Enrich  : (仅富集) term/p/adj_p/combined_score/n_overlap/overlap_genes
  方法学 Methods          : 自动生成的中文「材料与方法」草稿 + 规范引用
  成分x靶点矩阵 Matrix    : 0/1 矩阵
另写出 <同名>.graphml (Cytoscape, 当存在 PPI 网络) 与 <同名>_方法学.md。
"""
from __future__ import annotations

import os

import pandas as pd

from .methods import methods_and_refs
from .pipeline import PipelineResult
from .ppi import to_graphml


def export(result: PipelineResult, out_path: str, access_date: str = None) -> str:
    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    herb = result.herb
    summary_rows = [
        ("查询输入", result.query),
        ("匹配方式", herb.get("match_type")),
        ("中文名", herb.get("chinese")),
        ("拼音", herb.get("pinyin")),
        ("拉丁学名", herb.get("latin")),
        ("英文名", herb.get("english")),
        ("来源库", herb.get("source_db")),
        ("", ""),
        ("ADME 模式", result.config_snapshot.get("adme_mode")),
        ("OB 阈值", result.config_snapshot.get("ob_min")),
        ("DL 阈值", result.config_snapshot.get("dl_min")),
        ("QED 阈值(proxy)", result.config_snapshot.get("qed_min")),
        ("预测分数阈值", result.config_snapshot.get("predicted_score_min")),
        ("物种 taxon", result.config_snapshot.get("taxon_id")),
        ("", ""),
    ]
    for k, v in result.stats.items():
        summary_rows.append((k, v))
    df_summary = pd.DataFrame(summary_rows, columns=["项", "值"])

    df_cpd = pd.DataFrame(result.compounds, columns=[
        "cid", "name", "batman_name", "smiles", "inchikey",
        "adme_source", "ob", "dl", "qed", "lipinski_violations", "adme_passed", "adme_reason"])
    df_ct = pd.DataFrame(result.compound_targets, columns=[
        "cid", "compound_name", "gene_symbol", "evidence", "max_score", "source_db"])
    df_prot = pd.DataFrame(result.proteins, columns=[
        "symbol", "accession", "uniprot_id", "protein_name", "length", "function", "sequence"])

    # T1: 疾病靶点 + 交集 (仅当提供 disease)
    df_disease = df_inter = None
    if result.disease is not None:
        df_disease = pd.DataFrame(result.disease.get("genes", []), columns=["symbol", "score"])
        inter = result.intersection or {}
        rows = ([("intersection", g) for g in inter.get("intersection", [])]
                + [("drug_only", g) for g in inter.get("drug_only", [])]
                + [("disease_only", g) for g in inter.get("disease_only", [])])
        df_inter = pd.DataFrame(rows, columns=["category", "gene_symbol"])

    # T3: PPI 边表 + Hub 靶点 (仅当有 PPI 网络)
    df_ppi = df_hub = None
    if result.ppi is not None:
        df_ppi = pd.DataFrame(result.ppi.get("edges", []), columns=["a", "b", "score"])
        df_hub = pd.DataFrame(result.ppi.get("hubs", []), columns=["gene", "degree"])

    # T4: GO/KEGG 富集 (仅当有富集结果). 库名 -> sheet 名
    _LIB_SHEET = {"GO_Biological_Process_2021": "GO富集", "KEGG_2021_Human": "KEGG富集"}
    enrich_sheets = []  # [(sheet_name, df)]
    if result.enrichment is not None:
        cols = ["term", "p_value", "adj_p_value", "combined_score", "n_overlap", "overlap_genes"]
        for lib, rows in result.enrichment.items():
            df_e = pd.DataFrame([{**r, "overlap_genes": ";".join(r.get("overlap_genes", []))}
                                 for r in rows], columns=cols)
            sheet = _LIB_SHEET.get(lib, lib[:28])
            enrich_sheets.append((sheet, df_e))

    # 成分 x 靶点 0/1 矩阵
    if result.compound_targets:
        mt = pd.DataFrame(result.compound_targets)
        matrix = (mt.assign(v=1)
                    .pivot_table(index="compound_name", columns="gene_symbol", values="v",
                                 aggfunc="max", fill_value=0))
    else:
        matrix = pd.DataFrame()

    with pd.ExcelWriter(out_path, engine="openpyxl") as xw:
        df_summary.to_excel(xw, sheet_name="概览", index=False)
        df_cpd.to_excel(xw, sheet_name="成分表", index=False)
        df_ct.to_excel(xw, sheet_name="成分-靶点", index=False)
        df_prot.to_excel(xw, sheet_name="靶点蛋白", index=False)
        if df_disease is not None:
            df_disease.to_excel(xw, sheet_name="疾病靶点", index=False)
            df_inter.to_excel(xw, sheet_name="交集靶点", index=False)
        if df_ppi is not None:
            df_hub.to_excel(xw, sheet_name="Hub靶点", index=False)
            df_ppi.to_excel(xw, sheet_name="PPI边表", index=False)
        for sheet, df_e in enrich_sheets:
            df_e.to_excel(xw, sheet_name=sheet, index=False)
        # T5: 方法学 + 参考文献
        methods_md, refs = methods_and_refs(result, access_date)
        df_methods = pd.DataFrame(
            [("方法学正文", methods_md.split("## 参考文献")[0].strip())]
            + [(f"参考文献{i}", f"{r['citation']} {r['url']}（访问 {r['access_date']}）")
               for i, r in enumerate(refs, 1)],
            columns=["区块", "内容"])
        df_methods.to_excel(xw, sheet_name="方法学", index=False)
        if not matrix.empty:
            matrix.to_excel(xw, sheet_name="成分x靶点矩阵")

    # T3: 同时写出 Cytoscape 可直接打开的 GraphML
    if result.ppi is not None and result.ppi.get("edges"):
        gpath = os.path.splitext(out_path)[0] + ".graphml"
        with open(gpath, "w", encoding="utf-8") as fh:
            fh.write(to_graphml(result.ppi["nodes"], result.ppi["edges"]))

    # T5: 同时写出可粘贴的「材料与方法」markdown
    mpath = os.path.splitext(out_path)[0] + "_方法学.md"
    with open(mpath, "w", encoding="utf-8") as fh:
        fh.write(methods_md)
    return out_path
