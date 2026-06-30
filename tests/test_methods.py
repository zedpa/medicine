"""T5 验收 AC-18…AC-22: 方法学 & 引用自动生成(纯本地, 零网络, 可复现)。"""
import re

from src.methods import build_methods, build_references
from src.pipeline import PipelineResult

DATE = "2026-06-30"


def _base_result(**over):
    r = PipelineResult(query="肉桂", found=True)
    r.herb = {"chinese": "肉桂", "latin": "Cinnamomum cassia", "pinyin": "rougui"}
    r.config_snapshot = {"adme_mode": "tcmsp_live(n=99)", "ob_min": 30.0, "dl_min": 0.1,
                         "predicted_score_min": 0.4, "taxon_id": 9606}
    r.compounds = [{"adme_passed": True}] * 6 + [{"adme_passed": False}] * 261
    r.compound_targets = [{"gene_symbol": "PTGS2"}, {"gene_symbol": "TRPA1"}]
    r.proteins = [{"accession": "P35354"}, {"accession": "O75762"}]
    r.stats = {"ingredients_total": 267, "compounds_passed_adme": 6,
               "unique_targets": 2, "targets_with_uniprot": 2}
    for k, v in over.items():
        setattr(r, k, v)
    return r


def test_references_base_set():  # AC-18
    refs = build_references(_base_result(), DATE)
    names = " ".join(r["name"] for r in refs)
    assert "BATMAN" in names and "PubChem" in names and "UniProt" in names
    for r in refs:
        assert r["access_date"] == DATE
        assert re.search(r"https?://", r["url"])


def test_references_conditional():  # AC-19
    r = _base_result(
        disease={"query": "高血压", "found": True, "n": 78},
        intersection={"intersection": ["PTGS2"], "drug_only": [], "disease_only": [],
                      "counts": {"drug": 2, "disease": 78, "intersection": 1}},
        ppi={"n_nodes": 2, "n_edges": 1, "hubs": [{"gene": "PTGS2", "degree": 1}]},
        enrichment={"KEGG_2021_Human": [{"term": "Pathways in cancer"}]})
    names = " ".join(x["name"] for x in build_references(r, DATE))
    assert "Open Targets" in names and "STRING" in names and "Enrichr" in names

    names0 = " ".join(x["name"] for x in build_references(_base_result(), DATE))
    assert "Open Targets" not in names0 and "STRING" not in names0 and "Enrichr" not in names0


def test_methods_numbers_and_disease_gating():  # AC-20
    m_no = build_methods(_base_result(), DATE)
    assert "肉桂" in m_no and "267" in m_no and "6" in m_no
    assert "疾病" not in m_no and "交集" not in m_no

    r = _base_result(
        disease={"query": "高血压", "found": True, "n": 78},
        intersection={"intersection": ["PTGS2"], "drug_only": [], "disease_only": [],
                      "counts": {"drug": 2, "disease": 78, "intersection": 1}})
    m_yes = build_methods(r, DATE)
    assert "高血压" in m_yes and "交集" in m_yes


def test_methods_adme_source_fidelity():  # AC-21
    r_proxy = _base_result()
    r_proxy.config_snapshot = {**r_proxy.config_snapshot, "adme_mode": "rdkit_proxy(tcmsp_miss)"}
    m = build_methods(r_proxy, DATE)
    assert "RDKit" in m
    assert any("RDKit" in x["name"] for x in build_references(r_proxy, DATE))

    m2 = build_methods(_base_result(), DATE)   # tcmsp_live
    assert "TCMSP" in m2
    assert not any("RDKit" in x["name"] for x in build_references(_base_result(), DATE))


def test_reproducible_bytewise():  # AC-22
    r = _base_result()
    assert build_methods(r, DATE) == build_methods(r, DATE)
    assert build_references(r, DATE) == build_references(r, DATE)
