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
from src.stats import overview, per_user, herb_popularity, activity_by_day
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


# ---- 前端设计 (UI 重设计): 本草典籍 × 分子网络。token 见 .streamlit/config.toml ----
_THEME_CSS = """
<style>
/* 自托管字体(spec-007): woff2 经 Streamlit 静态服务(/static/fonts/), 内网/离线免依赖 Google Fonts。
   相对路径 static/... 兼容 baseUrlPath 子路径部署。缺文件时回落系统字体(优雅降级)。 */
@font-face{font-family:'Inter';font-style:normal;font-weight:400;font-display:swap;src:url('static/fonts/inter-400.woff2') format('woff2');}
@font-face{font-family:'Inter';font-style:normal;font-weight:500;font-display:swap;src:url('static/fonts/inter-500.woff2') format('woff2');}
@font-face{font-family:'Inter';font-style:normal;font-weight:600;font-display:swap;src:url('static/fonts/inter-600.woff2') format('woff2');}
@font-face{font-family:'Inter';font-style:normal;font-weight:700;font-display:swap;src:url('static/fonts/inter-700.woff2') format('woff2');}
@font-face{font-family:'Space Mono';font-style:normal;font-weight:400;font-display:swap;src:url('static/fonts/spacemono-400.woff2') format('woff2');}
@font-face{font-family:'Space Mono';font-style:normal;font-weight:700;font-display:swap;src:url('static/fonts/spacemono-700.woff2') format('woff2');}
/* 思源宋体: 简体中文子集单字重, 覆盖 400~700 全部标题字重 */
@font-face{font-family:'Noto Serif SC';font-style:normal;font-weight:400 700;font-display:swap;src:url('static/fonts/notoserifsc-600.woff2') format('woff2');}
:root{
  --ink:#1b2a23; --paper:#FAFBF8; --sage:#EBF0EA; --line:#D9E2D6;
  --pine:#1f6b4f; --pine-soft:#2d8a66; --cinnabar:#B23A2E; --muted:#5d6b62;
}
/* 基础字族: UI 无衬线(中文回落苹方/雅黑), 标题用思源宋体(本草典籍感) */
html, body, .stApp, [data-testid="stAppViewContainer"]{
  font-family:'Inter',-apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif;
  color:var(--ink);
}
h1,h2,h3,h4,[data-testid="stHeading"]{
  font-family:'Noto Serif SC',Georgia,'Songti SC',serif !important; letter-spacing:.01em;
}
/* 数字/计量用等宽, 强调数据感 */
[data-testid="stMetricValue"],.mono{ font-family:'Space Mono',ui-monospace,monospace; }

/* 招牌: 朱砂印章 + 宋体题名 + 管线节点母题(成分→靶点→蛋白→网络) */
.hero{ display:flex; align-items:center; gap:18px; padding:6px 0 2px; }
.seal{ flex:0 0 auto; width:60px; height:60px; border-radius:14px; color:#FBEFE9;
  background:linear-gradient(145deg,#B23A2E,#922b22); display:flex; align-items:center;
  justify-content:center; font-family:'Noto Serif SC',serif; font-weight:700; font-size:33px;
  box-shadow:0 6px 18px rgba(178,58,46,.26); border:1px solid rgba(0,0,0,.06); }
.hero-title{ font-family:'Noto Serif SC',serif; font-weight:700; font-size:29px; line-height:1.12;
  margin:0; color:var(--ink); }
.pipe{ display:flex; align-items:center; gap:7px; margin-top:8px; font-family:'Space Mono',monospace;
  font-size:11.5px; letter-spacing:.03em; color:var(--pine); flex-wrap:wrap; }
.pipe .dot{ width:7px; height:7px; border-radius:50%; background:var(--pine); }
.pipe .dot.c{ background:var(--cinnabar); }
.pipe .ln{ width:16px; height:1px; background:var(--line); }
.hero-sub{ font-size:12.5px; color:var(--muted); margin-top:7px; }
.hero-rule{ height:2px; margin:13px 0 4px; border-radius:2px;
  background:linear-gradient(90deg,var(--pine),rgba(31,107,79,0) 62%); }

/* 按钮: 圆角 + 主色松绿(招牌之外保持克制) */
.stButton>button,.stFormSubmitButton>button{ border-radius:9px; font-weight:600; }
button[kind="primary"],[data-testid="stBaseButton-primary"]{ background:var(--pine); border-color:var(--pine); }
button[kind="primary"]:hover{ background:var(--pine-soft); border-color:var(--pine-soft); }

/* 指标卡片化 */
[data-testid="stMetric"]{ background:#fff; border:1px solid var(--line); border-radius:14px;
  padding:13px 16px; box-shadow:0 1px 2px rgba(20,40,30,.04); }
[data-testid="stMetricValue"]{ color:var(--pine); }
[data-testid="stMetricLabel"]{ color:var(--muted); }

/* 侧栏(Claude 网页版结构): 无衬线、紧凑、会话行左对齐单行截断 */
[data-testid="stSidebar"]{ border-right:1px solid var(--line); }
/* 侧栏标题不用宋体, 与 Claude 一致的干净无衬线 */
[data-testid="stSidebar"] h1,[data-testid="stSidebar"] h2,[data-testid="stSidebar"] h3{
  font-family:'Inter',-apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif !important;
}
.side-brand{ display:flex; align-items:center; gap:7px; font-weight:600; font-size:15px;
  color:var(--ink); padding:2px 2px 10px; letter-spacing:.01em; }
.side-spacer{ height:14px; }
.side-account{ display:flex; align-items:center; gap:6px; font-size:12.5px; color:var(--muted);
  padding:2px 2px 0; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; min-width:0; }
/* 会话列表: 幽灵态标题(左对齐、单行截断), 选中态柔和苔绿(非抢眼松绿) */
.st-key-convlist .stButton>button{ justify-content:flex-start; text-align:left;
  white-space:nowrap; overflow:hidden; text-overflow:ellipsis; font-weight:500;
  background:transparent; border-color:transparent; }
.st-key-convlist .stButton>button:hover{ background:#fff; border-color:var(--line); }
.st-key-convlist .stButton>button[kind="primary"]{ background:var(--sage); color:var(--ink);
  border-color:var(--line); font-weight:600; }
/* ⋯ 菜单触发按钮: 紧凑不撑破窄列(修复挤成「.·」) */
.st-key-convlist [data-testid="stPopover"] button{ padding-left:0; padding-right:0;
  min-height:38px; border-color:transparent; background:transparent; }
.st-key-convlist [data-testid="stPopover"] button:hover{ background:#fff; border-color:var(--line); }

/* 选项卡选中色 / 表单卡 / 数据表圆角 */
[data-testid="stTabs"] button[aria-selected="true"]{ color:var(--pine)!important; }
[data-testid="stForm"]{ background:#fff; border:1px solid var(--line); border-radius:16px; }
[data-testid="stDataFrame"]{ border-radius:12px; overflow:hidden; }
[data-testid="stChatInput"]{ border-radius:14px; }

/* 质量底线: 键盘焦点可见 + 尊重减少动效 */
:focus-visible{ outline:2px solid var(--cinnabar); outline-offset:2px; }
@media (prefers-reduced-motion: reduce){ *{ animation:none!important; transition:none!important; } }
</style>
"""

