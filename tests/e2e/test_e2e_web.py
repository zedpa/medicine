"""端到端浏览器测试（Playwright）：模拟用户在网页上输入药材名, 验证真实管道产出。

直接模式（无 LLM 密钥, 输入即药材名）→ 跑真实 BATMAN/PubChem/UniProt/STRING/Enrichr 管道
（缓存已预热, 秒级）→ 断言指标、可视化标签页、图像、下载按钮均按数据存在性正确呈现。

运行: .venv/bin/python -m pytest tests/e2e   (默认 pytest 运行已 --ignore 本目录)
"""
import re


def test_page_loads_direct_mode(page_to_app):
    """E2E-1: 页面加载, 标题可见, 侧栏显示「直接模式」, 输入框就绪。"""
    page = page_to_app
    page.get_by_text("中药网络药理学一站式助手").wait_for(timeout=30_000)
    assert page.get_by_text("直接模式").first.is_visible()
    page.locator('[data-testid="stChatInput"] textarea').wait_for(timeout=30_000)


def test_full_pipeline_via_ui(page_to_app):
    """E2E-2~5: 输入「肉桂」→ 指标/标签页/图像/下载按钮端到端呈现。"""
    page = page_to_app

    chat = page.locator('[data-testid="stChatInput"] textarea')
    chat.fill("肉桂")
    chat.press("Enter")

    # 结果面板出现
    page.get_by_text("分析结果").wait_for(timeout=180_000)

    # E2E-2: 4 个指标卡 + 关键标签可见
    assert page.locator('[data-testid="stMetric"]').count() == 4
    assert page.get_by_text("成分总数").first.is_visible()
    assert page.get_by_text("通过 ADME").first.is_visible()

    # E2E-3: 标签页含基础三表 + PPI + 富集(直接模式无疾病, 故无「韦恩图」)
    tabs = page.locator('button[role="tab"]')
    names = [tabs.nth(i).inner_text() for i in range(tabs.count())]
    for must in ("成分表", "成分-靶点", "靶点蛋白(UniProt)", "PPI 网络", "富集气泡图"):
        assert must in names, f"缺标签页: {must} (实际 {names})"
    assert "韦恩图" not in names, "直接模式不应出现韦恩图(无疾病交集)"

    # E2E-4: 点开 PPI 网络标签 → 渲染出 <img>
    page.get_by_role("tab", name="PPI 网络").click()
    page.wait_for_timeout(1500)
    assert page.locator('[data-testid="stImage"] img').count() >= 1

    # 点开富集气泡图 → 也有图
    page.get_by_role("tab", name="富集气泡图").click()
    page.wait_for_timeout(1500)
    assert page.locator('[data-testid="stImage"] img').count() >= 1

    # E2E-5: 下载按钮(Excel + PNG)存在
    assert page.locator('[data-testid="stDownloadButton"]').count() >= 2
    assert page.get_by_text("下载完整 Excel").first.is_visible()


def test_unknown_herb_shows_warning(page_to_app):
    """E2E-6(负向): 不存在的药材 → 友好「未找到」提示(告警框), 不崩溃。"""
    page = page_to_app
    chat = page.locator('[data-testid="stChatInput"] textarea')
    chat.fill("这不是一味中药xyz")
    chat.press("Enter")
    alert = page.get_by_test_id("stAlertContentWarning")
    alert.wait_for(timeout=120_000)
    assert re.search(r"未在 BATMAN-TCM", alert.inner_text())
