"""spec-003 T2 验收 AC-9…AC-11: 侧边栏对话历史(持久化/新建保留/删除落库)。

用「未知药材」做查询: 触发友好告警即产生一轮对话(user+assistant), 秒级完成,
避免全管道开销; 历史落库正确性已由 T1 单测覆盖, 此处只验 UI 行为。
历史库经 conftest 指向临时文件并清空, 不污染真实数据。
"""
SIDEBAR = '[data-testid="stSidebar"]'


def _ask(page, text):
    chat = page.locator('[data-testid="stChatInput"] textarea')
    chat.fill(text)
    chat.press("Enter")
    # 未知药材 -> 友好告警; 出现即说明该轮对话已完成并自动落库
    page.get_by_test_id("stAlertContentWarning").first.wait_for(timeout=120_000)


def test_sidebar_structure_claude_like(page_to_app):  # spec-008: 结构重整
    """有历史后「清空对话」无意义 -> 移除; 侧栏保留新建/最近对话/账户核心结构。"""
    page = page_to_app
    sb = page.locator(SIDEBAR)
    sb.get_by_role("button", name="新建对话").wait_for(timeout=30_000)
    assert sb.get_by_text("最近对话").is_visible()
    assert sb.get_by_role("button", name="登出").count() == 1
    # 「清空当前对话内容」按钮已移除
    assert sb.get_by_role("button", name="清空").count() == 0


def test_history_persists_after_reload(page_to_app):  # AC-9
    page = page_to_app
    q = "历史甲药xyz"
    _ask(page, q)
    # 侧边栏出现该会话标题
    page.locator(SIDEBAR).get_by_text(q, exact=False).first.wait_for(timeout=30_000)
    # 刷新页面(新会话, session_state 重置) -> 历史仍在(证明落库, 非内存)
    page.reload(wait_until="domcontentloaded")
    page.locator(SIDEBAR).get_by_text(q, exact=False).first.wait_for(timeout=30_000)
    # 点击历史项 -> 对话气泡重现
    page.locator(SIDEBAR).get_by_text(q, exact=False).first.click()
    bubble = page.locator('[data-testid="stChatMessage"]').get_by_text(q, exact=False)
    bubble.first.wait_for(timeout=30_000)
    assert bubble.first.is_visible()


def test_new_conversation_keeps_history(page_to_app):  # AC-10
    page = page_to_app
    q = "历史乙药xyz"
    _ask(page, q)
    page.locator(SIDEBAR).get_by_text(q, exact=False).first.wait_for(timeout=30_000)
    # 新建对话: 主区清空, 但侧边栏历史保留上一会话
    page.get_by_role("button", name="新建对话").click()
    page.wait_for_timeout(1500)
    assert page.locator('[data-testid="stChatMessage"]').count() == 0   # 主区已清空
    assert page.locator(SIDEBAR).get_by_text(q, exact=False).first.is_visible()  # 历史仍在
    # 点回上一会话 -> 恢复其消息
    page.locator(SIDEBAR).get_by_text(q, exact=False).first.click()
    page.locator('[data-testid="stChatMessage"]').get_by_text(q, exact=False).first.wait_for(timeout=30_000)


def test_snapshot_restores_result_panel(page_to_app):  # AC-15
    """跑出带图表的分析 → 新建对话 → 点回该会话: 结果面板与 PPI 图重新出现(快照重显)。"""
    page = page_to_app
    chat = page.locator('[data-testid="stChatInput"] textarea')
    chat.fill("肉桂")
    chat.press("Enter")
    page.get_by_text("分析结果").wait_for(timeout=180_000)
    page.get_by_role("tab", name="PPI 网络").click()
    page.wait_for_timeout(1500)
    assert page.locator('[data-testid="stImage"] img').count() >= 1

    # 新建对话: 结果面板消失
    page.get_by_role("button", name="新建对话").click()
    page.wait_for_timeout(1500)
    assert page.get_by_text("分析结果").count() == 0

    # 点回「肉桂」会话: 结果面板 + PPI 图重新出现(证明快照重显, 非空白)
    # 注: 用 button role 定位会话项, 避开侧栏「示例: 肉桂」说明文字
    page.locator(SIDEBAR).get_by_role("button", name="肉桂").first.click()
    page.get_by_text("分析结果").wait_for(timeout=60_000)
    page.get_by_role("tab", name="PPI 网络").click()
    page.wait_for_timeout(1500)
    assert page.locator('[data-testid="stImage"] img').count() >= 1


def test_delete_removes_conversation(page_to_app):  # AC-11
    page = page_to_app
    q = "历史丙药xyz"
    _ask(page, q)
    sidebar = page.locator(SIDEBAR)
    sidebar.get_by_text(q, exact=False).first.wait_for(timeout=30_000)
    # 管理操作在「⋯」三点菜单内: 先打开该会话行的菜单, 再点删除
    row = sidebar.locator('[data-testid="stHorizontalBlock"]').filter(has_text=q)
    row.get_by_role("button", name="⋯").first.click()
    page.wait_for_timeout(500)
    # 打开的 popover 内容点删除(只渲染当前打开的 popover body)
    page.locator('[data-testid="stPopoverBody"]').get_by_role(
        "button", name="🗑 删除对话").first.click()
    page.wait_for_timeout(1500)
    assert sidebar.get_by_text(q, exact=False).count() == 0      # 从侧边栏消失
    # 刷新后不复现(确认落库删除)
    page.reload(wait_until="domcontentloaded")
    page.locator(SIDEBAR).wait_for(timeout=30_000)
    page.wait_for_timeout(1000)
    assert page.locator(SIDEBAR).get_by_text(q, exact=False).count() == 0
