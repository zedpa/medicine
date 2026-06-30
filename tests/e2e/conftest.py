"""E2E 夹具：启动真实 Streamlit 服务(直接模式, 无 LLM 密钥), 供 Playwright 驱动。

直接模式 = 不配任何 API key, 输入即药材名 -> 跑真实管道(缓存已预热, 秒级)。
"""
import os
import socket
import subprocess
import tempfile
import time
import urllib.request

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PORT = 8599
BASE_URL = f"http://127.0.0.1:{PORT}"
# E2E 库隔离: 不污染真实 data/*.sqlite
HISTORY_DB = os.path.join(tempfile.gettempdir(), "tcm_e2e_history.sqlite")
AUTH_DB = os.path.join(tempfile.gettempdir(), "tcm_e2e_auth.sqlite")
# 种子 admin(spec-004): 供已登录类用例; 固定 Cookie key 保证刷新后免登
ADMIN_USER, ADMIN_PASSWORD = "admin", "admin123"


def login(page, username=ADMIN_USER, password=ADMIN_PASSWORD):
    """填登录表单并提交; 等待主应用(聊天输入框)出现。

    登录/注册两表单都含「用户名/密码」标签 -> 用所在 stForm 作用域消歧。
    """
    form = page.locator('[data-testid="stForm"]').filter(
        has=page.get_by_role("button", name="登录"))
    form.get_by_label("用户名", exact=True).fill(username)
    form.get_by_label("密码", exact=True).fill(password)
    form.get_by_role("button", name="登录").click()
    page.locator('[data-testid="stChatInput"]').wait_for(timeout=30_000)


def _free(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) != 0


# macOS 系统代理会拦截 127.0.0.1 -> 显式禁用代理
_NO_PROXY = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _wait_health(timeout=120):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = _NO_PROXY.open(f"{BASE_URL}/_stcore/health", timeout=2)
            if r.status == 200 and r.read().strip() == b"ok":
                return True
        except Exception:
            time.sleep(0.5)
    return False


@pytest.fixture(scope="session")
def streamlit_server():
    # 清除 LLM 密钥 -> 直接模式(确定性, 不触 LLM/不计费)
    env = {k: v for k, v in os.environ.items()
           if k not in ("DEEPSEEK_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY")}
    # 历史库 + 账号库指向临时文件并清空, 保证本轮 E2E 干净起步
    for f in (HISTORY_DB, AUTH_DB):
        if os.path.exists(f):
            os.remove(f)
    env["HISTORY_DB_PATH"] = HISTORY_DB
    env["AUTH_DB_PATH"] = AUTH_DB
    env["AUTH_COOKIE_KEY"] = "e2e-fixed-cookie-key-0123456789"   # 固定 -> 刷新免登
    env["ADMIN_USER"] = ADMIN_USER                               # 种子 admin
    env["ADMIN_PASSWORD"] = ADMIN_PASSWORD
    venv_py = os.path.join(ROOT, ".venv", "bin", "streamlit")
    proc = subprocess.Popen(
        [venv_py, "run", "web/app.py",
         "--server.port", str(PORT), "--server.address", "127.0.0.1",
         "--server.headless", "true", "--browser.gatherUsageStats", "false"],
        cwd=ROOT, env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        assert _wait_health(60), "Streamlit 未在 60s 内就绪"
        yield BASE_URL
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


@pytest.fixture(scope="session")
def browser_type_launch_args(browser_type_launch_args):
    # macOS 系统代理会拦 127.0.0.1 -> 让 chromium 直连
    return {**browser_type_launch_args, "args": ["--no-proxy-server"]}


@pytest.fixture
def page_raw(streamlit_server, page):
    """到达应用但**不登录**(供认证门用例)。每个 page 是全新 context, 无 cookie。"""
    page.set_default_timeout(180_000)
    page.goto(streamlit_server, wait_until="domcontentloaded")
    return page


@pytest.fixture
def page_to_app(page_raw):
    """到达应用并以种子 admin 登录(供已登录类用例)。"""
    login(page_raw)
    return page_raw
