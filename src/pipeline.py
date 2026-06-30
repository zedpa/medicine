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
from .disease import DiseaseClient
from .enrichment import EnrichrClient
from .intersect import intersect_targets
from .online import OnlineClients
from .ppi import StringClient, hub_genes
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
    disease: Optional[dict] = None         # T1: 疾病靶点(提供 disease 时)
    intersection: Optional[dict] = None    # T1: 药物×疾病 交集(韦恩就绪)
    ppi: Optional[dict] = None             # T3: STRING PPI 网络(nodes/edges/hubs)
    enrichment: Optional[dict] = None      # T4: GO/KEGG 富集(按库分组)
    stats: dict = field(default_factory=dict)
    message: str = ""


# ---------------- 结果快照(spec-003 T3): 会话历史重显结果面板 ----------------
# PipelineResult 全字段为 dict/list/str/bool, 本就 JSON 可序列化; 快照只做字段选取 + JSON 往返,
# 图表由 viz 从这些 dict 现场重渲(不持久化 PNG)。
_SNAPSHOT_FIELDS = (
    "query", "found", "herb", "config_snapshot", "compounds", "compound_targets",
    "proteins", "disease", "intersection", "ppi", "enrichment", "stats", "message",
)


def result_to_snapshot(result: "PipelineResult", excel_path: Optional[str] = None) -> dict:
    """抽取渲染所需字段 + excel_path, 产出 JSON 可序列化的快照。"""
    return {"result": {f: getattr(result, f) for f in _SNAPSHOT_FIELDS},
            "excel_path": excel_path}


def snapshot_to_result(snap: dict):
    """从快照重建 (PipelineResult, excel_path)；与原对象字段相等(往返无损)。"""
    data = {f: snap["result"][f] for f in _SNAPSHOT_FIELDS if f in snap["result"]}
    return PipelineResult(**data), snap.get("excel_path")


def _progress(cb: Optional[Callable[[str], None]], msg: str) -> None:
    if cb:
        cb(msg)


def run_herb(query: str, progress: Optional[Callable[[str], None]] = None,
             disease: Optional[str] = None) -> PipelineResult:
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

    # ⑥ 疾病靶点 + 交集 (T1, 仅当提供 disease)
    _attach_disease(result, gene_set, cfg, cache, disease, progress)

    # ⑦ PPI 蛋白互作网络 (T3, 优先用交集靶点)
    _attach_ppi(result, gene_set, cfg, cache, progress)

    # ⑧ GO/KEGG 富集分析 (T4, 优先用交集靶点)
    _attach_enrichment(result, gene_set, cfg, cache, progress)

    result.stats = {
        "ingredients_total": n_total,
        "compounds_passed_adme": len(passed_compounds),
        "compound_target_pairs": len(result.compound_targets),
        "unique_targets": len(gene_set),
        "targets_with_uniprot": sum(1 for p in result.proteins if p.get("accession")),
    }
    if result.intersection is not None:
        result.stats["disease_targets"] = result.disease.get("n", 0)
        result.stats["intersection_targets"] = result.intersection["counts"]["intersection"]
    if result.ppi is not None:
        result.stats["ppi_nodes"] = result.ppi["n_nodes"]
        result.stats["ppi_edges"] = result.ppi["n_edges"]
    if result.enrichment is not None:
        result.stats["enrichment_terms"] = sum(len(v) for v in result.enrichment.values())
    result.message = (f"{result.herb['chinese'] or result.herb['latin']}: "
                      f"成分 {n_total} → 通过ADME {len(passed_compounds)} → "
                      f"靶点 {len(gene_set)} 个 (关系 {len(result.compound_targets)} 条)")
    if result.intersection is not None:
        result.message += (f"；疾病「{result.disease.get('query')}」靶点 "
                           f"{result.disease.get('n', 0)} 个 → 交集 "
                           f"{result.intersection['counts']['intersection']} 个")
    _progress(progress, "✓ 完成")
    return result


def _attach_disease(result: PipelineResult, gene_set, cfg, cache, disease, progress) -> None:
    """T1: 提供 disease 时, 拉疾病靶点并与药物靶点取交集, 挂到 result。

    disease=None -> result.disease / result.intersection 保持 None (向后兼容)。
    无命中 -> disease.found=False, 交集对空疾病集计算 (仍给出 counts)。
    """
    if not disease:
        result.disease = None
        result.intersection = None
        return
    _progress(progress, f"⑥ 疾病靶点 + 交集: {disease}")
    client = DiseaseClient(cfg, cache)
    dz = client.disease_targets(disease)
    result.disease = dz
    disease_genes = {g["symbol"] for g in dz.get("genes", [])}
    result.intersection = intersect_targets(set(gene_set), disease_genes)
    if dz.get("found"):
        _progress(progress, f"   疾病「{disease}」(EFO {dz.get('efo_id')}) 靶点 {dz['n']} 个, "
                            f"交集 {result.intersection['counts']['intersection']} 个")
    else:
        _progress(progress, f"   未在 Open Targets 命中疾病「{disease}」")


def _pick_genes(result: PipelineResult, gene_set):
    """下游分析(PPI/富集)的靶点选取: 药物×疾病交集非空时优先, 否则全部药物靶点。"""
    inter = getattr(result, "intersection", None)
    if inter and inter.get("intersection"):
        return list(inter["intersection"]), "交集靶点"
    return sorted(gene_set), "全部药物靶点"


def _attach_ppi(result: PipelineResult, gene_set, cfg, cache, progress) -> None:
    """T3: 构建 STRING PPI 网络并挂到 result。

    靶点优先用 药物×疾病 交集(非空时), 否则用全部药物靶点; <2 基因或 disabled 时跳过。
    """
    pcfg = cfg.raw.get("ppi", {})
    if not pcfg.get("enabled", True):
        result.ppi = None
        return
    genes, basis = _pick_genes(result, gene_set)
    if len(genes) < 2:
        result.ppi = None
        return
    _progress(progress, f"⑦ STRING PPI 网络 ({basis}, {len(genes)} 个基因)")
    client = StringClient(cfg, cache)
    net = client.network(genes)
    net["hubs"] = hub_genes(net["edges"])
    net["basis"] = basis
    result.ppi = net
    top = ", ".join(f"{h['gene']}({h['degree']})" for h in net["hubs"][:5])
    _progress(progress, f"   节点 {net['n_nodes']} / 边 {net['n_edges']}; hub: {top}")


def _attach_enrichment(result: PipelineResult, gene_set, cfg, cache, progress) -> None:
    """T4: GO/KEGG 富集分析并挂到 result(按库分组)。

    靶点优先用 药物×疾病 交集(非空时), 否则用全部药物靶点; <3 基因或 disabled 时跳过。
    """
    ecfg = cfg.raw.get("enrichment", {})
    if not ecfg.get("enabled", True):
        result.enrichment = None
        return
    genes, basis = _pick_genes(result, gene_set)
    if len(genes) < 3:
        result.enrichment = None
        return
    libraries = ecfg.get("libraries", [])
    _progress(progress, f"⑧ GO/KEGG 富集 ({basis}, {len(genes)} 个基因, {len(libraries)} 个库)")
    client = EnrichrClient(cfg, cache)
    grouped: dict = {}
    for lib in libraries:
        rows = client.enrich(genes, lib)
        grouped[lib] = rows
        if rows:
            _progress(progress, f"   {lib}: {len(rows)} 条显著; top: {rows[0]['term']}")
        else:
            _progress(progress, f"   {lib}: 无显著富集项")
    result.enrichment = grouped


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
