"""命令行入口: python -m src.run_cli 肉桂 [更多药材...] [--disease 疾病名]

每味药材跑完整管道并导出 outputs/<拼音或查询>.xlsx。
提供 --disease 时, 额外做 疾病靶点 + 药物×疾病 交集 (T1)。
"""
from __future__ import annotations

import sys
import re

from .excel_export import export
from .pipeline import run_herb


def _safe(name: str) -> str:
    return re.sub(r"[^\w\-]+", "_", name).strip("_") or "herb"


def main(argv: list[str]) -> int:
    disease = None
    if "--disease" in argv:
        i = argv.index("--disease")
        disease = argv[i + 1] if i + 1 < len(argv) else None
        argv = argv[:i] + argv[i + 2:]
    if not argv:
        print("用法: python -m src.run_cli <药材名> [药材名...] [--disease 疾病名]")
        return 2
    for query in argv:
        print(f"\n===== {query} =====")
        result = run_herb(query, progress=lambda m: print("  " + m), disease=disease)
        if not result.found:
            print("  " + result.message)
            continue
        out = export(result, f"outputs/{_safe(result.herb.get('pinyin') or query)}.xlsx")
        print(f"  -> {result.message}")
        print(f"  -> Excel: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
