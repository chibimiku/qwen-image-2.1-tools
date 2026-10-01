# -*- coding: utf-8 -*-
"""把三批识图的 JSONL 合并、去重、按严重度排出待修清单。

  python exp/galgame-cg-20260928/merge_qa.py            # 合并并写 qa/merged.json + 打印
  python exp/galgame-cg-20260928/merge_qa.py --csv      # 同时写一份 CSV

多批结果里同一张图可能被不同批次看到**不同的缺陷**（实测就有：
一批报了手部，另一批报了鞋跟）。所以合并时**按缺陷条目去重**，
而不是按"每张图取一条"，否则会丢掉别的批次发现的真问题。
"""
from __future__ import annotations

import argparse
import csv
import json
import pathlib
import re
import sys
from collections import Counter

EXP = pathlib.Path(__file__).resolve().parent
QA = EXP / "qa"
SEV_ORDER = {"p0": 0, "p1": 1, "p2": 2, "p3": 3, "none": 9, "?": 8}


def parse_line(line: str) -> dict | None:
    line = line.strip()
    if not line.startswith("{"):
        return None
    try:
        return json.loads(line)
    except Exception:                                                   # noqa: BLE001
        # 容忍行内混入的前后文字
        i, j = line.find("{"), line.rfind("}")
        if i >= 0 and j > i:
            try:
                return json.loads(line[i:j + 1])
            except Exception:                                           # noqa: BLE001
                return None
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", action="store_true")
    a = ap.parse_args()

    merged: dict[str, dict] = {}
    files = sorted(QA.glob("result-*.jsonl"))
    print(f"读 {len(files)} 个结果文件：")
    for f in files:
        n = 0
        for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
            obj = parse_line(line)
            if not obj or "file" not in obj:
                continue
            name = str(obj["file"]).removesuffix(".png")
            n += 1
            rec = merged.setdefault(name, {
                "name": name, "people_count": obj.get("people_count"),
                "defects": [], "notes": [], "sources": [],
                "seen_ok": False,
            })
            if f.name not in rec["sources"]:
                rec["sources"].append(f.name)
            if obj.get("note"):
                rec["notes"].append(obj["note"])
            if obj.get("ok"):
                rec["seen_ok"] = True
            for d in (obj.get("defects") or []):
                rec["defects"].append(d)
        print(f"  {f.name}: {n} 条")

    # 按 (code, severity) 去重；同一 code 不同位置保留位置更具体的那个
    for rec in merged.values():
        uniq: dict[tuple, dict] = {}
        for d in rec["defects"]:
            key = (str(d.get("code", "?")).upper(), str(d.get("severity", "?")).upper())
            prev = uniq.get(key)
            if prev is None or len(str(d.get("what", ""))) > len(str(prev.get("what", ""))):
                uniq[key] = d
        rec["defects"] = sorted(uniq.values(),
                                key=lambda x: (SEV_ORDER.get(str(x.get("severity", "?")).lower(), 8),
                                               str(x.get("code"))))
        worst = "none"
        for d in rec["defects"]:
            s = str(d.get("severity", "?")).lower()
            if SEV_ORDER.get(s, 8) < SEV_ORDER.get(worst, 9):
                worst = s
        rec["worst"] = worst
        rec["ok"] = not rec["defects"]

    QA.mkdir(parents=True, exist_ok=True)
    (QA / "merged.json").write_text(
        json.dumps(list(merged.values()), ensure_ascii=False, indent=2), encoding="utf-8")

    ok = [r for r in merged.values() if r["ok"]]
    bad = [r for r in merged.values() if not r["ok"]]
    print(f"\n合并后 {len(merged)} 张：合格 {len(ok)}，有缺陷 {len(bad)}")
    print(f"  合格：{', '.join(sorted(r['name'] for r in ok))}")

    codes = Counter(d.get("code") for r in bad for d in r["defects"])
    sevs = Counter(str(d.get("severity", "?")).upper() for r in bad for d in r["defects"])
    print(f"  严重度：{dict(sevs)}")
    print(f"  代码分布：{dict(codes.most_common())}")

    print("\n=== 待修清单（按严重度）===")
    for r in sorted(bad, key=lambda x: (SEV_ORDER.get(x["worst"], 8), x["name"])):
        ds = "；".join(f"{d.get('code')}/{d.get('severity')} {str(d.get('what'))[:34]}"
                       for d in r["defects"])
        print(f"  {r['name']:<24} [{r['worst'].upper():<2}] 人数={r['people_count']}  {ds}")

    if a.csv:
        p = QA / "merged.csv"
        with p.open("w", encoding="utf-8", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["file", "worst", "people_count", "code", "severity", "where", "what",
                        "confident", "sources"])
            for r in bad:
                for d in r["defects"]:
                    w.writerow([r["name"], r["worst"], r["people_count"], d.get("code"),
                                d.get("severity"), d.get("where"), d.get("what"),
                                d.get("confident"), "|".join(r["sources"])])
        print(f"\nCSV -> {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
