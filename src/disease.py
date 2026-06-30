"""疾病靶点客户端：疾病名 -> 人类相关基因(gene symbol) + 关联分数。

数据源: Open Targets Platform GraphQL (免密钥)。两步：
  ① search(queryString, entityNames:["disease"]) -> EFO id
  ② disease(efoId){ associatedTargets } -> target.approvedSymbol + score (0~1 关联强度)
带本地缓存(ns=disease)，可复现；无命中如实返回 found=False，不编造（P3 不造假）。
"""
from __future__ import annotations

import time
from typing import Optional

import requests

from .cache import Cache
from .config import Config

DEFAULT_BASE = "https://api.platform.opentargets.org/api/v4/graphql"

_SEARCH_Q = """
query($q:String!){ search(queryString:$q, entityNames:["disease"]){
  hits{ id entity name } } }
"""

_ASSOC_Q = """
query($efo:String!,$size:Int!){ disease(efoId:$efo){ id name
  associatedTargets(page:{index:0,size:$size}){
    rows{ score target{ approvedSymbol } } } } }
"""

# Open Targets 检索对中文支持差 -> 常见中医研究病名 中->英 别名(命中后用英文检索)。
# 仅作检索回退, 输出仍保留用户原始 query。覆盖不到的病名按原样检索(可能未命中, 如实返回)。
_DISEASE_ALIASES = {
    "高血压": "hypertension",
    "糖尿病": "diabetes mellitus",
    "2型糖尿病": "type 2 diabetes mellitus",
    "高血脂": "hyperlipidemia",
    "高脂血症": "hyperlipidemia",
    "冠心病": "coronary heart disease",
    "动脉粥样硬化": "atherosclerosis",
    "脑卒中": "stroke",
    "中风": "stroke",
    "类风湿关节炎": "rheumatoid arthritis",
    "骨质疏松": "osteoporosis",
    "阿尔茨海默病": "Alzheimer disease",
    "抑郁症": "depression",
    "失眠": "insomnia",
    "肥胖": "obesity",
    "非酒精性脂肪肝": "non-alcoholic fatty liver disease",
    "肝纤维化": "liver fibrosis",
    "慢性肾病": "chronic kidney disease",
    "哮喘": "asthma",
    "溃疡性结肠炎": "ulcerative colitis",
    "乳腺癌": "breast cancer",
    "肝癌": "liver cancer",
    "肺癌": "lung cancer",
    "胃癌": "gastric cancer",
    "结直肠癌": "colorectal cancer",
}


def _search_terms(name: str) -> list:
    """检索候选词: 原词优先; 若有中->英别名则追加; 否则若含中文且无别名, 仅用原词。"""
    terms = [name]
    alias = _DISEASE_ALIASES.get(name.strip())
    if alias and alias != name:
        terms.append(alias)
    return terms


class DiseaseClient:
    def __init__(self, cfg: Config, cache: Cache, session=None):
        self.cfg = cfg
        self.cache = cache
        self.dcfg = cfg.raw.get("disease", {})
        self.base = self.dcfg.get("base_url", DEFAULT_BASE)
        self.timeout = self.dcfg.get("timeout", cfg.services.get("request_timeout", 30))
        self.size = int(self.dcfg.get("max_targets", 3000))
        if session is not None:
            self.session = session
        else:
            self.session = requests.Session()
            self.session.headers.update({"User-Agent": "tcm-netpharm/0.1 (research)"})

    # ---------------- 纯解析（可单测，离线） ----------------
    @staticmethod
    def _pick_disease(search_json: dict):
        hits = (((search_json or {}).get("data") or {}).get("search") or {}).get("hits") or []
        for h in hits:
            if h.get("entity") == "disease" and h.get("id"):
                return h["id"], h.get("name")
        return (None, None)

    @staticmethod
    def _parse_associations(assoc_json: dict, score_min: float) -> list:
        disease = ((assoc_json or {}).get("data") or {}).get("disease") or {}
        rows = (disease.get("associatedTargets") or {}).get("rows") or []
        out = []
        for r in rows:
            sym = ((r.get("target") or {}).get("approvedSymbol"))
            score = r.get("score")
            if not sym or score is None or score < score_min:
                continue
            out.append({"symbol": sym, "score": score})
        out.sort(key=lambda x: x["score"], reverse=True)
        return out

    # ---------------- 网络 ----------------
    def _gql(self, query: str, variables: dict) -> Optional[dict]:
        try:
            resp = self.session.post(self.base, json={"query": query, "variables": variables},
                                     timeout=self.timeout)
            if resp.status_code == 200:
                return resp.json()
        except (requests.RequestException, ValueError):
            return None
        return None

    def disease_targets(self, name: str, score_min: Optional[float] = None) -> dict:
        """返回 {query, found, efo_id, label, genes:[{symbol,score}], n}。带缓存。"""
        if score_min is None:
            score_min = float(self.dcfg.get("score_min", 0.1))
        key = f"{name}|{score_min}"
        cached = self.cache.get("disease", key)
        if cached is not None:
            return cached

        out = {"query": name, "found": False, "efo_id": None, "label": None, "genes": [], "n": 0}
        # 依次尝试检索候选词(原词 -> 中英别名), 命中即止
        efo = label = None
        for term in _search_terms(name):
            sj = self._gql(_SEARCH_Q, {"q": term})
            efo, label = self._pick_disease(sj or {})
            if efo:
                break
            time.sleep(0.1)
        if efo:
            time.sleep(0.2)
            aj = self._gql(_ASSOC_Q, {"efo": efo, "size": self.size})
            genes = self._parse_associations(aj or {}, score_min)
            out.update({"found": bool(genes), "efo_id": efo, "label": label,
                        "genes": genes, "n": len(genes)})
        # 仅缓存命中结果: 避免一次"未命中"(网络抖动/检索口径变化)被永久缓存
        if out["found"]:
            self.cache.set("disease", key, out)
        return out
