"""spec-005 T2 验收 AC-7…AC-10: 管理后台(角色门 + 统计看板 + 账号管理)。

复用 conftest.login(种子 admin) 与 test_e2e_auth 的注册/登录助手(同目录可导入)。
账号/历史库经 conftest 指向临时文件, 不污染真实数据。
"""
from conftest import login
from test_e2e_auth import _register, _login_scoped, _logout

SIDEBAR = '[data-testid="stSidebar"]'


def _enter_admin(page):
    page.locator(SIDEBAR).get_by_role("button", name="管理后台").click()
    page.get_by_text("🛠 管理后台").wait_for(timeout=30_000)


def test_admin_entry_and_dashboard(page_to_app):  # AC-7
    page = page_to_app
    # admin 登录后侧边栏有入口
    assert page.locator(SIDEBAR).get_by_role("button", name="管理后台").is_visible()
    _enter_admin(page)
    # 看到统计看板与四指标之一
    page.get_by_role("tab", name="统计看板").wait_for(timeout=30_000)
    assert page.get_by_text("用户数").first.is_visible()
    assert page.get_by_role("tab", name="账号管理").is_visible()


def test_normal_user_no_admin_entry(page_raw):  # AC-8
    page = page_raw
    # 注: stauth 校验「名」不许含数字, 故用纯字母用户名(_register 用 username 兼作名)
    _register(page, "norm", "Normpwd1!")
    _login_scoped(page, "norm", "Normpwd1!")
    # 普通用户侧边栏无管理后台入口
    assert page.locator(SIDEBAR).get_by_role("button", name="管理后台").count() == 0


def test_create_change_delete_user(page_to_app):  # AC-9
    page = page_to_app
    _enter_admin(page)
    page.get_by_role("tab", name="账号管理").click()
    # 新建用户 carol
    page.get_by_text("➕ 新建用户").click()
    page.get_by_label("用户名").fill("carol")
    page.get_by_label("姓名").fill("卡萝")
    page.get_by_label("邮箱").fill("carol@ex.com")
    page.get_by_label("初始密码").fill("Carolpwd1!")
    page.get_by_role("button", name="创建").click()
    # 用户表出现 carol(keyed 容器 -> .st-key-userrow_carol)
    row = page.locator(".st-key-userrow_carol")
    row.wait_for(timeout=30_000)
    # 改角色 user -> admin
    row.get_by_role("button", name="角色").click()
    page.locator('[data-testid="stPopoverBody"]').get_by_role(
        "button", name="设为 admin").click()
    page.wait_for_timeout(1500)
    # 删除 carol(此时已是 admin, 但非自己、非末位 -> 可删)
    row = page.locator(".st-key-userrow_carol")
    row.get_by_role("button", name="⋯").click()
    page.locator('[data-testid="stPopoverBody"]').get_by_role(
        "button", name="🗑 删除用户").click()
    page.wait_for_timeout(1500)
    assert page.locator(".st-key-userrow_carol").count() == 0


def test_last_admin_protected(page_to_app):  # AC-10
    page = page_to_app
    _enter_admin(page)
    page.get_by_role("tab", name="账号管理").click()
    # 找到 admin 自己的行(种子唯一管理员)
    row = page.locator(".st-key-userrow_admin")
    row.wait_for(timeout=30_000)
    # ⋯ 菜单: 不可删除自己
    row.get_by_role("button", name="⋯").click()
    body = page.locator('[data-testid="stPopoverBody"]')
    assert body.get_by_text("不可删除自己").is_visible()
    assert body.get_by_role("button", name="🗑 删除用户").count() == 0
