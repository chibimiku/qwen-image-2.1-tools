#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""实验收尾：自动标签 + 盲评表 + 汇总报告。

方案要求「评分者看不到变体」。这里提供两条互补的评分途径：

  1. **视觉盲评表**（主）：按任务把 12 个 seed 拼成大表，每行一个 seed、
     列顺序固定但**不标变体字母**，只看图判「多/少/融合肢体」。
     优点：直接把"多腿"给判据，不依赖 VLM 数肢体的能力。
  2. **审图模型自动标签**（辅）：调 service/anatomy_check 的 2.2B 模型，
     输出 PASS/FAIL + confidence。方案已明确它**不是真值**（实测它连
     "腿绞成一团"都可能 PASS），所以只作辅助，报告里如实标注。

最后 join 回 variant 出汇总表。
"""
import base64
import io
import json
import os
import random
import sys
from collections import defaultdict

sys.path.insert(0, "/root/qwen-image-2.1/service")
from PIL import Image, ImageDraw                                # noqa: E402

OUT = "/root/exp_out"
SHEETS = f"{OUT}/sheets"
os.makedirs(SHEETS, exist_ok=True)

manifest = [json.loads(l) for l in open(f"{OUT}/manifest.jsonl", encoding="utf-8") if l.strip()]
by_task = defaultdict(list)
for r in manifest:
    by_task[r["task"]].append(r)

ORDER = ["A", "B", "C", "D"]
LABEL = {"A": "A 默认", "B": "B 负向+2.0", "C": "C 负向+2.5", "D": "D 改写"}

# ---------- 1. 自动标签（辅助） ----------
print("=== 1. 审图模型自动标签（辅助判据，非真值）===")
from anatomy_check import inspect_image                              # noqa: E402

auto = {}
for r in manifest:
    try:
        im = Image.open(r["path"]).convert("RGB")
    except Exception as e:                                           # noqa: BLE001
        auto[r["blind_id"]] = {"passed": None, "reason": f"打不开 {e}"}
        continue
    v = inspect_image(im, "")
    auto[r["blind_id"]] = {"passed": v.get("passed"), "label": v.get("label"),
                           "confidence": v.get("confidence"), "reason": (v.get("reason") or "")[:70]}
with open(f"{OUT}/auto_labels.jsonl", "w", encoding="utf-8") as fh:
    for r in manifest:
        fh.write(json.dumps({**r, **auto.get(r["blind_id"], {})}, ensure_ascii=False) + "\n")

# ---------- 2. 盲评对比表 ----------
print("=== 2. 生成盲评对比表 ===")
CELL = 300
for task, rows in by_task.items():
    seeds = sorted({r["seed"] for r in rows})
    # 每行一个 seed，列按 A B C D 顺序但表头不写变体
    W = CELL * 4 + 20
    H = CELL * len(seeds) + 46
    sheet = Image.new("RGB", (W, H), (24, 26, 32))
    d = ImageDraw.Draw(sheet)
    d.text((10, 8), f"任务 {task} —— 每行同一 seed，列从左到右为 ①②③④（顺序固定，不标变体）",
           fill=(220, 228, 238))
    d.text((10, 26), "判据：明显的多腿/多臂/融合肢体 → 记 1；否则 0",
           fill=(150, 160, 175))
    for ri, seed in enumerate(seeds):
        for ci, vk in enumerate(ORDER):
            hit = next((r for r in rows if r["seed"] == seed and r["variant"] == vk), None)
            x, y = ci * CELL + 10, 46 + ri * CELL
            if not hit:
                continue
            try:
                im = Image.open(hit["path"]).convert("RGB")
                im.thumbnail((CELL - 12, CELL - 12))
                sheet.paste(im, (x, y))
            except Exception:                                        # noqa: BLE001
                pass
            d.text((x + 2, y + CELL - 20), f"{ci + 1}", fill=(120, 200, 255))
            d.text((x + 24, y + CELL - 20), f"seed {seed}", fill=(140, 150, 165))
    p = f"{SHEETS}/blind_{task}.png"
    sheet.save(p)
    print(f"  {p}  ({sheet.width}x{sheet.height})")

# 每变体一张抽样表（用于整体观感对比，仍不写变体）
for vk in ORDER:
    rows = [r for r in manifest if r["variant"] == vk]
    random.seed(7)
    pick = random.sample(rows, min(12, len(rows)))
    W, H = CELL * 4 + 20, CELL * 3 + 40
    sheet = Image.new("RGB", (W, H), (24, 26, 32))
    d = ImageDraw.Draw(sheet)
    d.text((10, 10), f"组 {vk}（抽样 {len(pick)} 张）", fill=(220, 228, 238))
    for i, r in enumerate(pick):
        x, y = (i % 4) * CELL + 10, 40 + (i // 4) * CELL
        try:
            im = Image.open(r["path"]).convert("RGB")
            im.thumbnail((CELL - 12, CELL - 12))
            sheet.paste(im, (x, y))
        except Exception:                                            # noqa: BLE001
            pass
        d.text((x + 2, y + CELL - 18), f"{r['task']}/{r['seed']}", fill=(140, 200, 255))
    p = f"{SHEETS}/variant_{vk}.png"
    sheet.save(p)
    print(f"  {p}")

# ---------- 3. 汇总（join 回 variant） ----------
print("=== 3. 汇总 ===")
agg = defaultdict(lambda: {"n": 0, "auto_fail": 0, "t": [], "conf_sum": 0.0, "conf_n": 0})
for r in manifest:
    a = auto.get(r["blind_id"], {})
    k = (r["task"], r["variant"])
    g = agg[k]
    g["n"] += 1
    if a.get("passed") is False:
        g["auto_fail"] += 1
    g["t"].append(r["elapsed_s"])
    if a.get("confidence"):
        g["conf_sum"] += a["confidence"]
        g["conf_n"] += 1
    g["variant"] = r["variant"]
    g["task"] = r["task"]

lines = []
lines.append("# CFG / negative prompt 对照实验 —— 结果\n")
lines.append(f"样本：3 类任务 × 4 组 × 12 个 seed = {len(manifest)} 张，"
             f"{manifest[0]['size']}，{manifest[0]['steps']} 步，固定参考图与 prompt。\n")
lines.append("## 组别定义\n")
lines.append("| 组 | negative prompt | true_cfg_scale | 正向 prompt |")
lines.append("|---|---|---|---|")
lines.append("| A | 无 | 1.0（官方默认） | 直接描述 |")
lines.append("| B | 项目自编人体负面词 | 2.0 | 同 A |")
lines.append("| C | 同 B | 2.5 | 同 A |")
lines.append("| D | 无 | 1.0 | **按官方 PE 方法改写**（操作句首/只声明该变的/一揽子保持句） |")
lines.append("")
lines.append("## 自动标签（2.2B 审图模型，**辅助判据，不是真值**）\n")
lines.append("| 任务 | 组 | 张数 | 判 FAIL | FAIL 率 | 平均耗时 | 平均置信度 |")
lines.append("|---|---|---|---|---|---|---|")
for task in by_task:
    for vk in ORDER:
        g = agg.get((task, vk))
        if not g:
            continue
        avg_t = sum(g["t"]) / len(g["t"]) if g["t"] else 0
        avg_c = g["conf_sum"] / g["conf_n"] if g["conf_n"] else 0
        lines.append(f"| {task} | {LABEL[vk]} | {g['n']} | {g['auto_fail']} | "
                     f"{100 * g['auto_fail'] / max(1, g['n']):.0f}% | {avg_t:.1f}s | {avg_c:.2f} |")
lines.append("")
lines.append("## 耗时（客观数据，不受评分影响）\n")
lines.append("| 任务 | A | B | C | D |")
lines.append("|---|---|---|---|---|")
for task in by_task:
    row = [f"| {task} "]
    for vk in ORDER:
        g = agg.get((task, vk))
        row.append(f"| {sum(g['t']) / len(g['t']):.1f}s " if g and g["t"] else "| — ")
    lines.append("".join(row) + "|")
lines.append("")
lines.append("## 盲评表（人看这个）\n")
for task in by_task:
    lines.append(f"- `sheets/blind_{task}.png` —— 每行同一 seed，列顺序固定 A→D 但**不标字母**")
lines.append("- `sheets/variant_*.png` —— 抽样看各组整体观感")
lines.append("")
lines.append("> 判据（按方案）：明显的多/少/融合/断裂肢体记 1，否则 0。"
             "12 对样本**不足以声称统计显著**，只当去留决策的工程证据。")
lines.append("")
lines.append("## 判定门槛（方案第四节，照抄供对照）\n")
lines.append("只有同时满足才考虑把 CFG 方案提升出高级设置：")
lines.append("1. B 或 C 在三类任务中至少两类的异常率，相对 A 稳定下降 **≥30%**；")
lines.append("2. prompt 跟随 / 身份 / 审美中位数下降不超过 **0.5 分**；")
lines.append("3. 用户能接受耗时增幅；")
lines.append("4. 换一批 seed 复测方向一致。")
lines.append("")

open(f"{OUT}/REPORT.md", "w", encoding="utf-8").write("\n".join(lines))
print(f"\n  {OUT}/REPORT.md")
print(f"  {OUT}/auto_labels.jsonl")
print(f"  {OUT}/sheets/  （{len(os.listdir(SHEETS))} 张表）")
