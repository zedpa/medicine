"""spec-004 T3 验收 AC-15…AC-17: 账号授权门 + 多租户隔离。

未登录看不到主应用; 不同账号互不可见对方历史; 本人重登仍见自己的历史。
注册/登录两个表单都含「用户名/密码」标签 -> 用所在 stForm 作用域消歧。
用未知药材查询触发秒级友好告警, 即产生一轮已落库的对话。
"""
from conftest import login

SIDEBAR = '[data-testid="stSidebar"]'


def _form(page, btn):
    """返回含指定提交按钮的表单(登录 / 注册), 用于消除同名标签歧义。"""
    return page.locator('[data-testid="stForm"]').filter(
        has=page.get_by_role("button", name=btn))


def _register(page, username, pwd):
    page.get_by_text("注册新账号").click()           # 展开注册 expander
    f = _form(page, "注册")
    f.get_by_label("名", exact=True).fill(username)
    f.get_by_label("姓", exact=True).fill("测试")
    f.get_by_label("邮箱", exact=True).fill(f"{username}@ex.com")
    f.get_by_label("用户名", exact=True).fill(username)
    f.get_by_label("密码", exact=True).fill(pwd)
    f.get_by_label("确认密码", exact=True).fill(pwd)
    f.get_by_role("button", name="注册").click()
    page.get_by_text("注册成功", exact=False).wait_for(timeout=30_000)


def _login_scoped(page, username, pwd):
    f = _form(page, "登录")
    f.get_by_label("用户名", exact=True).fill(username)
    f.get_by_label("密码", exact=True).fill(pwd)
    f.get_by_role("button", name="登录").click()
    page.locator('[data-testid="stChatInput"]').wait_for(timeout=30_000)


def _ask(page, text):
    chat = page.locator('[data-testid="stChatInput"] textarea')
    chat.fill(text)
    chat.press("Enter")
    page.get_by_test_id("stAlertContentWarning").first.wait_for(timeout=120_000)


def _logout(page):
    page.get_by_role("button", name="登出").click()
    _form(page, "登录").wait_for(timeout=30_000)       # 回到登录门


def test_unauthenticated_sees_only_login(page_raw):  # AC-15
    page = page_raw
    # 先等登录门渲染完成
    _form(page, "登录").get_by_role("button", name="登录").wait_for(timeout=30_000)
    assert page.locator('[data-testid="stChatInput"]').count() == 0   # 无聊天输入
    assert page.locator(SIDEBAR).get_by_text("最近对话").count() == 0  # 无历史列表


def test_history_isolated_between_users(page_raw):  # AC-16 + AC-17
    page = page_raw
    # 用户 A 注册→登录→产生一轮对话
    _register(page, "alice", "Alicepwd1!")
    _login_scoped(page, "alice", "Alicepwd1!")
    _ask(page, "甲药alicexyz")
    page.locator(SIDEBAR).get_by_text("甲药alicexyz", exact=False).first.wait_for(timeout=30_000)
    _logout(page)

    # 用户 B 注册→登录: 看不到 A 的会话(隔离)
    _register(page, "bob", "Bobpwd1234!")
    _login_scoped(page, "bob", "Bobpwd1234!")
    page.wait_for_timeout(1500)
    assert page.locator(SIDEBAR).get_by_text("甲药alicexyz", exact=False).count() == 0
    _logout(page)

    # A 重新登录: 仍见自己的历史(AC-17 归属持久且正确)
    _login_scoped(page, "alice", "Alicepwd1!")
    page.locator(SIDEBAR).get_by_text("甲药alicexyz", exact=False).first.wait_for(timeout=30_000)