_HERO_HTML = """
<div class="hero">
  <div class="seal">本</div>
  <div>
    <div class="hero-title">中药网络药理学一站式助手</div>
    <div class="pipe">
      <span class="dot"></span>成分<span class="ln"></span>
      <span class="dot"></span>靶点<span class="ln"></span>
      <span class="dot"></span>蛋白<span class="ln"></span>
      <span class="dot c"></span>网络
    </div>
    <div class="hero-sub">数据来源 · BATMAN-TCM 2.0 · PubChem · UniProt · STRING · Enrichr</div>
  </div>
</div>
<div class="hero-rule"></div>
"""


def _inject_theme():
    st.markdown(_THEME_CSS, unsafe_allow_html=True)


def _render_hero():
    st.markdown(_HERO_HTML, unsafe_allow_html=True)


st.set_page_config(page_title="中药网络药理学助手", page_icon="🌿", layout="wide")
_inject_theme()
_render_hero()

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
    # 角色以账号库为准(不依赖 stauth 内部 session 写入), 供后台门控
    _me = _ustore.get(st.session_state.owner) or {}
    st.session_state.role = _me.get("role", "user")
else:
    st.session_state.owner = "default"          # 关闭认证时回退单租户
    st.session_state.auth = None
    st.session_state.role = "admin"             # 关闭认证 -> 单租户全权
