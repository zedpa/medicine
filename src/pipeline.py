"""端到端管道编排: 药材 -> 成分 -> ADME 筛选 -> 靶点 -> 基因/蛋白归一化 -> 结构化结果。

每条靶点关系带 provenance (来源库 + 证据等级 + 分数)。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

from . import batman
from .adme import AdmeFilter
from .cache import Cache
from .config import load_config
from .online import OnlineClients
from .tcmsp import TcmspClient

SOURCE_DB = "BATMAN-TCM 2.0"


@dataclass
class PipelineResult:
    query: str
    found: bool
    herb: dict = field(default_factory=dict)
    config_snapshot: dict = field(default_factory=dict)
    compounds: list[dict] = field(default_factory=list)        # 成分表(含 ADME)
    compound_targets: list[dict] = field(default_factory=list) # 成分-靶点 long
    proteins: list[dict] = field(default_factory=list)         # 靶点蛋白信息表
    stats: dict = field(default_factory=dict)
    message: str = ""


def _progress(cb: Optional[Callable[[str], None]], msg: str) -> None:
    if cb:
        cb(msg)


def run_herb(query: str, progress: Optional[Callable[[str], None]] = None) -> PipelineResult:
    cfg = load_config()
    db = batman.get_db()
    cache = Cache(cfg.path("cache_db"))
    online = OnlineClients(cfg, cache)

    _progress(progress, f"① 解析药材名: {query}")
    match = db.resolve_herb(query)
    if not match.found:
        return PipelineResult(query=query, found=False,
                              message=f"未在 BATMAN-TCM 2.0 (8404 味) 中找到药材「{query}」。"
                                      f"可尝试中文名/拼音/拉丁学名。")

    # ADME 过滤器: tcmsp_live 模式下实时抓取该药材的 TCMSP OB/DL, 按 InChIKey 连接
    adme = _build_adme(cfg, match, online, progress)

    result = PipelineResult(query=query, found=True)
    result.herb = {"latin": match.latin, "chinese": match.chinese,
                   "pinyin": match.pinyin, "english": match.english,
                   "match_type": match.match_type, "source_db": SOURCE_DB}
    result.config_snapshot = {
        "adme_mode": getattr(adme, "label", adme.effective_mode),
        "ob_min": cfg.adme.get("ob_min"), "dl_min": cfg.adme.get("dl_min"),
        "qed_min": cfg.adme.get("proxy", {}).get("qed_min"),
        "predicted_score_min": cfg.targets.get("predicted_score_min"),
        "use_known": cfg.targets.get("use_known"), "use_predicted": cfg.targets.get("use_predicted"),
        "taxon_id": cfg.taxon_id,
    }

    n_total = len(match.ingredients)
    _progress(progress, f"② 成分归一化 + ADME 筛选 ({n_total} 个成分)")
    score_min = float(cfg.targets["predicted_score_min"])
    use_known = bool(cfg.targets["use_known"])
    use_pred = bool(cfg.targets["use_predicted"])

    passed_compounds: list[dict] = []
    predicted_entrez: set[str] = set()  # 收集需映射的 Entrez ID

    for i, ing in enumerate(match.ingredients, 1):
        if i % 25 == 0:
            _progress(progress, f"   ...成分 {i}/{n_total}")
        pc = online.pubchem_by_cid(ing.cid)
        ad = adme.evaluate(ing.cid, pc["smiles"], pc["name"] or ing.name, pc["inchikey"])
        row = {
            "cid": ing.cid,
            "name": pc["name"] or ing.name,
            "batman_name": ing.name,
            "smiles": pc["smiles"],
            "inchikey": pc["inchikey"],
            "adme_source": ad.source,
            "ob": ad.ob, "dl": ad.dl, "qed": ad.qed,
            "lipinski_violations": ad.lipinski_violations,
            "adme_passed": ad.passed, "adme_reason": ad.reason,
        }
        result.compounds.append(row)
        if ad.passed:
            passed_compounds.append(row)
            if use_pred:
                for eid, sc in db.predicted_targets(ing.cid):
                    if sc >= score_min:
                        predicted_entrez.add(eid)

    _progress(progress, f"③ 靶点映射: {len(predicted_entrez)} 个预测 Entrez ID -> gene symbol")
    entrez_map = online.entrez_to_symbol(sorted(predicted_entrez)) if predicted_entrez else {}

    _progress(progress, "④ 汇总成分-靶点关系 (已知 + 预测)")
    gene_set: set[str] = set()
    # (cid, gene) 去重, 聚合证据
    seen_pair: dict[tuple[str, str], dict] = {}
    for row in passed_compounds:
        cid = row["cid"]
        if use_known:
            for sym in db.known_targets(cid):
                _add_pair(seen_pair, cid, row["name"], sym, "known", None)
                gene_set.add(sym)
        if use_pred:
            for eid, sc in db.predicted_targets(cid):
                if sc < score_min:
                    continue
                sym = entrez_map.get(eid)
                if not sym:
                    continue
                _add_pair(seen_pair, cid, row["name"], sym, "predicted", sc)
                gene_set.add(sym)
    result.compound_targets = list(seen_pair.values())

    _progress(progress, f"⑤ 靶点蛋白信息 (UniProt): {len(gene_set)} 个基因")
    for j, sym in enumerate(sorted(gene_set), 1):
        if j % 25 == 0:
            _progress(progress, f"   ...UniProt {j}/{len(gene_set)}")
        up = online.uniprot_by_symbol(sym)
        result.proteins.append(up)

    result.stats = {
        "ingredients_total": n_total,
        "compounds_passed_adme": len(passed_compounds),
        "compound_target_pairs": len(result.compound_targets),
        "unique_targets": len(gene_set),
        "targets_with_uniprot": sum(1 for p in result.proteins if p.get("accession")),
    }
    result.message = (f"{result.herb['chinese'] or result.herb['latin']}: "
                      f"成分 {n_total} → 通过ADME {len(passed_compounds)} → "
                      f"靶点 {len(gene_set)} 个 (关系 {len(result.compound_targets)} 条)")
    _progress(progress, "✓ 完成")
    return result


def _build_adme(cfg, match, online, progress) -> AdmeFilter:
    """按 config 构造 ADME 过滤器。tcmsp_live: 实时抓 TCMSP 该药材 OB/DL, 按 InChIKey 连接。"""
    mode = cfg.adme.get("mode", "auto")
    if mode != "tcmsp_live":
        adme = AdmeFilter(cfg)
        adme.label = adme.effective_mode
        return adme
    _progress(progress, "②a 实时抓取 TCMSP OB/DL (模拟人工浏览, 仅本药材)")
    cache = Cache(cfg.path("cache_db"))
    client = TcmspClient(cache, timeout=cfg.services.get("request_timeout", 30))
    # 用中文名优先查询 TCMSP
    q = match.chinese or match.pinyin or match.latin or match.query
    idx = client.fetch_herb_adme(q, online=online)
    if idx.get("found"):
        _progress(progress, f"   TCMSP 命中 {idx['n']} 个分子 (en={idx['en_name']}), "
                            f"InChIKey 解析 {len(idx['by_inchikey'])} 个")
        adme = AdmeFilter(cfg, live_index=idx)
        adme.label = f"tcmsp_live(n={idx['n']})"
        return adme
    _progress(progress, "   TCMSP 未命中, 回退 RDKit 代理")
    adme = AdmeFilter(cfg)       # mode=tcmsp_live 不触发静态表加载
    adme.mode = "proxy"          # 强制代理回退
    adme.label = "rdkit_proxy(tcmsp_miss)"
    return adme


def _add_pair(store: dict, cid: str, cname: str, sym: str, evidence: str, score):
    key = (cid, sym)
    if key not in store:
        store[key] = {"cid": cid, "compound_name": cname, "gene_symbol": sym,
                      "evidence": evidence, "max_score": score, "source_db": SOURCE_DB}
    else:
        rec = store[key]
        # 已知证据优先级高于预测
        if evidence == "known":
            rec["evidence"] = "known"
        if score is not None and (rec["max_score"] is None or score > rec["max_score"]):
            rec["max_score"] = score
