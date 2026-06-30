#!/usr/bin/env bash
# 自托管字体: 从 Fontsource(jsDelivr CDN)拉取 woff2 到 static/fonts/,
# 供 Streamlit 静态服务 (app/static/fonts/*) 引用 -> 内网/离线部署免依赖 Google Fonts。
# 重新拉取: bash scripts/fetch_fonts.sh
set -euo pipefail
cd "$(dirname "$0")/.."
DST="static/fonts"
mkdir -p "$DST"
BASE="https://cdn.jsdelivr.net/fontsource/fonts"

dl() {  # dl <url> <out>
  echo "  -> $2"
  curl -fsSL --noproxy '*' -o "$DST/$2" "$1"
}

echo "Inter (latin, UI 正文/控件):"
for w in 400 500 600 700; do dl "$BASE/inter@latest/latin-$w-normal.woff2" "inter-$w.woff2"; done

echo "Space Mono (latin, 计量/编号):"
for w in 400 700; do dl "$BASE/space-mono@latest/latin-$w-normal.woff2" "spacemono-$w.woff2"; done

echo "Noto Serif SC (简体中文子集, 标题/招牌; 单字重复用于全部标题):"
dl "$BASE/noto-serif-sc@latest/chinese-simplified-600-normal.woff2" "notoserifsc-600.woff2"

echo "完成。文件:"
ls -la "$DST"
