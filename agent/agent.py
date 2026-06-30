"""对话式 agent: 把网络药理学管道暴露为一个工具, 由 LLM 决定调用。

后端按环境变量自动选择(优先级从上到下):
  - DEEPSEEK_API_KEY  -> DeepSeek (OpenAI 兼容, model=deepseek-chat)
  - OPENAI_API_KEY    -> OpenAI 兼容端点 (base 可用 OPENAI_BASE_URL 覆盖)
  - ANTHROPIC_API_KEY -> Claude (claude-opus-4-8)
  - 都没有            -> 直接模式(输入即药材名)

工具 analyze_herbs(herbs): 对每味药材跑完整管道, 导出 Excel, 返回简要统计。
"""
from __future__ import annotations

import json
import os
import re
from typing import Callable, Optional

from src.excel_export import export
from src.pipeline import PipelineResult, run_herb

CLAUDE_MODEL = "claude-opus-4-8"

TOOL_NAME = "analyze_herbs"
TOOL_DESC = (
    "对一味或多味中药跑网络药理学管道: 药材→成分→ADME筛选→靶点→UniProt蛋白信息, "
    "并导出多 sheet Excel。当用户提到任意中药名(中文/拼音/拉丁名)并希望查询其成分/靶点/蛋白时调用。"
)
TOOL_PARAMS = {
    "type": "object",
    "properties": {
        "herbs": {
            "type": "array",
            "items": {"type": "string"},
            "description": "药材名列表, 如 ['肉桂'] 或 ['黄芪','当归']。支持中文名/拼音/拉丁学名。",
        },
        "disease": {
            "type": "string",
            "description": "可选。疾病名(中/英), 如 '高血压'。提供时额外做疾病靶点 + 药物×疾病交集。",
        },
    },
    "required": ["herbs"],
}

SYSTEM = (
    "你是中药网络药理学助手。用户给出中药名时, 调用 analyze_herbs 工具跑管道并拿到结果, "
    "然后用中文简明汇报: 药材匹配情况、通过 ADME 的成分数、去重靶点数、几个代表性靶点基因, "
    "并提示完整结果已导出为 Excel(含 SMILES/InChIKey/UniProt 信息)。"
    "若用户同时提到某疾病, 把疾病名放进 disease 参数, 并汇报疾病靶点数与交集靶点(潜在作用靶点), "
    "以及 PPI 网络的 hub 核心靶点、GO/KEGG 富集的代表性通路。"
    "不要编造数据库里没有的靶点或通路。"
)


def _safe(name: str) -> str:
    return re.sub(r"[^\w\-]+", "_", name).strip("_") or "herb"


def run_pipeline_for(query: str, on_progress: Optional[Callable[[str], None]] = None,
                     disease: Optional[str] = None
                     ) -> tuple[PipelineResult, Optional[str]]:
    result = run_herb(query, progress=on_progress, disease=disease)
    excel_path = None
    if result.found:
        excel_path = export(result, f"outputs/{_safe(result.herb.get('pinyin') or query)}.xlsx")
    return result, excel_path


def _tool_summary(result: PipelineResult, excel_path: Optional[str]) -> dict:
    if not result.found:
        return {"query": result.query, "found": False, "message": result.message}
    known = [t["gene_symbol"] for t in result.compound_targets if t["evidence"] == "known"]
    sample = sorted(set(known))[:15] or sorted({t["gene_symbol"] for t in result.compound_targets})[:15]
    out = {
        "query": result.query, "found": True,
        "herb": {"chinese": result.herb.get("chinese"), "latin": result.herb.get("latin")},
        "adme_mode": result.config_snapshot.get("adme_mode"),
        "stats": result.stats, "sample_targets": sample, "excel_path": excel_path,
    }
    if result.intersection is not None:
        out["disease"] = {
            "query": result.disease.get("query"), "found": result.disease.get("found"),
            "n_disease_targets": result.disease.get("n"),
            "intersection": result.intersection["intersection"][:30],
            "n_intersection": result.intersection["counts"]["intersection"],
        }
    if result.ppi is not None:
        out["ppi"] = {
            "basis": result.ppi.get("basis"),
            "n_nodes": result.ppi.get("n_nodes"), "n_edges": result.ppi.get("n_edges"),
            "hub_genes": [h["gene"] for h in result.ppi.get("hubs", [])[:10]],
        }
    if result.enrichment is not None:
        out["enrichment"] = {
            lib: [r["term"] for r in rows[:8]]
            for lib, rows in result.enrichment.items()
        }
    return out


