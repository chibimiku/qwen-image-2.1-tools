# -*- coding: utf-8 -*-
"""核对总结文档里的数字是否与实验包原始评分一致。

  python tools/verify_experiment_summary.py

做法：从 exp 的 scores.csv 现算各组均值/可接受率、泄露率，再到
docs/EXPERIMENT-style-migration-RESULTS.md 里检查这些数字是否出现（或反之）。
任何对不上的都列出来 —— 文档里的数字必须能从原始评分复算出来。
"""
from __future__ import annotations

import csv
import pathlib
import sys
from collections import defaultdict

ROOT = pathlib.Path(__file__).resolve().parent.parent
PKG = ROOT / "exp" / "style-reference-migration-20260927"
DOC = ROOT / "docs" / "EXPERIMENT-style-migration-RESULTS.md"
LIMIT = ROOT / "docs" / "PROMPT-LENGTH-LIMIT.md"


def acc(c, l, q):
    return c is not None and l is not None and q is not None and c >= 4 and l <= 1 and q >= 3


def num(v):
    try:
        return int(v)
    except Exception:                                                   # noqa: BLE001
        return None


def main() -> int:
    if not (PKG / "analysis" / "scores.csv").exists():
        print(f"缺原始评分：{PKG / 'analysis' / 'scores.csv'}")
        return 2
    with (PKG / "analysis" / "scores.csv").open(encoding="utf-8-sig") as fh:
        rows = list(csv.DictReader(fh))
    doc = DOC.read_text(encoding="utf-8")
    lim = LIMIT.read_text(encoding="utf-8")

    print(f"原始评分 {len(rows)} 行；总结 {len(doc)} 字符，长度上限文档 {len(lim)} 字符")

    by_mode = defaultdict(list)
    by_style_mode = defaultdict(list)
    for r in rows:
        by_mode[r["mode"]].append(r)
        by_style_mode[(r["style"], r["mode"])].append(r)

    def mean(items, key):
        v = [num(x[key]) for x in items if num(x[key]) is not None]
        return round(sum(v) / len(v), 2) if v else None

    def rate(items):
        ok = n = 0
        for x in items:
            c, l, q = num(x["content_0_5"]), num(x["leakage_0_5"]), num(x["quality_0_5"])
            if None in (c, l, q):
                continue
            n += 1
            ok += 1 if acc(c, l, q) else 0
        return round(ok / n * 100) if n else None

    print("\n=== 各组（现算 vs 文档里是否出现）===")
    fails = []
    for mode in ("A_content_only", "B_text_short", "C_ref_only", "D_ref_long",
                 "E_ref_short", "F_ref_priority", "G_dual_content_only",
                 "H_dual_style_priority"):
        items = by_mode.get(mode)
        if not items:
            continue
        s, c = mean(items, "style_0_5"), mean(items, "content_0_5")
        l, q, a = mean(items, "leakage_0_5"), mean(items, "quality_0_5"), rate(items)
        key = mode.split("_")[0]
        # 文档里这组的行是否同时含 style/content 两个数
        hit = (f"| {s} | {c} |" in doc) or (f"{s}" in doc and f"{c}" in doc)
        print(f"  {key}: n={len(items):<3} S={s:<5} C={c:<5} L={l:<5} Q={q:<5} "
              f"可接受={a}%   文档命中={hit}")
        if not hit:
            fails.append(f"{key} 的 S={s}/C={c} 没在文档里对上")

    print("\n=== 逐风格 × 组的可接受率（抽验总结里点名的几项）===")
    checks = [
        ("waterink-style", "E_ref_short", 67),
        ("waterink-style", "F_ref_priority", 44),
        ("sakurapion-style", "D_ref_long", 0),
        ("sakurapion-style", "E_ref_short", 33),
        ("fuzichoco-v2", "E_ref_short", 11),
        ("tinkle-style", "F_ref_priority", 44),
        ("renian", "D_ref_long", 0),
        ("renian", "E_ref_short", 0),
        ("renian", "F_ref_priority", 0),
    ]
    for style, mode, want in checks:
        items = by_style_mode.get((style, mode))
        got = rate(items) if items else None
        ok = got == want
        print(f"  {'OK  ' if ok else 'FAIL'} {style:<18}{mode:<18} 现算={got}%  文档写={want}%")
        if not ok:
            fails.append(f"{style}/{mode} 可接受率 现算={got}% 文档={want}%")

    print("\n=== 泄露≥3 比例（总结第 5 节的表）===")
    for style in ("waterink-style", "fuzichoco-v2", "tinkle-style",
                  "sakurapion-style", "renian"):
        items = [r for r in rows if r["style"] == style
                 and r["mode"] in ("C_ref_only", "D_ref_long", "E_ref_short", "F_ref_priority")]
        lk = [num(r["leakage_0_5"]) for r in items if num(r["leakage_0_5"]) is not None]
        ge3 = round(sum(1 for v in lk if v >= 3) / len(lk) * 100) if lk else None
        cm = mean(items, "content_0_5")
        print(f"  {style:<18} n={len(items)}  泄露≥3={ge3}%  内容均值={cm}")
        if f"{ge3}%" not in doc:
            fails.append(f"{style} 的泄露≥3={ge3}% 没在文档里出现")

    print("\n=== 长度上限文档里的数字 ===")
    for probe, where in (("9216", "位置表长"), ("9100", "纯文本实测上限"),
                         ("1024", "1024² 参考图 vision token")):
        print(f"  {'OK  ' if probe in lim and probe in doc else 'check'} "
              f"{probe}（{where}）在 PROMPT-LENGTH-LIMIT={'有' if probe in lim else '无'}, "
              f"在总结={'有' if probe in doc else '无'}")

    print()
    print(f"结论: {'通过 —— 文档数字与原始评分一致' if not fails else '%d 处对不上' % len(fails)}")
    for f in fails:
        print("   -", f)
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
