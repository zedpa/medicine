"""命令行入口: python -m src.run_cli 肉桂 [更多药材...]

每味药材跑完整管道并导出 outputs/<拼音或查询>.xlsx。
"""
from __future__ import annotations

import sys
import re

from .excel_export import export
from .pipeline import run_herb


def _safe(name: str) -> str:
    return re.sub(r"[^\w\-]+", "_", name).strip("_") or "herb"


def main(argv: list[str]) -> int:
    if not argv:
        print("用法: python -m src.run_cli <药材名> [药材名...]")
        return 2
    for query in argv:
        print(f"\n===== {query} =====")
        result = run_herb(query, progress=lambda m: print("  " + m))
        if not result.found:
            print("  " + result.message)
            continue
        out = export(result, f"outputs/{_safe(result.herb.get('pinyin') or query)}.xlsx")
        print(f"  -> {result.message}")
        print(f"  -> Excel: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
