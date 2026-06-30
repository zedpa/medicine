"""网页前端: 对话式中药网络药理学助手 (Streamlit)。

运行: .venv/bin/streamlit run web/app.py
输入框输入任意药材名(中文/拼音/拉丁, 支持批量), agent 自动跑管道, 展示表格并提供 Excel 下载。
"""
from __future__ import annotations

import datetime
import os
import secrets
import sys
import uuid

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import pandas as pd
import streamlit as st
import streamlit_authenticator as stauth

from agent.agent import respond
from src.config import load_config
from src.auth import UserStore
from src.history import HistoryStore, _derive_title
from src.pipeline import result_to_snapshot, snapshot_to_result
from src.viz import venn_png, bubble_png, network_png


@st.cache_resource
def _history():
    """历史存储 + 配置。db_path 可被环境变量 HISTORY_DB_PATH 覆盖(供 E2E 隔离)。"""
    hcfg = load_config().raw.get("history", {}) or {}
    db = os.environ.get("HISTORY_DB_PATH") or hcfg.get("db_path", "data/history.sqlite")
    if not os.path.isabs(db):
        db = os.path.join(ROOT, db)
    return HistoryStore(db), hcfg


def _now_iso():
    # 时间由 UI 层生成后注入存储层(存储层保持纯净, 见 spec-003 §3)
    return datetime.datetime.now().isoformat(timespec="seconds")


@st.cache_resource
def _auth_setup():
    """账号库 + 认证配置 + Cookie key(spec-004 T3)。

    db_path 可被 AUTH_DB_PATH 覆盖(供 E2E 隔离)。空库且配了 ADMIN_USER/ADMIN_PASSWORD
    时种入一个 admin。Cookie key 取 AUTH_COOKIE_KEY; 缺失则随机生成(重启失效, 仅开发兜底)。
    """
    acfg = load_config().raw.get("auth", {}) or {}
    db = os.environ.get("AUTH_DB_PATH") or acfg.get("db_path", "data/auth.sqlite")
    if not os.path.isabs(db):
        db = os.path.join(ROOT, db)
    store = UserStore(db)
    admin_u, admin_p = os.environ.get("ADMIN_USER"), os.environ.get("ADMIN_PASSWORD")
    if store.count() == 0 and admin_u and admin_p:
        store.upsert({"username": admin_u, "name": admin_u, "email": "",
                      "password_hash": stauth.Hasher.hash(admin_p),
                      "role": "admin", "created_at": _now_iso()})
    cookie_key = os.environ.get("AUTH_COOKIE_KEY")
    key_warning = not cookie_key
    return store, acfg, (cookie_key or secrets.token_hex(16)), key_warning


def _save_current():
    """把当前会话落库(空会话跳过); 标题取首条用户消息, 并按上限裁剪。"""
    msgs = st.session_state.messages
    if not msgs:
        return
    store, hcfg = _history()
    owner = st.session_state.owner
    cid = st.session_state.conv_id
    prev = store.get(cid, owner)
    snaps = [result_to_snapshot(r, path) for r, path in st.session_state.results]
    store.save({
        "id": cid,
        "owner": owner,              # spec-004: 会话归属当前登录用户
        "title": _derive_title(msgs, int(hcfg.get("title_max_len", 24))),
        "created_at": prev["created_at"] if prev else _now_iso(),
        "updated_at": _now_iso(),
        "messages": msgs,
        "results": snaps,            # T3: 结果快照随会话落库, 切回时重显面板
    })
    store.prune(owner, int(hcfg.get("max_conversations", 50)))

st.set_page_config(page_title="中药网络药理学助手", page_icon="🌿", layout="wide")
st.title("🌿 中药网络药理学一站式助手")
st.caption("数据来源: BATMAN-TCM 2.0 + PubChem + UniProt · 输入任意药材名(支持批量), 自动产出成分→靶点→蛋白 + Excel")

if "messages" not in st.session_state:
    st.session_state.messages = []
if "results" not in st.session_state:
    st.session_state.results = []  # (PipelineResult, excel_path)
if "conv_id" not in st.session_state:
    st.session_state.conv_id = uuid.uuid4().hex

