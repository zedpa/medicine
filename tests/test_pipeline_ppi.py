"""T3 验收 AC-12, AC-13: PPI 挂载到管道结果(注入缓存, 不触网)。"""
from src.cache import Cache
from src.config import Config, load_config
from src.pipeline import PipelineResult, _attach_ppi


def _inject(cache, cfg, genes):
    pcfg = cfg.raw["ppi"]
    key = f"{pcfg['species']}|{pcfg['score_min']}|{','.join(sorted(genes))}"
    payload = {"nodes": sorted(genes),
               "edges": [{"a": sorted(genes)[0], "b": sorted(genes)[1], "score": 0.9}],
               "n_nodes": len(genes), "n_edges": 1, "source": "STRING"}
    cache.set("string", key, payload)
    return payload


def test_attach_ppi_prefers_intersection(tmp_path):  # AC-12
    cfg = load_config()
    cache = Cache(str(tmp_path / "c.sqlite"))
    _inject(cache, cfg, ["ACE", "AGT"])               # 交集靶点的网络

    result = PipelineResult(query="肉桂", found=True)
    result.intersection = {"intersection": ["ACE", "AGT"], "drug_only": [], "disease_only": [],
                           "counts": {"drug": 4, "disease": 2, "intersection": 2}}
    _attach_ppi(result, {"ACE", "AGT", "REN", "X"}, cfg, cache, progress=None)

    assert result.ppi is not None
    assert result.ppi["n_nodes"] == 2          # 用了交集(2)而非全集(4)
    assert result.ppi["hubs"][0]["degree"] >= 1


def test_attach_ppi_skip_when_too_few(tmp_path):  # AC-12 边界
    cfg = load_config()
    cache = Cache(str(tmp_path / "c.sqlite"))
    result = PipelineResult(query="肉桂", found=True)
    _attach_ppi(result, {"ACE"}, cfg, cache, progress=None)
    assert result.ppi is None


def test_attach_ppi_disabled(tmp_path):  # AC-13
    cfg = Config(raw={"ppi": {"enabled": False}})
    cache = Cache(str(tmp_path / "c.sqlite"))
    result = PipelineResult(query="肉桂", found=True)
    _attach_ppi(result, {"ACE", "AGT", "REN"}, cfg, cache, progress=None)
    assert result.ppi is None
