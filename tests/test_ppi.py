"""T3 验收 AC-8…AC-11: STRING PPI 解析/hub/graphml/缓存(全离线)。"""
import xml.etree.ElementTree as ET

from src.cache import Cache
from src.config import load_config
from src.ppi import StringClient, hub_genes, to_graphml


NETWORK_TSV = (
    "stringId_A\tstringId_B\tpreferredName_A\tpreferredName_B\tncbiTaxonId\tscore\n"
    "9606.X\t9606.Y\tACE\tAGT\t9606\t0.9\n"
    "9606.Y\t9606.X\tAGT\tACE\t9606\t0.9\n"      # 反向重复 -> 去重
    "9606.X\t9606.Z\tACE\tREN\t9606\t0.3\n"      # 低于阈值 -> 丢弃
    "9606.X\t9606.W\tACE\tAGTR1\t9606\t0.7\n"
)


class _ExplodingSession:
    def get(self, *a, **k):
        raise AssertionError("命中缓存时不应发起网络请求")


def test_parse_network_tsv_threshold_and_undirected_dedup():  # AC-8
    edges = StringClient._parse_network_tsv(NETWORK_TSV, score_min=0.4)
    pairs = sorted(tuple(sorted((e["a"], e["b"]))) for e in edges)
    assert pairs == [("ACE", "AGT"), ("ACE", "AGTR1")]
    assert len(edges) == 2


def test_hub_genes_degree_sorted():  # AC-9
    edges = [{"a": "ACE", "b": "AGT", "score": 0.9},
             {"a": "ACE", "b": "AGTR1", "score": 0.7}]
    hubs = hub_genes(edges)
    assert hubs[0] == {"gene": "ACE", "degree": 2}
    assert {h["gene"] for h in hubs} == {"ACE", "AGT", "AGTR1"}
    assert [h["degree"] for h in hubs] == sorted([h["degree"] for h in hubs], reverse=True)


def test_to_graphml_roundtrip_counts():  # AC-10
    nodes = ["ACE", "AGT", "AGTR1"]
    edges = [{"a": "ACE", "b": "AGT", "score": 0.9},
             {"a": "ACE", "b": "AGTR1", "score": 0.7}]
    xml = to_graphml(nodes, edges)
    root = ET.fromstring(xml)
    assert root.tag.endswith("graphml")
    ns = "{http://graphml.graphdrawing.org/xmlns}"
    graph = root.find(f"{ns}graph")
    assert len(graph.findall(f"{ns}node")) == 3
    assert len(graph.findall(f"{ns}edge")) == 2


def test_network_cache_hit_no_network(tmp_path):  # AC-11
    cache = Cache(str(tmp_path / "c.sqlite"))
    cfg = load_config()
    pcfg = cfg.raw["ppi"]
    species, score_min = pcfg["species"], pcfg["score_min"]
    genes = ["ACE", "AGT"]
    key = f"{species}|{score_min}|{','.join(sorted(genes))}"
    injected = {"nodes": ["ACE", "AGT"], "edges": [{"a": "ACE", "b": "AGT", "score": 0.9}],
                "n_nodes": 2, "n_edges": 1, "source": "STRING"}
    cache.set("string", key, injected)

    client = StringClient(cfg, cache, session=_ExplodingSession())
    assert client.network(genes) == injected
