"""T4 验收 AC-14…AC-16: Enrichr 富集解析/过滤/排序/缓存(全离线)。"""
from src.cache import Cache
from src.config import load_config
from src.enrichment import EnrichrClient

LIB = "KEGG_2021_Human"

# Enrichr enrich 响应: {lib: [[rank, term, p, z, combined, [overlap], adj_p, old_p, old_adj_p], ...]}
ENRICH_JSON = {LIB: [
    [1, "Pathway A", 1e-6, 2.0, 50.0, ["ACE", "AGT"], 1e-4, 0, 0],
    [2, "Pathway B", 1e-3, 1.5, 80.0, ["REN"], 2e-3, 0, 0],       # combined 更高
    [3, "Pathway C", 0.04, 1.0, 10.0, ["X"], 0.20, 0, 0],          # adj_p 超阈值 -> 剔除
]}


class _ExplodingSession:
    def get(self, *a, **k):
        raise AssertionError("命中缓存时不应发起网络请求")

    def post(self, *a, **k):
        raise AssertionError("命中缓存时不应发起网络请求")


def test_parse_enrich_filter_sort_topn():  # AC-14
    rows = EnrichrClient._parse_enrich(ENRICH_JSON, LIB, adj_p_max=0.05, top_n=10)
    assert [r["term"] for r in rows] == ["Pathway B", "Pathway A"]   # combined 降序, C 被剔除
    assert rows[0]["n_overlap"] == 1
    assert rows[1]["overlap_genes"] == ["ACE", "AGT"]
    assert rows[0]["adj_p_value"] == 2e-3


def test_parse_enrich_topn_and_empty():  # AC-15
    one = EnrichrClient._parse_enrich(ENRICH_JSON, LIB, adj_p_max=0.05, top_n=1)
    assert len(one) == 1 and one[0]["term"] == "Pathway B"
    assert EnrichrClient._parse_enrich({}, LIB, adj_p_max=0.05, top_n=10) == []
    assert EnrichrClient._parse_enrich({"OTHER": []}, LIB, adj_p_max=0.05, top_n=10) == []


def test_enrich_cache_hit_no_network(tmp_path):  # AC-16
    cache = Cache(str(tmp_path / "c.sqlite"))
    cfg = load_config()
    ecfg = cfg.raw["enrichment"]
    genes = ["ACE", "AGT", "REN"]
    key = f"{LIB}|{ecfg['adj_p_max']}|{ecfg['top_n']}|{','.join(sorted(genes))}"
    injected = [{"term": "Pathway B", "p_value": 1e-3, "adj_p_value": 2e-3,
                 "combined_score": 80.0, "overlap_genes": ["REN"], "n_overlap": 1}]
    cache.set("enrichr", key, injected)

    client = EnrichrClient(cfg, cache, session=_ExplodingSession())
    assert client.enrich(genes, LIB) == injected
