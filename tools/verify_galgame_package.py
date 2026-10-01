# -*- coding: utf-8 -*-
"""盘点 galgame 实验包的**实际内容**，用来核对文档里的说法有没有夸大。

  python tools/verify_galgame_package.py

产出：目录清单、manifest 分组统计、成品逐张信息，以及"文档声称 vs 实测"的对照。
"""
from __future__ import annotations

import json
import pathlib
import sys
from collections import Counter

ROOT = pathlib.Path(__file__).resolve().parent.parent
EXP = ROOT / "exp" / "galgame-cg-20260928"


def main() -> int:
    print("=== 目录实际内容（不含 refs/）===")
    for p in sorted(EXP.rglob("*")):
        if p.is_file() and "refs" not in p.parts and p.suffix in (
                ".png", ".txt", ".jsonl", ".py"):
            print(f"  {p.stat().st_size:>10,} B  {p.relative_to(EXP)}")

    mf = EXP / "manifest.jsonl"
    if not mf.exists():
        print("缺 manifest.jsonl")
        return 1
    recs = [json.loads(l) for l in mf.read_text(encoding="utf-8").splitlines() if l.strip()]
    print(f"\n=== manifest：{len(recs)} 条 ===")
    print("  按 phase :", dict(Counter(r.get("phase") or "(bracket)" for r in recs)))
    print("  按 status:", dict(Counter(r["status"] for r in recs)))

    print("\n=== 已入库的成品（story- / fix-）===")
    fin = [r for r in recs if r["status"] == "ok"
           and (r["name"].startswith("story-") or r["name"].startswith("fix-"))]
    for r in sorted(fin, key=lambda x: x["name"]):
        tag = "  [修补]" if r["name"].startswith("fix-") else ""
        print("  {:<26} {:<11} seed={:<10} {:>6.1f}s{}".format(
            r["name"], str(r.get("size")), str(r.get("seed")), r.get("seconds") or 0, tag))
    print(f"  合计 {len(fin)} 张")

    print("\n=== 文档声称 vs 实测 ===")
    st = [r for r in recs if r.get("phase") == "story"]
    ct = [r for r in recs if r.get("phase") == "control"]
    sd = [r for r in recs if r.get("phase") == "seeds"]
    bo = [r for r in recs if r.get("phase") == "boost"]
    so = [r for r in recs if r.get("phase") == "styleonly"]

    def claim(ok: bool, text: str, detail: str = "") -> int:
        print(("  OK   " if ok else "  ▲    ") + text + (("  " + detail) if detail else ""))
        return 0 if ok else 1

    bad = 0
    # 成品是 12 幕；story-* 12 张 + fix-* 3 张 = 15 个 PNG，因为 3 幕的
    # **问题版与修补版都留在盘上**便于对比，不是 15 幕。
    story_only = [r for r in fin if r["name"].startswith("story-")]
    fix_only = [r for r in fin if r["name"].startswith("fix-")]
    bad += claim(len(story_only) == 12, "正片 12 幕", f"story-* = {len(story_only)}")
    bad += claim(len(fix_only) == 3, "3 幕有修补版", f"fix-* = {len(fix_only)}")
    bad += claim(sorted({r["seed"] for r in st}) == [42],
                 "正片只跑了 seed 42（文档里'每场景 3 seed'是建议，正片未执行）",
                 f"实测 seed {sorted({r['seed'] for r in st})}")
    bad += claim(len(sd) == 3, "跨 seed 稳定性单独跑了 3 个 seed", f"实测 {len(sd)}")
    bad += claim(len(ct) == 3, "对照组 3 个场景（02/03/08）",
                 f"实测 {sorted({r['scene_id'] for r in ct})}")
    # --phase boost 只有 3 条；fix 相里那条补的 02-cafe 记在 fix 下。
    # （别用 r["boost"] 字段统计 —— 修补版也带 boost=True，会数出 10 条）
    boost_phase = [r for r in recs if r.get("phase") == "boost"]
    boost_in_fix = [r for r in recs
                    if r.get("phase") == "fix" and "02-cafe" in r["name"]]
    bad += claim(len(boost_phase) == 3 and len(boost_in_fix) == 1,
                 "强化样式词：--phase boost 3 张 + fix 相里补的 02-cafe 1 张",
                 f"boost={len(boost_phase)} fix内={len(boost_in_fix)}")
    bad += claim(len(so) == 3, "只给画风图的对照组 3 张", f"实测 {len(so)}")

    # 失败要区分三种：
    #   a) 驱动解析响应写错导致的失败 —— 同尺寸后来补跑成功，已解决
    #   b) 尺寸用错导致的失败 —— 尺寸后来换成 64 倍数，任务本身已废弃
    #   c) 真正没解决的
    # 不把 (a)(b) 混进"全部成功"里报，也不假装它们不存在。
    OBSOLETE = {"bracket-1792x1008", "bracket-1920x1104"}   # 非 64 倍数，已废弃
    failed = [r for r in recs if r["status"] != "ok"]
    ok_names = {r["name"] for r in recs if r["status"] == "ok"}
    resolved = [r["name"] for r in failed if r["name"] in ok_names]
    obsolete = [r["name"] for r in failed if r["name"] in OBSOLETE]
    unresolved = [r["name"] for r in failed
                  if r["name"] not in ok_names and r["name"] not in OBSOLETE]
    bad += claim(not unresolved, "没有未解决的失败",
                 f"未解决：{unresolved}" if unresolved else
                 f"失败 {len(failed)} 条 = 已补跑 {len(resolved)} + 已废弃 {len(obsolete)}")

    vf = EXP / "autostart-verify.txt"
    bad += claim(vf.exists(), "自启验证结果已落盘", vf.name if vf.exists() else "缺")
    rd = EXP / "README.md"
    bad += claim(rd.exists(), "包内 README 存在", rd.name if rd.exists() else "缺")

    print()
    print("结论:", "文档与实测一致" if bad == 0 else f"{bad} 处对不上，需改文档")
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
