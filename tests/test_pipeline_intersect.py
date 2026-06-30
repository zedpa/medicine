"""T1 验收 AC-6, AC-7: 疾病/交集挂载到管道结果(注入缓存, 不触网/不依赖全量库)。"""
from src.cache import Cache
from src.config import load_config
from src.pipeline import PipelineResult, _attach_disease


def test_attach_disease_intersection(tmp_path):  # AC-6
    cfg = load_config()
    cache = Cache(str(tmp_path / "c.sqlite"))
    score_min = cfg.raw.get("disease", {}).get("score_min", 0.1)
    cache.set("disease", f"高血压|{score_min}", {
        "query": "高血压", "found": True, "efo_id": "EFO_0000537", "label": "hypertension",
        "genes": [{"symbol": "AGT", "score": 0.82}, {"symbol": "PTGS2", "score": 0.3}], "n": 2})

    result = PipelineResult(query="肉桂", found=True)
    drug_genes = {"PTGS2", "TRPA1", "RELA"}
    _attach_disease(result, drug_genes, cfg, cache, disease="高血压", progress=None)

    assert result.disease["found"] is True
    assert result.intersection["intersection"] == ["PTGS2"]
    c = result.intersection["counts"]
    assert c["drug"] == 3 and c["disease"] == 2 and c["intersection"] == 1


def test_attach_disease_none_backward_compatible(tmp_path):  # AC-7
    cfg = load_config()
    cache = Cache(str(tmp_path / "c.sqlite"))
    result = PipelineResult(query="肉桂", found=True)
    _attach_disease(result, {"PTGS2"}, cfg, cache, disease=None, progress=None)
    assert result.disease is None
    assert result.intersection is None
