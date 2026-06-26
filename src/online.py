"""在线归一化/富集客户端: PubChem, mygene, UniProt。全部带本地缓存。

- PubChem:  PubChem CID -> SMILES / InChIKey / 常用名 (FR-3 成分归一化)
- mygene:   Entrez Gene ID -> HGNC gene symbol (限人类) (FR-5 靶点归一化)
- UniProt:  gene symbol -> UniProt 蛋白信息表 (蛋白结构需求)
"""
from __future__ import annotations

import time
from typing import Optional

import requests

from .cache import Cache
from .config import Config


class OnlineClients:
    def __init__(self, cfg: Config, cache: Cache):
        self.cfg = cfg
        self.cache = cache
        self.svc = cfg.services
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "tcm-netpharm/0.1 (research)"})

    def _get(self, url: str, **kwargs) -> Optional[requests.Response]:
        timeout = self.svc.get("request_timeout", 30)
        for attempt in range(self.svc.get("retries", 3)):
            try:
                resp = self.session.get(url, timeout=timeout, **kwargs)
                if resp.status_code == 200:
                    return resp
                if resp.status_code == 404:
                    return None
            except requests.RequestException:
                pass
            time.sleep(0.5 * (attempt + 1))
        return None

    # ---------------- PubChem ----------------
    def pubchem_by_cid(self, cid: str) -> dict:
        """返回 {cid, smiles, inchikey, name}。失败字段为 None。"""
        cid = str(cid)
        cached = self.cache.get("pubchem", cid)
        if cached is not None:
            return cached
        base = self.svc["pubchem_base"]
        url = f"{base}/compound/cid/{cid}/property/Title,InChIKey,CanonicalSMILES,IsomericSMILES/JSON"
        out = {"cid": cid, "smiles": None, "inchikey": None, "name": None}
        resp = self._get(url)
        if resp is not None:
            try:
                props = resp.json()["PropertyTable"]["Properties"][0]
                out["inchikey"] = props.get("InChIKey")
                out["name"] = props.get("Title")
                # PubChem 近期把 CanonicalSMILES 输出键改为 ConnectivitySMILES / SMILES
                for k, v in props.items():
                    if "SMILES" in k and v:
                        # 优先 Isomeric/带立体的, 否则任意 SMILES
                        if out["smiles"] is None or "Isomeric" in k or k == "SMILES":
                            out["smiles"] = v
            except (KeyError, ValueError, IndexError):
                pass
        self.cache.set("pubchem", cid, out)
        time.sleep(0.2)  # 尊重 PubChem 速率
        return out

    def pubchem_inchikey_by_name(self, name: str) -> Optional[str]:
        """成分常用名 -> InChIKey (用于把 TCMSP 分子名映射到 InChIKey 做连接)。"""
        if not name:
            return None
        cached = self.cache.get("pubchem_name", name.lower())
        if cached is not None:
            return cached.get("inchikey")
        base = self.svc["pubchem_base"]
        url = f"{base}/compound/name/{requests.utils.quote(name)}/property/InChIKey/JSON"
        inchikey = None
        resp = self._get(url)
        if resp is not None:
            try:
                inchikey = resp.json()["PropertyTable"]["Properties"][0].get("InChIKey")
            except (KeyError, ValueError, IndexError):
                pass
        self.cache.set("pubchem_name", name.lower(), {"inchikey": inchikey})
        time.sleep(0.2)
        return inchikey

    # ---------------- mygene ----------------
    def entrez_to_symbol(self, entrez_ids: list[str]) -> dict[str, Optional[str]]:
        """批量 Entrez ID -> gene symbol (人类)。带缓存, 仅查询未缓存项。"""
        result: dict[str, Optional[str]] = {}
        missing: list[str] = []
        for eid in entrez_ids:
            eid = str(eid)
            c = self.cache.get("mygene", eid)
            if c is not None:
                result[eid] = c.get("symbol")
            else:
                missing.append(eid)
        if missing:
            base = self.svc["mygene_base"]
            for i in range(0, len(missing), 500):
                chunk = missing[i:i + 500]
                try:
                    resp = self.session.post(
                        f"{base}/gene",
                        data={"ids": ",".join(chunk), "fields": "symbol", "species": "human"},
                        timeout=self.svc.get("request_timeout", 30),
                    )
                    rows = resp.json() if resp.status_code == 200 else []
                except (requests.RequestException, ValueError):
                    rows = []
                got = {}
                for row in rows:
                    q = str(row.get("query"))
                    sym = row.get("symbol") if not row.get("notfound") else None
                    got[q] = sym
                for eid in chunk:
                    sym = got.get(eid)
                    self.cache.set("mygene", eid, {"symbol": sym})
                    result[eid] = sym
                time.sleep(0.2)
        return result

    # ---------------- UniProt ----------------
    def uniprot_by_symbol(self, symbol: str) -> dict:
        """gene symbol -> {symbol, accession, uniprot_id, protein_name, length, function, sequence}。"""
        cached = self.cache.get("uniprot", symbol)
        if cached is not None:
            return cached
        base = self.svc["uniprot_base"]
        taxon = self.cfg.taxon_id
        reviewed = "AND (reviewed:true)" if self.svc.get("uniprot_reviewed_only", True) else ""
        query = f"(gene_exact:{symbol}) AND (organism_id:{taxon}) {reviewed}"
        fields = "accession,id,protein_name,gene_names,length,cc_function,sequence"
        url = (f"{base}/search?query={requests.utils.quote(query)}"
               f"&fields={fields}&format=json&size=1")
        out = {"symbol": symbol, "accession": None, "uniprot_id": None,
               "protein_name": None, "length": None, "function": None, "sequence": None}
        resp = self._get(url)
        if resp is not None:
            try:
                results = resp.json().get("results", [])
                if results:
                    r = results[0]
                    out["accession"] = r.get("primaryAccession")
                    out["uniprot_id"] = r.get("uniProtkbId")
                    desc = r.get("proteinDescription", {})
                    rec = desc.get("recommendedName") or (desc.get("submissionNames") or [{}])[0]
                    out["protein_name"] = (rec.get("fullName", {}) or {}).get("value")
                    seq = r.get("sequence", {})
                    out["length"] = seq.get("length")
                    out["sequence"] = seq.get("value")
                    for c in r.get("comments", []):
                        if c.get("commentType") == "FUNCTION":
                            texts = c.get("texts", [])
                            if texts:
                                out["function"] = texts[0].get("value")
                            break
            except (KeyError, ValueError, IndexError):
                pass
        self.cache.set("uniprot", symbol, out)
        time.sleep(0.1)
        return out
