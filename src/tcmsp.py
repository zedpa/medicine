"""TCMSP 在线 per-herb 抓取器 (模拟人工浏览, 仅抓查询药材, 礼貌低频)。

来源: https://www.tcmsp-e.com/tcmspsearch.php (参考开源项目 shujuecn/TCMSP-Spider)
流程:
  1. GET tcmspsearch.php 取 SearchForm 隐藏 token
  2. ?qs=herb_all_name&q=<药材> 取候选, 解析 herb_en_name
  3. ?qr=<en_name>&qsr=herb_en_name 取成分网格(嵌入 JS 的 JSON), 含 ob/dl/MOL_ID/molecule_name

返回该药材的 OB/DL, 并(可选)经 PubChem 把分子名解析到 InChIKey 用于跨库连接。
结果按药材缓存(ns=tcmsp)。
"""
from __future__ import annotations

import json
import re
import time
from typing import Optional

import requests

_TOKEN_RE = re.compile(r'name="token"[^>]*value="([0-9a-f]+)"')
_OBJ_RE = re.compile(r'\{[^{}]*"ob":[^{}]*\}')


def _norm(s: str) -> str:
    return re.sub(r"\s+", "", (s or "").strip().lower())


class TcmspClient:
    BASE = "https://www.tcmsp-e.com/tcmspsearch.php"

    def __init__(self, cache, timeout: int = 30):
        self.cache = cache
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        })
        self._token: Optional[str] = None

    def _get(self, params: Optional[dict] = None) -> Optional[str]:
        for attempt in range(3):
            try:
                r = self.session.get(self.BASE, params=params, timeout=self.timeout)
                if r.status_code == 200:
                    return r.text
            except requests.RequestException:
                pass
            time.sleep(0.6 * (attempt + 1))
        return None

    def _ensure_token(self) -> Optional[str]:
        if self._token:
            return self._token
        html = self._get()
        if html:
            m = _TOKEN_RE.search(html)
            if m:
                self._token = m.group(1)
        return self._token

    def _resolve_en_name(self, query: str) -> Optional[str]:
        token = self._ensure_token()
        if not token:
            return None
        html = self._get({"qs": "herb_all_name", "q": query, "token": token})
        if not html:
            return None
        q = _norm(query)
        # 抽取候选药材记录字段
        cands = []
        for m in re.finditer(
            r'"herb_cn_name":"([^"]*)"[^}]*?"herb_en_name":"([^"]*)"[^}]*?"herb_pinyin":"([^"]*)"',
            html,
        ):
            cn, en, py = (x.encode().decode("unicode_escape") for x in m.groups())
            cands.append((cn, en, py))
        if not cands:
            # 备选: 直接抓 en_name
            m = re.search(r'"herb_en_name":"([^"]*)"', html)
            return m.group(1).encode().decode("unicode_escape") if m else None
        # 精确匹配 中文/拼音/英文; 否则取首个
        for cn, en, py in cands:
            if q in (_norm(cn), _norm(py), _norm(en)):
                return en
        return cands[0][1]

    def fetch_herb_adme(self, query: str, online=None) -> dict:
        """返回 {found, en_name, by_name:{name->{ob,dl}}, by_inchikey:{ik->{ob,dl}}, n}。

        online: 可选 OnlineClients, 用于把分子名解析为 InChIKey(供跨库 InChIKey 连接)。
        """
        cache_key = _norm(query)
        cached = self.cache.get("tcmsp", cache_key)
        if cached is not None:
            return cached

        out = {"found": False, "en_name": None, "by_name": {}, "by_inchikey": {}, "n": 0}
        en_name = self._resolve_en_name(query)
        if not en_name:
            self.cache.set("tcmsp", cache_key, out)
            return out
        out["en_name"] = en_name
        token = self._ensure_token()
        html = self._get({"qr": en_name, "qsr": "herb_en_name", "token": token})
        if not html:
            self.cache.set("tcmsp", cache_key, out)
            return out

        for obj in _OBJ_RE.findall(html):
            try:
                r = json.loads(obj)
                ob = float(r.get("ob")); dl = float(r.get("dl"))
            except (ValueError, TypeError):
                continue
            name = (r.get("molecule_name") or "").strip()
            if not name:
                continue
            rec = {"ob": ob, "dl": dl, "mol_id": r.get("MOL_ID")}
            out["by_name"][name.lower()] = rec
            if online is not None:
                ik = online.pubchem_inchikey_by_name(name)
                if ik:
                    out["by_inchikey"][ik] = rec
        out["found"] = bool(out["by_name"])
        out["n"] = len(out["by_name"])
        self.cache.set("tcmsp", cache_key, out)
        return out
