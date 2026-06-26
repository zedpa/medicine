#!/usr/bin/env bash
# 下载 BATMAN-TCM 2.0 dump 到 data/raw/batman/ 并生成 MANIFEST(含校验和)。
# 部署时在项目根目录执行一次即可。
set -euo pipefail
cd "$(dirname "$0")/.."

BASE="http://batman2.cloudna.cn/downloadApiFile/data/browser"
DIR="data/raw/batman"
FILES=(herb_browse.txt known_browse_by_ingredients.txt.gz predicted_browse_by_ingredients.txt.gz)

mkdir -p "$DIR"
for f in "${FILES[@]}"; do
  if [ -s "$DIR/$f" ]; then echo "已存在, 跳过: $f"; continue; fi
  echo "下载 $f ..."
  curl -fSL --retry 3 -m 300 "$BASE/$f" -o "$DIR/$f"
done

{
  echo "# BATMAN-TCM 2.0 dump"
  echo "source_base: $BASE"
  echo "download_date: $(date +%F)"
  echo "files:"
  for f in "${FILES[@]}"; do
    if command -v sha256sum >/dev/null; then sha=$(sha256sum "$DIR/$f" | awk '{print $1}');
    else sha=$(shasum -a 256 "$DIR/$f" | awk '{print $1}'); fi
    sz=$(wc -c < "$DIR/$f" | tr -d ' ')
    echo "  - name: $f"; echo "    sha256: $sha"; echo "    bytes: $sz"
  done
} > "$DIR/MANIFEST"
echo "完成。已写入 $DIR/MANIFEST"
