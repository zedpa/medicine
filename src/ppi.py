"""蛋白互作网络（PPI）客户端：靶点 gene symbol 列表 -> STRING 互作网络。

数据源: STRING (https://string-db.org/api)，免密钥。network 端点返回 TSV，
combined score 为 0~1。带本地缓存(ns=string)，可复现；无命中不编造（P3）。

附带纯函数：hub_genes(按度数找核心靶点)、to_graphml(导出 Cytoscape 可读网络)。
"""
from __future__ import annotations

import time
from typing import Optional
from xml.sax.saxutils import escape

import requests

from .cache import Cache
from .config import Config

DEFAULT_BASE = "https://string-db.org/api"


class StringClient:
    def __init__(self, cfg: Config, cache: Cache, session=None):
        self.cfg = cfg
        self.cache = cache
        self.pcfg = cfg.raw.get("ppi", {})
        self.base = self.pcfg.get("base_url", DEFAULT_BASE)
        self.species = int(self.pcfg.get("species", 9606))
        self.timeout = int(self.pcfg.get("timeout", 30))
        self.max_nodes = int(self.pcfg.get("max_nodes", 200))
        if session is not None:
            self.session = session
        else:
            self.session = requests.Session()
            self.session.headers.update({"User-Agent": "tcm-netpharm/0.1 (research)"})

    @staticmethod
    def _parse_network_tsv(text: str, score_min: float) -> list:
        """STRING network TSV -> [{a,b,score}]，按 score_min 过滤，无向边去重。"""
        lines = [ln for ln in (text or "").splitlines() if ln.strip()]
        if not lines:
            return []
        header = lines[0].split("\t")
        try:
            ia, ib = header.index("preferredName_A"), header.index("preferredName_B")
            isc = header.index("score")
        except ValueError:
            return []
        seen = set()
        edges = []
        for ln in lines[1:]:
            cols = ln.split("\t")
            if len(cols) <= max(ia, ib, isc):
                continue
            a, b = cols[ia], cols[ib]
            try:
                score = float(cols[isc])
            except ValueError:
                continue
            if not a or not b or a == b or score < score_min:
                continue
            key = frozenset((a, b))
            if key in seen:
                continue
            seen.add(key)
            edges.append({"a": a, "b": b, "score": score})
        return edges

    def network(self, genes, score_min: Optional[float] = None) -> dict:
        """gene 列表 -> {nodes, edges:[{a,b,score}], n_nodes, n_edges, source}。带缓存。"""
        if score_min is None:
            score_min = float(self.pcfg.get("score_min", 0.4))
        genes = [g for g in genes if g][: self.max_nodes]
        key = f"{self.species}|{score_min}|{','.join(sorted(genes))}"
        cached = self.cache.get("string", key)
        if cached is not None:
            return cached

        out = {"nodes": [], "edges": [], "n_nodes": 0, "n_edges": 0, "source": "STRING"}
        url = f"{self.base}/tsv/network"
        params = {"identifiers": "\r".join(genes), "species": self.species,
                  "caller_identity": "tcm-netpharm"}
        try:
            resp = self.session.get(url, params=params, timeout=self.timeout)
            text = resp.text if resp.status_code == 200 else ""
        except requests.RequestException:
            text = ""
        edges = self._parse_network_tsv(text, score_min)
        nodes = sorted({g for e in edges for g in (e["a"], e["b"])})
        out.update({"nodes": nodes, "edges": edges,
                    "n_nodes": len(nodes), "n_edges": len(edges)})
        self.cache.set("string", key, out)
        time.sleep(0.2)
        return out


def hub_genes(edges) -> list:
    """按节点度数(degree)降序 -> [{gene, degree}]。识别核心靶点。"""
    deg: dict = {}
    for e in edges:
        for g in (e["a"], e["b"]):
            deg[g] = deg.get(g, 0) + 1
    return [{"gene": g, "degree": d}
            for g, d in sorted(deg.items(), key=lambda kv: (-kv[1], kv[0]))]


def to_graphml(nodes, edges) -> str:
    """导出 Cytoscape 可直接打开的 GraphML（节点带 degree，边带 score）。"""
    deg = {h["gene"]: h["degree"] for h in hub_genes(edges)}
    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<graphml xmlns="http://graphml.graphdrawing.org/xmlns">',
        '<key id="d_label" for="node" attr.name="label" attr.type="string"/>',
        '<key id="d_degree" for="node" attr.name="degree" attr.type="int"/>',
        '<key id="d_score" for="edge" attr.name="score" attr.type="double"/>',
        '<graph edgedefault="undirected">',
    ]
    for n in nodes:
        parts.append(
            f'<node id="{escape(n)}">'
            f'<data key="d_label">{escape(n)}</data>'
            f'<data key="d_degree">{deg.get(n, 0)}</data></node>')
    for i, e in enumerate(edges):
        parts.append(
            f'<edge id="e{i}" source="{escape(e["a"])}" target="{escape(e["b"])}">'
            f'<data key="d_score">{e["score"]}</data></edge>')
    parts.append("</graph></graphml>")
    return "\n".join(parts)
