"""spec-003 T3 验收 AC-12…AC-14: 结果快照(可序列化往返) + 历史会话携带快照。"""
import json

from src.history import HistoryStore
from src.pipeline import PipelineResult, result_to_snapshot, snapshot_to_result


def _sample_result():
    return PipelineResult(
        query="肉桂", found=True,
        herb={"chinese": "肉桂", "latin": "Cinnamomum cassia"},
        config_snapshot={"adme_mode": "tcmsp_live", "ob_min": 30, "dl_min": 0.1},
        compounds=[{"name": "肉桂醛", "ob": 32.0, "dl": 0.023}],
        compound_targets=[{"compound": "肉桂醛", "gene": "PTGS2"}],
        proteins=[{"gene": "PTGS2", "uniprot": "P35354"}],
        disease={"found": True, "label": "hypertension", "n": 2},
        intersection={"intersection": ["PTGS2"], "drug_only": ["TRPA1"],
                      "disease_only": ["AGT"], "counts": {"drug": 2, "disease": 2, "intersection": 1}},
        ppi={"n_nodes": 2, "n_edges": 1, "basis": "intersection",
             "nodes": ["PTGS2", "AGT"], "edges": [{"a": "PTGS2", "b": "AGT", "score": 0.7}],
             "hubs": [{"gene": "PTGS2", "degree": 1}]},
        enrichment={"KEGG_2021_Human": [{"term": "Renin-angiotensin system",
                    "adj_p_value": 8e-9, "combined_score": 1.5e4, "n_overlap": 2}]},
        stats={"ingredients_total": 99, "unique_targets": 1},
        message="")


def test_snapshot_is_json_serializable():  # AC-12
    snap = result_to_snapshot(_sample_result(), excel_path="outputs/肉桂.xlsx")
    s = json.dumps(snap, ensure_ascii=False)        # 不报错即证明全 JSON 安全
    assert "肉桂醛" in s
    for f in ("query", "found", "herb", "compounds", "ppi", "enrichment", "stats"):
        assert f in snap["result"]
    assert snap["excel_path"] == "outputs/肉桂.xlsx"


def test_snapshot_roundtrip_equal():  # AC-13
    r = _sample_result()
    snap = result_to_snapshot(r, excel_path="p.xlsx")
    # 经 JSON 往返(模拟落库)后再重建
    snap2 = json.loads(json.dumps(snap, ensure_ascii=False))
    rebuilt, path = snapshot_to_result(snap2)
    assert isinstance(rebuilt, PipelineResult)
    assert rebuilt == r          # dataclass 逐字段相等 -> 往返无损
    assert path == "p.xlsx"


def test_history_carries_results(tmp_path):  # AC-14
    store = HistoryStore(str(tmp_path / "h.sqlite"))
    snap = result_to_snapshot(_sample_result(), excel_path="p.xlsx")
    store.save({"id": "c1", "owner": "u1", "title": "肉桂",
                "created_at": "2026-06-30T10:00:00",
                "updated_at": "2026-06-30T10:00:00",
                "messages": [{"role": "user", "content": "肉桂"}],
                "results": [snap]})
    got = store.get("c1", owner="u1")
    assert got["results"] == [snap]                 # 经 sqlite 往返等价
    rebuilt, path = snapshot_to_result(got["results"][0])
    assert rebuilt.query == "肉桂" and path == "p.xlsx"


def test_history_without_results_backward_compatible(tmp_path):  # AC-14 向后兼容
    store = HistoryStore(str(tmp_path / "h.sqlite"))
    store.save({"id": "c2", "owner": "u1", "title": "黄芪",
                "created_at": "2026-06-30T10:00:00",
                "updated_at": "2026-06-30T10:00:00",
                "messages": [{"role": "user", "content": "黄芪"}]})   # 不带 results
    assert store.get("c2", owner="u1")["results"] == []
