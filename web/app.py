"""网页前端: 对话式中药网络药理学助手 (Streamlit)。

运行: .venv/bin/streamlit run web/app.py
输入框输入任意药材名(中文/拼音/拉丁, 支持批量), agent 自动跑管道, 展示表格并提供 Excel 下载。
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import streamlit as st

from agent.agent import respond

st.set_page_config(page_title="中药网络药理学助手", page_icon="🌿", layout="wide")
st.title("🌿 中药网络药理学一站式助手")
st.caption("数据来源: BATMAN-TCM 2.0 + PubChem + UniProt · 输入任意药材名(支持批量), 自动产出成分→靶点→蛋白 + Excel")

if "messages" not in st.session_state:
    st.session_state.messages = []
if "results" not in st.session_state:
    st.session_state.results = []  # (PipelineResult, excel_path)

with st.sidebar:
    st.subheader("状态")
    if os.environ.get("DEEPSEEK_API_KEY"):
        _backend = "DeepSeek (deepseek-chat)"
    elif os.environ.get("OPENAI_API_KEY"):
        _backend = "OpenAI 兼容"
    elif os.environ.get("ANTHROPIC_API_KEY"):
        _backend = "Claude (claude-opus-4-8)"
    else:
        _backend = "直接模式(无 LLM, 输入即药材名)"
    st.write("LLM 后端:", _backend)
    st.markdown("**示例**: `肉桂` / `黄芪, 当归` / `Cinnamomum cassia`")
    if st.button("清空对话"):
        st.session_state.messages = []
        st.session_state.results = []
        st.rerun()


def render_result(result, excel_path):
    herb = result.herb
    if not result.found:
        st.warning(result.message)
        return
    st.markdown(f"### {herb.get('chinese') or herb.get('latin')}  "
                f"<span style='color:gray'>({herb.get('latin')})</span>", unsafe_allow_html=True)
    s = result.stats
    c = st.columns(4)
    c[0].metric("成分总数", s.get("ingredients_total", 0))
    c[1].metric("通过 ADME", s.get("compounds_passed_adme", 0))
    c[2].metric("去重靶点", s.get("unique_targets", 0))
    c[3].metric("UniProt 命中", s.get("targets_with_uniprot", 0))
    st.caption(f"ADME 模式: {result.config_snapshot.get('adme_mode')} · "
               f"OB≥{result.config_snapshot.get('ob_min')} DL≥{result.config_snapshot.get('dl_min')} · "
               f"预测分数≥{result.config_snapshot.get('predicted_score_min')}")

    tabs = st.tabs(["成分表", "成分-靶点", "靶点蛋白(UniProt)"])
    with tabs[0]:
        st.dataframe(pd.DataFrame(result.compounds), use_container_width=True, height=300)
    with tabs[1]:
        st.dataframe(pd.DataFrame(result.compound_targets), use_container_width=True, height=300)
    with tabs[2]:
        st.dataframe(pd.DataFrame(result.proteins), use_container_width=True, height=300)

    if excel_path and os.path.exists(excel_path):
        with open(excel_path, "rb") as fh:
            st.download_button("⬇️ 下载完整 Excel", fh.read(),
                               file_name=os.path.basename(excel_path),
                               mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                               key=f"dl_{excel_path}_{s.get('unique_targets')}")


# 历史消息
for m in st.session_state.messages:
    with st.chat_message(m["role"]):
        st.markdown(m["content"])

# 已产出的结果面板
if st.session_state.results:
    st.divider()
    st.subheader("📊 分析结果")
    for result, path in st.session_state.results:
        render_result(result, path)

if prompt := st.chat_input("输入药材名, 例如: 肉桂"):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        status = st.status("正在跑管道…", expanded=True)
        new_results = []

        def on_progress(msg):
            status.write(msg)

        def on_result(result, path):
            new_results.append((result, path))

        reply = respond(st.session_state.messages, on_result=on_result, on_progress=on_progress)
        status.update(label="完成", state="complete", expanded=False)
        st.markdown(reply)

    st.session_state.messages.append({"role": "assistant", "content": reply})
    st.session_state.results.extend(new_results)
    st.rerun()
