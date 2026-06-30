"""GO/KEGG 富集分析客户端：靶点 gene symbol 列表 -> Enrichr 富集结果。

数据源: Enrichr (https://maayanlab.cloud/Enrichr)，免密钥。两步：
  ① POST addList(genes) -> userListId
  ② GET enrich?userListId=&backgroundType=<library>
     -> {lib: [[rank, term, p, z, combined, [overlap], adj_p, ...], ...]}
带本地缓存(ns=enrichr)，可复现；无命中不编造（P3）。
"""
from __future__ import annotations

import time
from typing import Optional

import requests

from .cache import Cache
from .config import Config

DEFAULT_BASE = "https://maayanlab.cloud/Enrichr"

# Enrichr enrich 行字段位置
_I_TERM, _I_P, _I_COMBINED, _I_OVERLAP, _I_ADJP = 1, 2, 4, 5, 6


class EnrichrClient:
    def __init__(self, cfg: Config, cache: Cache, session=None):
        self.cfg = cfg
        self.cache = cache
        self.ecfg = cfg.raw.get("enrichment", {})
        self.base = self.ecfg.get("base_url", DEFAULT_BASE)
        self.timeout = int(self.ecfg.get("timeout", 30))
        if session is not None:
            self.session = session
        else:
            self.session = requests.Session()
            self.session.headers.update({"User-Agent": "tcm-netpharm/0.1 (research)"})

    @staticmethod
    def _parse_enrich(enrich_json: dict, library: str, adj_p_max: float, top_n: int) -> list:
        """Enrichr enrich 响应 -> [{term,p_value,adj_p_value,combined_score,overlap_genes,n_overlap}]。

        按 adj_p_max 过滤、combined_score 降序、截断 top_n。
        """
        rows = (enrich_json or {}).get(library) or []
        out = []
        for r in rows:
            if not isinstance(r, (list, tuple)) or len(r) <= _I_ADJP:
                continue
            adj_p = r[_I_ADJP]
            if adj_p is None or adj_p > adj_p_max:
                continue
            overlap = list(r[_I_OVERLAP]) if isinstance(r[_I_OVERLAP], (list, tuple)) else []
            out.append({
                "term": r[_I_TERM],
                "p_value": r[_I_P],
                "adj_p_value": adj_p,
                "combined_score": r[_I_COMBINED],
                "overlap_genes": overlap,
                "n_overlap": len(overlap),
            })
        out.sort(key=lambda x: (x["combined_score"] is None, -(x["combined_score"] or 0)))
        return out[:top_n]

    def _add_list(self, genes: list) -> Optional[str]:
        try:
            resp = self.session.post(
                f"{self.base}/addList",
                files={"list": (None, "\n".join(genes)), "description": (None, "tcm-netpharm")},
                timeout=self.timeout)
            if resp.status_code == 200:
                return str(resp.json().get("userListId"))
        except (requests.RequestException, ValueError):
            return None
        return None

    def enrich(self, genes, library: str,
               adj_p_max: Optional[float] = None, top_n: Optional[int] = None) -> list:
        """gene 列表 + 库 -> 富集行列表。带缓存。"""
        if adj_p_max is None:
            adj_p_max = float(self.ecfg.get("adj_p_max", 0.05))
        if top_n is None:
            top_n = int(self.ecfg.get("top_n", 20))
        genes = [g for g in genes if g]
        key = f"{library}|{adj_p_max}|{top_n}|{','.join(sorted(genes))}"
        cached = self.cache.get("enrichr", key)
        if cached is not None:
            return cached

        rows: list = []
        list_id = self._add_list(genes)
        if list_id:
            time.sleep(0.2)
            try:
                resp = self.session.get(
                    f"{self.base}/enrich",
                    params={"userListId": list_id, "backgroundType": library},
                    timeout=self.timeout)
                data = resp.json() if resp.status_code == 200 else {}
            except (requests.RequestException, ValueError):
                data = {}
            rows = self._parse_enrich(data, library, adj_p_max, top_n)
        self.cache.set("enrichr", key, rows)
        time.sleep(0.2)
        return rows
