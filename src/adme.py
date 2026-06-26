"""ADME 筛选 (FR: OB/DL)。

口径 (config/pipeline.yaml -> adme):
  mode=tcmsp  : 用 data/raw/tcmsp/ 下的 OB/DL 表 (按 InChIKey 优先, 退化按名称) 连接并筛选 OB>=ob_min & DL>=dl_min
  mode=proxy  : 无 TCMSP 数据时, 用 RDKit 代理指标 (QED 作 DL 代理, Lipinski 违反数) 筛选;
                明确标注 source=rdkit_proxy, 不冒充 TCMSP 的 OB/DL 数值。
  mode=auto   : 有 TCMSP 表则 tcmsp, 否则 proxy。
  mode=off    : 不筛选。
"""
from __future__ import annotations

import glob
import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Optional

from .config import Config


@dataclass
class AdmeResult:
    cid: str
    ob: Optional[float]          # TCMSP 口服生物利用度 (%); proxy 模式为 None
    dl: Optional[float]          # TCMSP 成药性; proxy 模式为 None
    qed: Optional[float] = None  # RDKit QED (proxy 模式)
    lipinski_violations: Optional[int] = None
    source: str = ""             # tcmsp / rdkit_proxy / none
    passed: bool = True
    reason: str = ""


def _load_tcmsp_table(tcmsp_dir: str) -> dict:
    """读取 TCMSP OB/DL 表, 建立 inchikey->{ob,dl} 与 name->{ob,dl} 索引。

    支持 csv/xlsx。列名大小写不敏感, 识别 OB / DL / InChIKey / molecule_name(或 mol_name)。
    """
    import pandas as pd

    idx = {"by_inchikey": {}, "by_name": {}}
    if not os.path.isdir(tcmsp_dir):
        return idx
    files = glob.glob(os.path.join(tcmsp_dir, "*.csv")) + glob.glob(os.path.join(tcmsp_dir, "*.xlsx"))
    for f in files:
        try:
            df = pd.read_csv(f) if f.endswith(".csv") else pd.read_excel(f)
        except Exception:
            continue
        cols = {c.lower().strip(): c for c in df.columns}
        ob_c = next((cols[k] for k in cols if k == "ob" or "oral" in k), None)
        dl_c = next((cols[k] for k in cols if k == "dl" or "drug-likeness" in k or "druglikeness" in k), None)
        ik_c = next((cols[k] for k in cols if "inchikey" in k), None)
        nm_c = next((cols[k] for k in cols if "molecule" in k and "name" in k or k in ("mol_name", "name")), None)
        if ob_c is None or dl_c is None:
            continue
        for _, row in df.iterrows():
            try:
                rec = {"ob": float(row[ob_c]), "dl": float(row[dl_c])}
            except (ValueError, TypeError):
                continue
            if ik_c and isinstance(row[ik_c], str):
                idx["by_inchikey"][row[ik_c].strip()] = rec
            if nm_c and isinstance(row[nm_c], str):
                idx["by_name"][row[nm_c].strip().lower()] = rec
    return idx


class AdmeFilter:
    def __init__(self, cfg: Config, live_index: Optional[dict] = None):
        """live_index: 形如 {by_inchikey:{}, by_name:{}} 的实时 OB/DL 索引(如 TCMSP per-herb 抓取)。
        提供时强制 tcmsp 口径并使用该索引, 忽略静态表。"""
        self.cfg = cfg
        self.a = cfg.adme
        self.mode = self.a.get("mode", "auto")
        self._tcmsp = None
        if live_index is not None:
            self.mode = "tcmsp"
            self._tcmsp = {"by_inchikey": live_index.get("by_inchikey", {}),
                           "by_name": live_index.get("by_name", {})}
            return
        if self.mode in ("tcmsp", "auto"):
            self._tcmsp = _load_tcmsp_table(cfg.path("tcmsp_dir"))
            has_data = bool(self._tcmsp["by_inchikey"] or self._tcmsp["by_name"])
            if self.mode == "auto":
                self.mode = "tcmsp" if has_data else "proxy"
            elif not has_data:
                raise RuntimeError("adme.mode=tcmsp 但 data/raw/tcmsp/ 下无可用 OB/DL 表")

    @property
    def effective_mode(self) -> str:
        return self.mode

    def evaluate(self, cid: str, smiles: Optional[str], name: Optional[str],
                 inchikey: Optional[str]) -> AdmeResult:
        if self.mode == "off":
            return AdmeResult(cid=cid, ob=None, dl=None, source="none", passed=True, reason="筛选关闭")
        if self.mode == "tcmsp":
            return self._eval_tcmsp(cid, name, inchikey)
        return self._eval_proxy(cid, smiles)

    def _eval_tcmsp(self, cid, name, inchikey) -> AdmeResult:
        rec = None
        if inchikey:
            rec = self._tcmsp["by_inchikey"].get(inchikey)
        if rec is None and name:
            rec = self._tcmsp["by_name"].get(name.strip().lower())
        if rec is None:
            return AdmeResult(cid=cid, ob=None, dl=None, source="tcmsp",
                              passed=False, reason="TCMSP 表中无 OB/DL 记录")
        ob_min = float(self.a["ob_min"])
        dl_min = float(self.a["dl_min"])
        passed = rec["ob"] >= ob_min and rec["dl"] >= dl_min
        return AdmeResult(cid=cid, ob=rec["ob"], dl=rec["dl"], source="tcmsp", passed=passed,
                          reason=f"OB={rec['ob']:.1f} DL={rec['dl']:.3f} (阈值 OB>={ob_min}, DL>={dl_min})")

    def _eval_proxy(self, cid, smiles) -> AdmeResult:
        from rdkit import Chem
        from rdkit.Chem import QED, Descriptors, Lipinski

        if not smiles:
            return AdmeResult(cid=cid, ob=None, dl=None, source="rdkit_proxy",
                              passed=False, reason="无 SMILES, 无法计算代理指标")
        mol = Chem.MolFromSmiles(smiles)
        if mol is None:
            return AdmeResult(cid=cid, ob=None, dl=None, source="rdkit_proxy",
                              passed=False, reason="SMILES 解析失败")
        qed = float(QED.qed(mol))
        violations = 0
        if Descriptors.MolWt(mol) > 500: violations += 1
        if Descriptors.MolLogP(mol) > 5: violations += 1
        if Lipinski.NumHDonors(mol) > 5: violations += 1
        if Lipinski.NumHAcceptors(mol) > 10: violations += 1
        qed_min = float(self.a["proxy"]["qed_min"])
        max_viol = int(self.a["proxy"]["lipinski_max_violations"])
        passed = qed >= qed_min and violations <= max_viol
        return AdmeResult(cid=cid, ob=None, dl=None, qed=qed, lipinski_violations=violations,
                          source="rdkit_proxy", passed=passed,
                          reason=f"QED={qed:.3f} (>= {qed_min}), Lipinski违反={violations} (<= {max_viol})")