def _execute_tool(args: dict, on_result, on_progress) -> str:
    """执行 analyze_herbs, 返回 JSON 字符串(给 LLM 看)。"""
    herbs = args.get("herbs", []) if isinstance(args, dict) else []
    disease = args.get("disease") if isinstance(args, dict) else None
    summaries = []
    for h in herbs:
        result, path = run_pipeline_for(h, on_progress, disease=disease)
        if on_result:
            on_result(result, path)
        summaries.append(_tool_summary(result, path))
    return json.dumps(summaries, ensure_ascii=False)


def respond(history: list[dict],
            on_result: Optional[Callable[[PipelineResult, Optional[str]], None]] = None,
            on_progress: Optional[Callable[[str], None]] = None) -> str:
    """给定对话历史(role/content), 返回助手回复文本。结果通过 on_result 回调上报。"""
    if os.environ.get("DEEPSEEK_API_KEY"):
        return _respond_openai_compat(
            history, on_result, on_progress,
            api_key=os.environ["DEEPSEEK_API_KEY"],
            base_url=os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
            model=os.environ.get("DEEPSEEK_MODEL", "deepseek-chat"))
    if os.environ.get("OPENAI_API_KEY"):
        return _respond_openai_compat(
            history, on_result, on_progress,
            api_key=os.environ["OPENAI_API_KEY"],
            base_url=os.environ.get("OPENAI_BASE_URL"),
            model=os.environ.get("OPENAI_MODEL", "gpt-4o-mini"))
    try:
        import anthropic  # noqa
        if os.environ.get("ANTHROPIC_API_KEY"):
            return _respond_claude(history, on_result, on_progress)
    except ImportError:
        pass
    return _direct_mode(history, on_result, on_progress)


# ---------------- OpenAI 兼容后端 (DeepSeek 等) ----------------
def _respond_openai_compat(history, on_result, on_progress, *, api_key, base_url, model) -> str:
    from openai import OpenAI

    client = OpenAI(api_key=api_key, base_url=base_url)
    tools = [{"type": "function", "function": {
        "name": TOOL_NAME, "description": TOOL_DESC, "parameters": TOOL_PARAMS}}]
    msgs = [{"role": "system", "content": SYSTEM}] + [
        {"role": m["role"], "content": m["content"]} for m in history]

    for _ in range(6):
        resp = client.chat.completions.create(
            model=model, messages=msgs, tools=tools, tool_choice="auto", max_tokens=4096)
        m = resp.choices[0].message
        if not m.tool_calls:
            return (m.content or "").strip()
        msgs.append({"role": "assistant", "content": m.content or "",
                     "tool_calls": [{"id": tc.id, "type": "function",
                                     "function": {"name": tc.function.name,
                                                  "arguments": tc.function.arguments}}
                                    for tc in m.tool_calls]})
        for tc in m.tool_calls:
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            content = _execute_tool(args, on_result, on_progress)
            msgs.append({"role": "tool", "tool_call_id": tc.id, "content": content})
    return "(达到工具调用上限, 请重试)"


# ---------------- Anthropic 后端 ----------------
def _respond_claude(history, on_result, on_progress) -> str:
    import anthropic

    client = anthropic.Anthropic()
    tool = {"name": TOOL_NAME, "description": TOOL_DESC, "input_schema": TOOL_PARAMS}
    messages = [{"role": m["role"], "content": m["content"]} for m in history]
    for _ in range(6):
        resp = client.messages.create(
            model=CLAUDE_MODEL, max_tokens=4096, thinking={"type": "adaptive"},
            system=SYSTEM, tools=[tool], messages=messages)
        if resp.stop_reason != "tool_use":
            return "".join(b.text for b in resp.content if b.type == "text").strip()
        messages.append({"role": "assistant", "content": resp.content})
        results = []
        for block in resp.content:
            if block.type != "tool_use":
                continue
            content = _execute_tool(block.input, on_result, on_progress)
            results.append({"type": "tool_result", "tool_use_id": block.id, "content": content})
        messages.append({"role": "user", "content": results})
    return "(达到工具调用上限, 请重试)"


# ---------------- 无 LLM: 直接模式 ----------------
def _direct_mode(history, on_result, on_progress) -> str:
    user_text = ""
    for m in reversed(history):
        if m["role"] == "user":
            user_text = m["content"] if isinstance(m["content"], str) else ""
            break
    herbs = [h for h in re.split(r"[,，、;\s]+", user_text.strip()) if h]
    if not herbs:
        return "请输入药材名(中文/拼音/拉丁学名), 可用逗号分隔多味。"
    lines = ["(直接模式 · 未配置 LLM API Key)"]
    for h in herbs:
        result, path = run_pipeline_for(h, on_progress)
        if on_result:
            on_result(result, path)
        lines.append(f"✓ {result.message}  →  {path}" if result.found else f"✗ {result.message}")
    return "\n".join(lines)
