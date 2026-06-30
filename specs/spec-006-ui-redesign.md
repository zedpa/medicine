# Spec-006 前端 UI 重设计（本草典籍 × 分子网络）

状态: ✅ 完成 · 负责人: web · 关联: [[spec-003 对话历史]](spec-003-conversation-history.md) · 方法: 依据 Anthropic `frontend-design` skill 的两遍式设计法

参考: <https://github.com/anthropics/skills/blob/main/skills/frontend-design/SKILL.md>

## 1. 背景与目标

界面此前沿用 Streamlit 默认观感（默认红主色、无字体系统、无招牌）。本次按 frontend-design skill 重设计，让**主题本身**（中药 × 网络药理学）驱动美学，而非套模板。

约束（保持功能不破）：UI 为**纯视觉**重设计——所有 E2E 依赖的可见文案/控件名/test-id（标题「中药网络药理学一站式助手」、按钮「新建对话/登录/注册/登出/管理后台/角色/⋯/创建」、选项卡、指标名等）**一律保留**，仅改样式、字体、招牌与配色。13 个 E2E + 66 单测重设计后仍全绿。

## 2. 设计主题（thesis）

「**本草典籍 × 分子网络**」：古典中医药文献的学术气质，与现代生物信息网络的精确数据感融合。

## 3. Token 系统（第一遍）

**配色**（4–6 named）：
- `--pine #1f6b4f` 松绿——植物学主色（按钮/选项卡/控件强调，= `primaryColor`）
- `--paper #FAFBF8` 矿物冷白——背景（**刻意非**暖奶油 #F4F1EA）
- `--sage #EBF0EA` 柔和苔绿——侧栏/卡片（`secondaryBackgroundColor`）
- `--ink #1b2a23` 松墨——正文（带绿调近黑）
- `--cinnabar #B23A2E` 朱砂——**招牌色**，源自中医矿物药/印章传统（克制使用，非泛用陶土）

**字族**：
- 展示/标题：思源宋体 `Noto Serif SC`（古典医典感）
- 正文/UI：`Inter`（中文回落苹方/微软雅黑）
- 计量/编号：`Space Mono`（强化数据感）

**招牌元素（spend boldness in one place）**：朱砂**印章**「本」（取「本草」之本）置于题名左侧；其余一律安静克制。

**结构编码信息**：招牌下方节点母题 `成分 ─ 靶点 ─ 蛋白 ─ 网络`，对应真实管线流程，末节点（网络）用朱砂呼应印章。

**布局（ASCII）**：
```
┌───────────────────────────────────────────┐
│ [本]  中药网络药理学一站式助手   (思源宋体)   │
│ 印章  ● 成分 — ● 靶点 — ● 蛋白 — ◍ 网络      │
│       数据来源 · BATMAN-TCM · PubChem · …    │
├──── pine→透明 渐变细线 ──────────────────────┤
```

## 4. 第二遍 · 对照红线自评

skill 列出三种 AI 默认观感，逐一规避：
1. **暖奶油 + 高对比衬线 + 陶土** → 用矿物冷白 + 中文宋体 + 朱砂印章（朱砂有文化出处，非泛用陶土）。
2. **近黑底 + 荧光绿/朱红强调** → 浅底 + **沉静**松绿（非荧光 #39FF14）。
3. **broadsheet 细线 + 零圆角 + 密排栏** → 柔和圆角卡片（指标/表单/数据表）、留白充足。

质量底线：键盘焦点可见（`:focus-visible` 朱砂描边）、`prefers-reduced-motion` 关闭动效、Streamlit 自带响应式。

## 5. 落地

- `.streamlit/config.toml`：主题 token（primaryColor/background/secondaryBackground/text/font）。
- `web/app.py`：`_inject_theme()` 注入字体 + CSS（招牌、按钮、指标卡、侧栏、选项卡、表单卡、焦点/减动效）；`_render_hero()` 渲染印章招牌 + 节点母题，替代原 `st.title`/`st.caption`（题名文案不变）。

## 6. 边界
- Streamlit 限制下不做画布动画/复杂滚动叙事；招牌为静态 HTML/CSS（含内联节点母题），符合「克制」。
- 字体经 Google Fonts `@import`；离线/内网部署若需自托管字体，可改 `<link>` 指向本地，token 不变。