if "view" not in st.session_state:
    st.session_state.view = "chat"              # chat | admin

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
    # ① 品牌(紧凑、无衬线)
    st.markdown('<div class="side-brand">🌿 中药网络药理学</div>', unsafe_allow_html=True)
    _store, _hcfg = _history()

    # ② 新建对话(醒目主按钮)
    if st.button("✚　新建对话", use_container_width=True, type="primary"):
        _new_conversation()
        st.rerun()

    # ③ 最近对话(Claude 式扁平列表: 标题幽灵按钮 + 右侧「⋯」菜单)
    st.caption("最近对话")
    _convs = _store.list(st.session_state.owner,
                         limit=int(_hcfg.get("max_conversations", 50)))
    with st.container(key="convlist"):
        if not _convs:
            st.caption("暂无历史，开始第一轮提问吧")
        for _c in _convs:
            _cur = _c["id"] == st.session_state.conv_id
            _title = _c["title"] or "新对话"
            _row, _menu = st.columns([0.8, 0.2], vertical_alignment="center")
            # 选中态经 CSS 呈柔和苔绿高亮(见 .st-key-convlist)
            if _row.button(_title, key=f"open_{_c['id']}", use_container_width=True,
                           type="primary" if _cur else "secondary"):
                _open_conversation(_store, _c["id"])
                st.rerun()
            # 管理操作收进「⋯」菜单(重命名 / 删除)
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

    # ④ 底部账户区(Claude 把账户/设置放最底): 管理入口 → 账户 → 后端
    st.markdown('<div class="side-spacer"></div>', unsafe_allow_html=True)
    st.divider()
    # 管理后台入口: 仅 admin 可见(spec-005 FR-T2.1)
    if st.session_state.get("role") == "admin":
        if st.session_state.view == "admin":
            if st.button("←　返回助手", use_container_width=True):
                st.session_state.view = "chat"
                st.rerun()
        else:
            if st.button("🛠　管理后台", use_container_width=True):
                st.session_state.view = "admin"
                st.rerun()
    if st.session_state.get("auth") is not None:
        _who, _out = st.columns([0.68, 0.32], vertical_alignment="center")
        _role_badge = "管理员" if st.session_state.get("role") == "admin" else "用户"
        _who.markdown(
            f'<div class="side-account">👤 {st.session_state.get("name") or st.session_state.owner}'
            f'　·　{_role_badge}</div>', unsafe_allow_html=True)
        with _out:
            st.session_state.auth.logout("登出", location="main",
                                         use_container_width=True)
    # 后端状态(紧凑一行; 「清空对话」已移除——有历史后用「新建对话」即可)
    if os.environ.get("DEEPSEEK_API_KEY"):
        _backend = "DeepSeek (deepseek-chat)"
    elif os.environ.get("OPENAI_API_KEY"):
        _backend = "OpenAI 兼容"
    elif os.environ.get("ANTHROPIC_API_KEY"):
        _backend = "Claude (claude-opus-4-8)"
    else:
        _backend = "直接模式(无 LLM)"
    st.caption(f"ℹ️ {_backend}")


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


