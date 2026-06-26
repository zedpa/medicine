"""BATMAN-TCM 2.0 dump 加载与索引。

提供:
  - resolve_herb(query): 药材名(中文/拼音/英文/拉丁) -> 匹配的药材 + 成分清单(含 PubChem CID)
  - known_targets(cid):  成分 -> 已知靶点 gene symbol 列表
  - predicted_targets(cid): 成分 -> 预测靶点 [(entrez_id, score), ...]

数据来源: data/raw/batman/ (见同目录 MANIFEST)。
"""
from __future__ import annotations

import gzip
import os
import re
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Optional

from .config import load_config

_CID_RE = re.compile(r"\((\d+)\)$")


def _norm(s: str) -> str:
    """名称归一化: 小写、压缩空白、去首尾。用于模糊匹配。"""
    return re.sub(r"\s+", " ", (s or "").strip().lower())


@dataclass
class Ingredient:
    cid: str
    name: str  # BATMAN 提供的 IUPAC 名


@dataclass
class HerbMatch:
    query: str
    match_type: str            # exact_chinese / exact_pinyin / latin / english / substring / none
    rows: list[dict] = field(default_factory=list)
    latin: Optional[str] = None
    chinese: Optional[str] = None
    pinyin: Optional[str] = None
    english: Optional[str] = None
    ingredients: list[Ingredient] = field(default_factory=list)

    @property
    def found(self) -> bool:
        return bool(self.rows)


class BatmanDB:
    def __init__(self, batman_dir: str):
        self.dir = batman_dir
        self._herb_rows: list[dict] = []
        self._by_chinese: dict[str, list[int]] = {}
        self._by_pinyin: dict[str, list[int]] = {}
        self._by_english: dict[str, list[int]] = {}
        self._by_latin: dict[str, list[int]] = {}
        self._known: dict[str, list[str]] = {}
        self._predicted: dict[str, list[tuple[str, float]]] = {}
        self._loaded_herbs = False
        self._loaded_known = False
        self._loaded_predicted = False

    # ---------- herb_browse ----------
    def _load_herbs(self) -> None:
        if self._loaded_herbs:
            return
        path = os.path.join(self.dir, "herb_browse.txt")
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            header = fh.readline()  # Pinyin.Name Chinese.Name English.Name Latin.Name Ingredients
            for line in fh:
                parts = line.rstrip("\n").split("\t")
                if len(parts) < 5:
                    continue
                pinyin, chinese, english, latin, ingredients = parts[0], parts[1], parts[2], parts[3], parts[4]
                idx = len(self._herb_rows)
                self._herb_rows.append(
                    {"pinyin": pinyin, "chinese": chinese, "english": english,
                     "latin": latin, "ingredients_raw": ingredients}
                )
                for value, index in ((chinese, self._by_chinese), (pinyin, self._by_pinyin),
                                     (english, self._by_english), (latin, self._by_latin)):
                    key = _norm(value)
                    if key and key != "na":
                        index.setdefault(key, []).append(idx)
        self._loaded_herbs = True

    @staticmethod
    def _parse_ingredients(raw: str) -> list[Ingredient]:
        out: list[Ingredient] = []
        seen: set[str] = set()
        for token in raw.split("|"):
            token = token.strip()
            if not token:
                continue
            m = _CID_RE.search(token)
            if not m:
                continue
            cid = m.group(1)
            name = token[: m.start()].strip()
            if cid in seen:
                continue
            seen.add(cid)
            out.append(Ingredient(cid=cid, name=name))
        return out

    def resolve_herb(self, query: str) -> HerbMatch:
        """按 中文->拼音->拉丁->英文 优先级精确匹配, 失败再子串匹配。"""
        self._load_herbs()
        q = _norm(query)
        order = [("exact_chinese", self._by_chinese), ("exact_pinyin", self._by_pinyin),
                 ("latin", self._by_latin), ("english", self._by_english)]
        matched_idx: list[int] = []
        match_type = "none"
        for mtype, index in order:
            if q in index:
                matched_idx = index[q]
                match_type = mtype
                break
        if not matched_idx:
            # 子串匹配 (拉丁名/英文名包含)，取首个命中集合
            for mtype, index in (("latin", self._by_latin), ("english", self._by_english),
                                 ("substring", self._by_chinese)):
                hits = [i for key, idxs in index.items() if q and q in key for i in idxs]
                if hits:
                    matched_idx = sorted(set(hits))
                    match_type = "substring"
                    break

        match = HerbMatch(query=query, match_type=match_type)
        if not matched_idx:
            return match
        rows = [self._herb_rows[i] for i in matched_idx]
        match.rows = rows
        match.latin = next((r["latin"] for r in rows if _norm(r["latin"]) not in ("", "na")), None)
        match.chinese = next((r["chinese"] for r in rows if _norm(r["chinese"]) not in ("", "na")), None)
        match.pinyin = rows[0]["pinyin"]
        match.english = next((r["english"] for r in rows if _norm(r["english"]) not in ("", "na")), None)
        # 跨所有命中行 union 成分（按 CID 去重）
        seen: set[str] = set()
        for r in rows:
            for ing in self._parse_ingredients(r["ingredients_raw"]):
                if ing.cid not in seen:
                    seen.add(ing.cid)
                    match.ingredients.append(ing)
        return match

    # ---------- known targets ----------
    def _load_known(self) -> None:
        if self._loaded_known:
            return
        path = os.path.join(self.dir, "known_browse_by_ingredients.txt.gz")
        with gzip.open(path, "rt", encoding="utf-8", errors="replace") as fh:
            fh.readline()  # header: PubChem_CID IUPAC_name known_target_proteins
            for line in fh:
                parts = line.rstrip("\n").split("\t")
                if len(parts) < 3:
                    continue
                cid, _name, targets = parts[0], parts[1], parts[2]
                syms = [t.strip() for t in targets.split("|") if t.strip() and t.strip().upper() != "NA"]
                if syms:
                    self._known[cid] = syms
        self._loaded_known = True

    def known_targets(self, cid: str) -> list[str]:
        self._load_known()
        return self._known.get(str(cid), [])

    # ---------- predicted targets ----------
    def _load_predicted(self) -> None:
        if self._loaded_predicted:
            return
        path = os.path.join(self.dir, "predicted_browse_by_ingredients.txt.gz")
        tok_re = re.compile(r"^(\d+)\(([\d.]+)\)$")
        # 注意: 该文件为空格分隔(与 known 的 TAB 不同)。成分名可能含空格,
        # 但 CID(首 token)与 targets(末 token, 形如 2720(0.89)|... 无内部空格)是干净的。
        with gzip.open(path, "rt", encoding="utf-8", errors="replace") as fh:
            fh.readline()  # header
            for line in fh:
                line = line.rstrip("\n")
                if " " not in line:
                    continue
                cid, rest = line.split(" ", 1)
                if not cid.isdigit():
                    continue
                targets = rest.rsplit(" ", 1)[-1]  # 末 token 即靶点串
                pairs: list[tuple[str, float]] = []
                for tok in targets.split("|"):
                    m = tok_re.match(tok.strip())
                    if m:
                        pairs.append((m.group(1), float(m.group(2))))
                if pairs:
                    self._predicted[cid] = pairs
        self._loaded_predicted = True

    def predicted_targets(self, cid: str) -> list[tuple[str, float]]:
        self._load_predicted()
        return self._predicted.get(str(cid), [])


@lru_cache(maxsize=1)
def get_db() -> BatmanDB:
    cfg = load_config()
    return BatmanDB(cfg.path("batman_dir"))
