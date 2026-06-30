# Spec-007 自托管字体（内网/离线免依赖 Google Fonts）

状态: ✅ 完成 · 负责人: web · 关联: [[spec-006 UI 重设计]](spec-006-ui-redesign.md)

## 1. 背景与目标

spec-006 的字体经 `@import url(https://fonts.googleapis.com/...)` 从 Google Fonts 加载。内网/离线部署时该请求不可达 → 标题/正文退化为系统字体，且每次访问外联 Google（隐私/可达性问题）。

目标：把字体**自托管**到应用内，经 Streamlit 静态服务提供，彻底移除对 Google Fonts 的运行时依赖；缺字体时优雅降级到系统字体。

## 2. 方案

- **静态服务**：`.streamlit/config.toml › [server] enableStaticServing = true`；`static/` 下文件经 `/static/<path>` 提供（本机 Streamlit 1.50 实测路径为 `/static/`，非旧文档的 `app/static/`）。
- **字体文件**（`static/fonts/`，来源 Fontsource@jsDelivr，woff2）：
  - `Inter` 400/500/600/700（latin，UI 正文/控件，各 ~24KB）
  - `Space Mono` 400/700（latin，计量/编号，各 ~16KB）
  - `Noto Serif SC` 600（**简体中文子集** ~1.5MB，标题/招牌；单字重经 `font-weight:400 700` 覆盖全部标题字重）
  - 合计 ~1.6MB，直接入库 → 开箱即用、离线可跑。
- **获取脚本**：`scripts/fetch_fonts.sh`（幂等重拉，记录来源）。
- **CSS**：`web/app.py` 的 `_THEME_CSS` 用 `@font-face` 引 `static/fonts/*.woff2`（**相对路径**，兼容 baseUrlPath 子路径部署），替换原 `@import`。`font-display:swap`；缺文件时回落 `-apple-system / PingFang SC / Microsoft YaHei`（无衬线）与 `Georgia / Songti SC / serif`（衬线）。

## 3. 验收（实景，Playwright）
- 加载页面后网络请求中**无** `fonts.googleapis.com` / `fonts.gstatic.com`；字体 woff2 全部来自本机 `/static/fonts/`。
- 招牌/标题仍为思源宋体的古典宋体观感，与 spec-006 一致（视觉回归无差）。
- 66 单测 + 13 E2E 全绿（E2E 服务从仓库根启动，已实际走静态服务路径）。

## 4. 边界
- CJK 用简体中文子集（覆盖常用字含药材名）；极生僻字回落系统宋体。
- 字体文件直接入库（~1.6MB）；若不愿入库，可 gitignore `static/fonts/` 并在部署时跑 `scripts/fetch_fonts.sh`（缺文件时 UI 自动回落系统字体，不报错）。
- `brotli`/`fonttools` 仅在需自行子集化时才用；本方案直接取 Fontsource 已子集 woff2，运行时无额外依赖。