# ---- 账号授权门 (spec-004 T3): 未登录只渲染登录/注册, 主应用一律 st.stop ----
_ustore, _acfg, _cookie_key, _key_warn = _auth_setup()
if _acfg.get("enabled", True):
    _authr = stauth.Authenticate(
        _ustore.credentials(), _acfg.get("cookie_name", "tcm_auth"),
        _cookie_key, float(_acfg.get("cookie_expiry_days", 7)))
    _authr.login(location="main", captcha=False,
                 fields={"Form name": "登录", "Username": "用户名",
                         "Password": "密码", "Login": "登录"})
    if st.session_state.get("authentication_status") is not True:
        if st.session_state.get("authentication_status") is False:
            st.error("用户名或密码错误")
        if _key_warn:
            st.caption("⚠️ 未设置 AUTH_COOKIE_KEY，登录态重启即失效（仅开发兜底）")
        if _acfg.get("allow_self_register", True):
            with st.expander("还没有账号？注册新账号", expanded=False):
                try:
                    _email, _uname, _name = _authr.register_user(
                        location="main", captcha=False, password_hint=False,
                        roles=[_acfg.get("default_role", "user")],
                        fields={"Form name": "注册", "Username": "用户名",
                                "Email": "邮箱", "First name": "名", "Last name": "姓",
                                "Password": "密码", "Repeat password": "确认密码",
                                "Register": "注册"})
                    if _uname:
                        _u = _authr.authentication_controller.authentication_model.\
                            credentials["usernames"][_uname]
                        # 0.4.x 凭据存 first_name/last_name(无 name 键) -> 拼全名
                        _full = (f"{_u.get('first_name', '')} {_u.get('last_name', '')}"
                                 .strip() or _u.get("name") or _uname)
                        _ustore.upsert({"username": _uname, "name": _full,
                                        "email": _u.get("email", ""),
                                        "password_hash": _u["password"],
                                        "role": (_u.get("roles") or ["user"])[0],
                                        "created_at": _now_iso()})
                        st.success("注册成功，请在上方用新账号登录")
                except Exception as _e:          # RegisterError 等 -> 友好提示
                    st.error(str(_e))
        st.stop()
    st.session_state.owner = st.session_state["username"]
    st.session_state.auth = _authr
else:
    st.session_state.owner = "default"          # 关闭认证时回退单租户
    st.session_state.auth = None

# 切换登录用户时清空内存态, 防止上一用户的对话/结果残留泄漏
if st.session_state.get("_auth_user") != st.session_state.owner:
    st.session_state._auth_user = st.session_state.owner
    st.session_state.messages = []
    st.session_state.results = []
    st.session_state.conv_id = uuid.uuid4().hex

def _new_conversation():
    _save_current()                       # 先把当前会话落库
    st.session_state.messages = []
    st.session_state.results = []
    st.session_state.conv_id = uuid.uuid4().hex


def _open_conversation(store, conv_id):
    loaded = store.get(conv_id, st.session_state.owner) or {}
    st.session_state.messages = loaded.get("messages", [])
    # T3: 从快照重建结果, 切回会话即重显表/图/下载面板
    st.session_state.results = [snapshot_to_result(s) for s in loaded.get("results", [])]
    st.session_state.conv_id = conv_id


