# -*- coding: utf-8 -*-
"""校验要入库的逐图评分文件：行数、列、内容完整性。

  python tools/verify_scoring_files.py

这些文件进了版本库，就是给别人读的 —— 所以提交前确认它们不是半截的：
scores.csv 必须有 300 个数据行、四维分齐全；anime 是 30 行；
errors.csv 的 issue 分类要和分数对得上。
"""
from __future__ import annotations

import csv
import json
import pathlib
import sys
from collections import Counter

ROOT = pathlib.Path(__file__).resolve().parent.parent
PKG = ROOT / "exp" / "style-reference-migration-20260927"

CHECKS = [
    ("analysis/scores.csv", 300),
    ("analysis/errors.csv", None),
    ("analysis/ratings-filled.csv", 300),
    ("analysis/ratings-template.csv", 300),
    ("exec/anime/scores.csv", 30),
]


def main() -> int:
    bad = []
    print("=== CSV 行数与列 ===")
    for rel, want in CHECKS:
        p = PKG / rel
        if not p.exists():
            print(f"  MISSING {rel}")
            bad.append(rel)
            continue
        with p.open(encoding="utf-8-sig", newline="") as fh:
            rows = list(csv.DictReader(fh))
        cols = list(rows[0].keys()) if rows else []
        ok = want is None or len(rows) == want
        print(f"  {'OK  ' if ok else 'FAIL'} {rel:<34} {len(rows):>4} 行 × {len(cols):>2} 列")
        if want is not None and not ok:
            bad.append(f"{rel} 行数 {len(rows)} != {want}")

    print("\n=== 四维分完整性（不能有空）===")
    for rel, _ in CHECKS:
        p = PKG / rel
        if not p.exists() or "scores" not in rel:
            continue
        with p.open(encoding="utf-8-sig", newline="") as fh:
            rows = list(csv.DictReader(fh))
        dims = ("style_0_5", "content_0_5", "leakage_0_5", "quality_0_5")
        blanks = [r.get("id", "?") for r in rows
                  if any(str(r.get(d, "")).strip() == "" for d in dims)]
        print(f"  {rel:<34} 空分单元 {len(blanks)}")
        if blanks:
            bad.append(f"{rel} 有 {len(blanks)} 个单元缺分")

    print("\n=== errors.csv 的问题分类 ===")
    ep = PKG / "analysis" / "errors.csv"
    if ep.exists():
        with ep.open(encoding="utf-8-sig", newline="") as fh:
            er = list(csv.DictReader(fh))
        for k, v in Counter(r["issue"] for r in er).most_common():
            print(f"  {k:<16} {v}")
        print(f"  合计 {len(er)} 行")

    print("\n=== summary.json 结构 ===")
    for rel in ("analysis/summary.json", "exec/anime/summary.json"):
        p = PKG / rel
        if not p.exists():
            print(f"  MISSING {rel}")
            continue
        d = json.loads(p.read_text(encoding="utf-8"))
        print(f"  {rel:<28} 顶层键 {sorted(d)[:6]}")

    print()
    print(f"结论: {'通过' if not bad else '%d 项有问题' % len(bad)}")
    for b in bad:
        print("   -", b)
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
