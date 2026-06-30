"""T4 验收 AC-17: 富集挂载到管道结果(注入缓存, 不触网)。"""
from src.cache import Cache
from src.config import Config, load_config
from src.pipeline import PipelineResult, _attach_enrichment


def _inject(cache, cfg, lib, genes):
    ecfg = cfg.raw["enrichment"]
    key = f"{lib}|{ecfg['adj_p_max']}|{ecfg['top_n']}|{','.join(sorted(genes))}"
    rows = [{"term": f"{lib} term", "p_value": 1e-4, "adj_p_value": 1e-3,
             "combined_score": 50.0, "overlap_genes": list(genes), "n_overlap": len(genes)}]
    cache.set("enrichr", key, rows)


def test_attach_enrichment_prefers_intersection(tmp_path):  # AC-17
    cfg = load_config()
    cache = Cache(str(tmp_path / "c.sqlite"))
    inter_genes = ["ACE", "AGT", "REN"]
    for lib in cfg.raw["enrichment"]["libraries"]:
        _inject(cache, cfg, lib, inter_genes)

    result = PipelineResult(query="肉桂", found=True)
    result.intersection = {"intersection": inter_genes, "drug_only": [], "disease_only": [],
                           "counts": {"drug": 5, "disease": 3, "intersection": 3}}
    _attach_enrichment(result, {"ACE", "AGT", "REN", "X", "Y"}, cfg, cache, progress=None)

    assert result.enrichment is not None
    for lib in cfg.raw["enrichment"]["libraries"]:
        assert lib in result.enrichment
        assert result.enrichment[lib][0]["n_overlap"] == 3   # 用了交集(3)而非全集(5)


def test_attach_enrichment_skip_too_few(tmp_path):  # AC-17 边界
    cfg = load_config()
    cache = Cache(str(tmp_path / "c.sqlite"))
    result = PipelineResult(query="肉桂", found=True)
    _attach_enrichment(result, {"ACE", "AGT"}, cfg, cache, progress=None)
    assert result.enrichment is None


def test_attach_enrichment_disabled(tmp_path):  # AC-17 开关
    cfg = Config(raw={"enrichment": {"enabled": False}})
    cache = Cache(str(tmp_path / "c.sqlite"))
    result = PipelineResult(query="肉桂", found=True)
    _attach_enrichment(result, {"ACE", "AGT", "REN"}, cfg, cache, progress=None)
    assert result.enrichment is None
