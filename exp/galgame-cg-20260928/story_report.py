# -*- coding: utf-8 -*-
"""把 STORY.md 要的 CG 与实际出图对齐，出一份差异表。

  python exp/galgame-cg-20260928/story_report.py

用途：出图之后对账 —— 哪些按剧本出来了、哪些被模型改写了、哪些要重做。
这张表会写进 STORY-GEN-REPORT.md，不靠记忆。
"""
from __future__ import annotations

import json
import pathlib
import sys

EXP = pathlib.Path(__file__).resolve().parent
STORY = EXP / "story"
LOG = EXP / "story-gen-log.jsonl"

# 人工判定结果（playthrough 后填）——与剧本要求的对照
VERDICT = {
    "01-entrance":       ("ok",     "门框/衣架/里屋那件粉裙的钩子都在"),
    "02-measure":        ("good",   "改成单人视角后成立；手与布尺成为主体，客人的肩在右侧虚焦"),
    "03-the-question":   ("ok",     "抬眼 + 笔停在记事本上的动作对"),
    "04-unbutton":       ("broken", "要求她解**另一个人**的扣子，画成她在扣自己的衬衫并对镜头笑"),
    "07b-three-fitting": ("ok",     "两人各一次、特征正确、无星空泄露；布尺语义修好了"),
    "10a-unhook":        ("broken", "道具与服装状态都对（背带滑到肘、扣环垂在手肘），但表情被改成甜笑"),
    "11-mirror-adult":   ("broken", "背带确实滑落、手撑镜面也对；但衬衫没敞开、裙长变短、气质被净化"),
    "13b-note":          ("ok",     "两件衣服 + 便签，仍然物构图"),
    "14-letter":         ("ok",     "信纸 + 尺头 + 开衫，粉裙下摆从纸边露出"),
}


def main() -> int:
    recs: dict[str, dict] = {}
    if LOG.exists():
        for line in LOG.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                recs[r["name"]] = r          # 后写的覆盖前面的（即最新一版）

    print("=" * 92)
    print("故事 CG 出图对账")
    print("=" * 92)
    print(f"{'CG':<20}{'判定':<9}{'状态':<9}{'秒':<7}{'参考图':<20}说明")
    print("-" * 92)
    tally: dict[str, int] = {}
    for name in sorted(VERDICT):
        verdict, note = VERDICT[name]
        r = recs.get(name) or {}
        ok = (STORY / f"{name}.png").exists()
        tally[verdict] = tally.get(verdict, 0) + 1
        print(f"{name:<20}{verdict:<9}{'有图' if ok else '缺图':<9}"
              f"{r.get('seconds', '?'):<7}{','.join(r.get('refs') or []):<20}{note}")

    print()
    print("小计：", "、".join(f"{k} {v} 张" for k, v in sorted(tally.items())))
    print()

    # 与剧本的 CG 清单对账
    want = ["01-entrance", "02-measure", "03-the-question", "04-unbutton",
            "07b-three-fitting", "10a-unhook", "11-mirror-adult", "13b-note", "14-letter"]
    missing = [w for w in want if not (STORY / f"{w}.png").exists()]
    print(f"剧本要求新出 {len(want)} 张，已出 {len(want) - len(missing)} 张"
          + (f"，缺 {missing}" if missing else ""))

    print()
    print("=" * 92)
    print("一条贯穿三张的规律（本次最重要的发现）")
    print("=" * 92)
    print("""
  04 / 10a / 11 三张都指向同一件事：**模型会把"接触另一个人"与"情欲"的语义
  替换成"可爱"** —— 而且它执行服装与道具的细节是准的，只是气质被打回去。

    04  要求：她的手停在**另一个人的**衬衫第二颗扣子上
        得到：她在扣**自己的**衬衫，还对着镜头笑
    10a 要求：背带滑落、她没回头
        得到：背带确实滑到肘部、扣环垂在手肘（对），但表情改成甜笑
    11  要求：衬衫敞开、靠镜、视线抬高
        得到：背带确实滑落、手撑镜面（对），但衬衫没敞开、裙长变短、整体净化

  这不是 prompt 写得不够细 —— 服装状态写了就执行。**是"情欲读法"本身被回退了。**
  所以对 R18 分镜，继续加形容词不会有用；要么换表达方式（见 STORY-GEN-REPORT.md
  的"三条退路"），要么接受这一篇做成"克制的张力"版本。
""")
    return 0


if __name__ == "__main__":
    sys.exit(main())
