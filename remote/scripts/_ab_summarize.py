#!/usr/bin/env python3
"""CFG/负面提示词 A/B 实验：把 auto_labels.jsonl 汇成"异常率下降"判据表。

方案（docs/CFG-NEGATIVE-AB-TEST.md 第四节）要求 B 或 C 相对 A 的异常率
至少两类任务下降 ≥30% 才考虑把 CFG 提升出高级设置。这里只算这张表，
不做结论 —— 结论要结合人看盲评表 + 耗时。
"""
import collections
import json
import sys

P = sys.argv[1] if len(sys.argv) > 1 else "/root/exp_out/auto_labels.jsonl"
rows = [json.loads(l) for l in open(P, encoding="utf-8") if l.strip()]
print("样本数:", len(rows), "\n")

ORDER = ["A", "B", "C", "D"]
agg = collections.defaultdict(lambda: {"n": 0, "fail": 0, "t": 0.0, "conf": [], "none": 0})
for r in rows:
    g = agg[(r["task"], r["variant"])]
    g["n"] += 1
    g["t"] += r.get("elapsed_s") or 0
    if r.get("passed") is False:
        g["fail"] += 1
    elif r.get("passed") is None:
        g["none"] += 1
    if r.get("confidence"):
        g["conf"].append(r["confidence"])

tasks = sorted({r["task"] for r in rows})

print("== 自动判 FAIL 的数量（2.2B 审图模型，辅助判据，不是真值）==")
print("%-8s %-4s %5s %6s %8s %8s" % ("任务", "组", "张数", "FAIL", "FAIL率", "平均耗时"))
for t in tasks:
    for v in ORDER:
        g = agg.get((t, v))
        if not g:
            continue
        print("%-8s %-4s %5d %6d %7.0f%% %7.1fs"
              % (t, v, g["n"], g["fail"], 100 * g["fail"] / max(1, g["n"]), g["t"] / max(1, g["n"])))
    print()

print("== 相对 A 的异常率变化（正数=下降，负数=变差）==")
print("%-8s %-4s %10s %10s %8s" % ("任务", "组", "FAIL率", "相对A变化", "达标?"))
for t in tasks:
    a = agg.get((t, "A"))
    ar = a["fail"] / max(1, a["n"]) if a else None
    for v in ORDER:
        g = agg.get((t, v))
        if not g:
            continue
        r = g["fail"] / max(1, g["n"])
        if ar is None or ar == 0:
            rel, verdict = "n/a（A 无异常，无下降空间）", "—"
        else:
            rel = "%.0f%%" % (100 * (ar - r) / ar)
            verdict = "达标" if (ar - r) / ar >= 0.30 else "未达标"
        print("%-8s %-4s %9.0f%% %10s %8s" % (t, v, 100 * r, rel, verdict))
    print()

print("== 置信度（低置信度说明模型自己也不确定，FAIL 更不可信）==")
for t in tasks:
    parts = []
    for v in ORDER:
        g = agg.get((t, v))
        if not g:
            continue
        c = g["conf"]
        parts.append("%s=%.2f(n=%d)" % (v, sum(c) / len(c) if c else 0, len(c)))
    print("  %-8s %s" % (t, "  ".join(parts)))

print("\n== 无结论的样本（passed 为 None，通常打不开图）==")
tot_none = sum(g["none"] for g in agg.values())
print("  %d 张" % tot_none)
