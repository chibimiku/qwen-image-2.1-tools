#!/usr/bin/env python3
"""复核：当初那批"144 张全 PASS"到底是模型在判，还是加载失败 fail-open。

两种情况的汇总表长得一模一样（都是 FAIL 0%、confidence 0.00），但含义完全不同：
  · 模型在判 → 全 PASS 说明"这组图没有它认得出的异常"
  · 加载失败 → 全 PASS 是 fail-open 的默认值，**没有任何信息**
判据是 label：模型答过话 label 会是 pass/fail，没答过会是 unavailable。
"""
import collections
import json

P = "/root/exp_out/auto_labels.jsonl"
rows = [json.loads(l) for l in open(P, encoding="utf-8") if l.strip()]
print("样本:", len(rows))
print("label 分布:", dict(collections.Counter(r.get("label") for r in rows)))
print("passed 分布:", dict(collections.Counter(r.get("passed") for r in rows)))
conf = [r.get("confidence") for r in rows]
print("confidence: 全为 0 吗？", all(c == 0 for c in conf), " 取值集合:", sorted(set(conf))[:5])
print("reason 前 3 条:")
for r in rows[:3]:
    print("  -", (r.get("reason") or "")[:110])

unavail = sum(1 for r in rows if r.get("label") == "unavailable")
print()
if unavail == len(rows):
    print("结论：**全部 unavailable —— 模型从没答过话**。")
    print("      这批自动标签没有任何信息量，不能当作'异常率'使用。")
elif unavail:
    print("结论：%d/%d 未作答，混了两种来源，汇总表不可用。" % (unavail, len(rows)))
else:
    print("结论：模型确实逐张作答了，labels 可用作辅助判据。")
