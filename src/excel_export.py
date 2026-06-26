"""多 sheet Excel 导出。

sheets:
  概览 Summary          : 药材信息 + 口径快照 + 统计
  成分表 Compounds       : CID / 名称 / SMILES / InChIKey / ADME(OB,DL 或 QED) / 是否通过
  成分-靶点 CompoundTarget: 成分 -> 靶点(gene symbol) long, 含证据等级/分数/来源
  靶点蛋白 Proteins      : gene symbol -> UniProt(accession, 蛋白名, 长度, 功能, 序列)
  成分x靶点矩阵 Matrix    : 0/1 矩阵
"""
from __future__ import annotations

import os

import pandas as pd

from .pipeline import PipelineResult


def export(result: PipelineResult, out_path: str) -> str:
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
        if not matrix.empty:
            matrix.to_excel(xw, sheet_name="成分x靶点矩阵")
    return out_path
