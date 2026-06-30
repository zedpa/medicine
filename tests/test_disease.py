"""T1 验收 AC-3, AC-4, AC-5: 疾病靶点客户端(离线: 解析纯函数 + 注入缓存)。"""
import pytest

from src.cache import Cache
from src.config import load_config
from src.disease import DiseaseClient


SEARCH_JSON = {
    "data": {"search": {"hits": [
        {"id": "ENSG000001", "entity": "target", "name": "SomeGene"},
        {"id": "EFO_0000537", "entity": "disease", "name": "hypertension"},
    ]}}
}

ASSOC_JSON = {
    "data": {"disease": {"associatedTargets": {"rows": [
        {"target": {"approvedSymbol": "AGT"}, "score": 0.82},
        {"target": {"approvedSymbol": "ACE"}, "score": 0.41},
        {"target": {"approvedSymbol": "LOWS"}, "score": 0.05},   # 低于阈值
        {"target": {"approvedSymbol": None}, "score": 0.9},      # 无 symbol, 丢弃
    ]}}}
}


class _ExplodingSession:
    """任何网络调用都炸 —— 用于证明命中缓存时不触网。"""
    def post(self, *a, **k):
        raise AssertionError("命中缓存时不应发起网络请求")


def test_search_terms_cn_alias():  # 实时测试发现: 中文病名需英文别名回退
    from src.disease import _search_terms
    assert _search_terms("高血压") == ["高血压", "hypertension"]
    assert _search_terms(" 糖尿病 ") == [" 糖尿病 ", "diabetes mellitus"]
    assert _search_terms("hypertension") == ["hypertension"]   # 已是英文, 不重复
    assert _search_terms("某种罕见病") == ["某种罕见病"]          # 无别名, 原样


def test_pick_disease():  # AC-3
    assert DiseaseClient._pick_disease(SEARCH_JSON) == ("EFO_0000537", "hypertension")
    assert DiseaseClient._pick_disease({"data": {"search": {"hits": []}}}) == (None, None)


def test_parse_associations_threshold_and_sort():  # AC-4
    rows = DiseaseClient._parse_associations(ASSOC_JSON, score_min=0.1)
    assert [r["symbol"] for r in rows] == ["AGT", "ACE"]   # 降序, 去掉低分/无名
    assert rows[0]["score"] == 0.82


def test_disease_targets_cache_hit_no_network(tmp_path):  # AC-5
    cache = Cache(str(tmp_path / "c.sqlite"))
    cfg = load_config()
    score_min = cfg.raw.get("disease", {}).get("score_min", 0.1)
    injected = {"query": "高血压", "found": True, "efo_id": "EFO_0000537",
                "label": "hypertension", "genes": [{"symbol": "AGT", "score": 0.82}], "n": 1}
    cache.set("disease", f"高血压|{score_min}", injected)

    client = DiseaseClient(cfg, cache, session=_ExplodingSession())
    out = client.disease_targets("高血压")
    assert out == injected