def render_admin():
    """管理后台(spec-005 T2): 统计看板 + 账号管理。仅 admin 进入。"""
    st.subheader("🛠 管理后台")
    store_h, _ = _history()
    acfg = load_config().raw.get("admin", {}) or {}
    top_n = int(acfg.get("herb_top_n", 10))
    days = int(acfg.get("activity_days", 14))
    users = _ustore.list_users()
    convs = store_h.export_all()
    n_admins = sum(1 for u in users if u.get("role") == "admin")
    n_conv_by = {r["username"]: r["n_conversations"] for r in per_user(users, convs)}

    tab_stat, tab_users = st.tabs(["📊 统计看板", "👥 账号管理"])

    with tab_stat:
        o = overview(users, convs)
        c = st.columns(4)
        c[0].metric("用户数", o["n_users"])
        c[1].metric("会话总数", o["n_conversations"])
        c[2].metric("消息总数", o["n_messages"])
        c[3].metric("活跃用户", o["active_users"])
        st.caption(f"其中管理员 {o['n_admins']} 人")

        st.markdown(f"**热门药材 Top {top_n}**（基于真实跑出的分析结果）")
        pop = herb_popularity(convs, top_n=top_n)
        if pop:
            dfp = pd.DataFrame(pop).rename(
                columns={"herb": "药材", "count": "分析次数", "found": "成功命中"})
            st.bar_chart(dfp.set_index("药材")["分析次数"], color="#3ba776")
            st.dataframe(dfp, use_container_width=True, hide_index=True)
        else:
            st.info("暂无分析记录")

        st.markdown(f"**近 {days} 天活跃趋势（新建会话数）**")
        act = activity_by_day(convs, today=datetime.date.today().isoformat(), days=days)
        dfa = pd.DataFrame(act).rename(columns={"date": "日期", "count": "新建会话"})
        st.line_chart(dfa.set_index("日期")["新建会话"], color="#3ba776")

        st.markdown("**各用户活跃度**")
        dfu = pd.DataFrame(per_user(users, convs)).rename(columns={
            "username": "用户名", "role": "角色", "n_conversations": "会话数",
            "n_messages": "消息数", "last_active": "最近活跃"})
        st.dataframe(dfu, use_container_width=True, hide_index=True)

    with tab_users:
        with st.expander("➕ 新建用户", expanded=False):
            with st.form("new_user", clear_on_submit=True):
                nu = st.text_input("用户名")
                nn = st.text_input("姓名")
                ne = st.text_input("邮箱")
                npw = st.text_input("初始密码", type="password")
                nr = st.selectbox("角色", ["user", "admin"])
                if st.form_submit_button("创建", type="primary"):
                    if not nu.strip():
                        st.error("用户名必填")
                    elif _ustore.get(nu.strip()):
                        st.error("用户名已存在")
                    elif not stauth.Validator().validate_password(npw):
                        st.error("密码需 8–20 位且含大小写字母、数字、特殊字符")
                    else:
                        _ustore.upsert({"username": nu.strip(), "name": nn.strip() or nu.strip(),
                                        "email": ne.strip(),
                                        "password_hash": stauth.Hasher.hash(npw),
                                        "role": nr, "created_at": _now_iso()})
                        st.success(f"已创建用户 {nu.strip()}")
                        st.rerun()

        for u in users:
            uname = u["username"]
            is_self = uname == st.session_state.owner
            is_last_admin = u.get("role") == "admin" and n_admins <= 1
            # keyed 容器 -> DOM 带 class st-key-userrow_<uname>, 供 E2E 精确定位该行
            with st.container(border=True, key=f"userrow_{uname}"):
                c0, c1, c2, c3 = st.columns([3, 3, 2, 1], vertical_alignment="center")
                c0.markdown(f"**{uname}**　`{u.get('role', 'user')}`")
                c1.caption(f"{u.get('name', '')} · {u.get('email', '') or '—'} · "
                           f"{n_conv_by.get(uname, 0)} 会话")
                # 改角色
                with c2.popover("角色", use_container_width=True):
                    if is_last_admin:
                        st.caption("末位管理员不可降级")
                    else:
                        _target = "user" if u.get("role") == "admin" else "admin"
                        if st.button(f"设为 {_target}", key=f"role_{uname}",
                                     use_container_width=True):
                            _ustore.set_role(uname, _target)
                            st.rerun()
                # 重置密码 / 删除
                with c3.popover("⋯", use_container_width=True):
                    _npw = st.text_input("新密码", type="password", key=f"pw_{uname}",
                                         label_visibility="collapsed", placeholder="新密码")
                    if st.button("🔑 重置密码", key=f"rstpw_{uname}", use_container_width=True):
                        if stauth.Validator().validate_password(_npw):
                            _ustore.set_password(uname, stauth.Hasher.hash(_npw))
                            st.success("已重置")
                        else:
                            st.error("密码不合规（8–20 位，含大小写/数字/特殊字符）")
                    st.divider()
                    if is_self:
                        st.caption("不可删除自己")
                    elif is_last_admin:
                        st.caption("末位管理员不可删除")
                    elif st.button("🗑 删除用户", key=f"del_{uname}", use_container_width=True):
                        _ustore.delete(uname)
                        st.rerun()


# admin 视图替换主区(spec-005 FR-T2.2): 仅 admin 且 view==admin
if st.session_state.get("role") == "admin" and st.session_state.view == "admin":
    render_admin()
    st.stop()

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
