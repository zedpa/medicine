"""药物靶点 × 疾病靶点 交集（纯函数，韦恩图就绪）。

返回结构可直接喂 matplotlib-venn：intersection / drug_only / disease_only + counts。
"""
from __future__ import annotations


def intersect_targets(drug_genes, disease_genes) -> dict:
    drug = set(drug_genes)
    dis = set(disease_genes)
    inter = sorted(drug & dis)
    return {
        "intersection": inter,
        "drug_only": sorted(drug - dis),
        "disease_only": sorted(dis - drug),
        "counts": {"drug": len(drug), "disease": len(dis), "intersection": len(inter)},
    }