with st.sidebar:
    st.markdown("### 🌿 中药网络药理学")
    _store, _hcfg = _history()

    # 顶部: 新建对话(Claude 风格, 醒目)
    if st.button("✚　新建对话", use_container_width=True, type="primary"):
        _new_conversation()
        st.rerun()

    st.caption("最近对话")
    _convs = _store.list(st.session_state.owner,
                         limit=int(_hcfg.get("max_conversations", 50)))
    if not _convs:
        st.caption("暂无历史，开始第一轮提问吧")

    for _c in _convs:
        _cur = _c["id"] == st.session_state.conv_id
        _title = _c["title"] or "新对话"
        _row, _menu = st.columns([6, 1], vertical_alignment="center")
        # 选中态用 primary 高亮(替代 🟢 emoji), 更接近 Claude 的当前会话样式
        if _row.button(_title, key=f"open_{_c['id']}", use_container_width=True,
                       type="primary" if _cur else "secondary"):
            _open_conversation(_store, _c["id"])
            st.rerun()
        # 管理操作收进「⋯」三点菜单(重命名 / 删除)
        with _menu.popover("⋯", use_container_width=True):
            st.caption(_title)
            _new_name = st.text_input("重命名", value=_title, key=f"rn_{_c['id']}",
                                      label_visibility="collapsed")
            if st.button("✏️ 重命名", key=f"rnbtn_{_c['id']}", use_container_width=True):
                if _new_name.strip():
                    _store.set_title(_c["id"], st.session_state.owner, _new_name.strip())
                    st.rerun()
            if st.button("🗑 删除对话", key=f"del_{_c['id']}", use_container_width=True):
                _store.delete(_c["id"], st.session_state.owner)
                if _c["id"] == st.session_state.conv_id:
                    st.session_state.messages = []
                    st.session_state.results = []
                    st.session_state.conv_id = uuid.uuid4().hex
                st.rerun()

    # 底部: 账户 + 设置/状态收进 expander, 列表更聚焦(Claude 把账户信息放底部)
    st.divider()
    if st.session_state.get("auth") is not None:
        _who, _out = st.columns([6, 3], vertical_alignment="center")
        _who.caption(f"👤 {st.session_state.get('name') or st.session_state.owner}")
        with _out:
            st.session_state.auth.logout("登出", location="main",
                                         use_container_width=True)
    if os.environ.get("DEEPSEEK_API_KEY"):
        _backend = "DeepSeek (deepseek-chat)"
    elif os.environ.get("OPENAI_API_KEY"):
        _backend = "OpenAI 兼容"
    elif os.environ.get("ANTHROPIC_API_KEY"):
        _backend = "Claude (claude-opus-4-8)"
    else:
        _backend = "直接模式(无 LLM, 输入即药材名)"
    with st.expander(f"ℹ️ {_backend}", expanded=False):
        st.markdown("**示例**: `肉桂` / `黄芪, 当归` / `Cinnamomum cassia`")
        st.caption("数据来源: BATMAN-TCM 2.0 + PubChem + UniProt + STRING + Enrichr")
        if st.button("🧹 清空当前对话内容", use_container_width=True):
            # 仅清屏(不删历史库): 历史会话仍保留在侧边栏
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

    # 按数据存在性动态拼标签页
    tab_names = ["成分表", "成分-靶点", "靶点蛋白(UniProt)"]
    disease_found = bool(result.disease and result.disease.get("found"))
    if result.intersection is not None and disease_found:
        tab_names.append("韦恩图")
    if result.ppi is not None:
        tab_names.append("PPI 网络")
    if result.enrichment is not None:
        tab_names.append("富集气泡图")
    tabs = st.tabs(tab_names)
    ti = {name: tabs[i] for i, name in enumerate(tab_names)}

    with ti["成分表"]:
        st.dataframe(pd.DataFrame(result.compounds), use_container_width=True, height=300)
    with ti["成分-靶点"]:
        st.dataframe(pd.DataFrame(result.compound_targets), use_container_width=True, height=300)
    with ti["靶点蛋白(UniProt)"]:
        st.dataframe(pd.DataFrame(result.proteins), use_container_width=True, height=300)

    uid = f"{result.query}_{s.get('unique_targets')}"

    def _img(png, fname, caption):
        if not png:
            st.info("数据不足，未生成该图")
            return
        st.image(png, caption=caption, use_container_width=False)
        st.download_button("⬇️ 下载 PNG (300dpi)", png, file_name=fname,
                           mime="image/png", key=f"dl_{fname}_{uid}")

    if "韦恩图" in ti:
        with ti["韦恩图"]:
            c = result.intersection["counts"]
            st.caption(f"药物靶点 {c['drug']} · 疾病靶点 {c['disease']} · 交集 {c['intersection']}")
            _img(venn_png(result.intersection), f"venn_{result.query}.png", "Drug–Disease overlap")
    if "PPI 网络" in ti:
        with ti["PPI 网络"]:
            st.caption(f"节点 {result.ppi['n_nodes']} · 边 {result.ppi['n_edges']} · "
                       f"基础: {result.ppi.get('basis')}")
            _img(network_png(result.ppi["nodes"], result.ppi["edges"], result.ppi.get("hubs")),
                 f"ppi_{result.query}.png", "PPI network")
    if "富集气泡图" in ti:
        with ti["富集气泡图"]:
            for lib, rows in result.enrichment.items():
                st.markdown(f"**{lib}**")
                _img(bubble_png(rows, lib), f"enrich_{lib}_{result.query}.png", lib)

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
    _save_current()          # 每轮回复后自动落库当前会话(FR-T2.5)
    st.rerun()
