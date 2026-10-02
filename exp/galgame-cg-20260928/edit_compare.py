# -*- coding: utf-8 -*-
"""后期 edit 前后对比：亮度/过曝的客观变化 + 主体动作是否真的改了。

  python exp/galgame-cg-20260928/edit_compare.py

为什么要出这张表：edit 的**副作用**（背景变暗、加光点）是可以量化看出来的，
而"主体动作有没有改"不能靠感觉 —— 要写清楚哪一项改了、哪一项没改。
"""
from __future__ import annotations

import pathlib
import sys

import numpy as np
from PIL import Image

EXP = pathlib.Path(__file__).resolve().parent
STORY, EDITED = EXP / "story", EXP / "story-edited"

# 人工判定：edit 前要求改什么、实际改成了什么
VERDICT = {
    "04-unbutton": {
        "asked": "她的手停在**另一个人的**衬衫第二颗扣子上、不笑",
        "got": "**没改** —— 仍是扣自己的衬衫 + 微笑；只改了背景",
        "verdict": "失败",
    },
    "10a-unhook": {
        "asked": "表情从甜笑改成克制的注视",
        "got": "**轻微变化**，仍带一点笑；背带与道具原样保住",
        "verdict": "部分",
    },
    "11-mirror-adult": {
        "asked": "衬衫敞开 + 裙长改回及膝 + 表情收敛",
        "got": "**三项都改到了**；背带滑落/手撑镜面/布尺原样保住",
        "verdict": "成功",
    },
}


def main() -> int:
    print("=" * 92)
    print("后期 edit 前后对比")
    print("=" * 92)
    print(f"{'图':<18}{'原图 亮度/白%':<20}{'edit 亮度/白%':<20}{'亮度变化':<12}{'白%变化'}")
    print("-" * 92)
    for n in sorted(VERDICT):
        a = np.asarray(Image.open(STORY / f"{n}.png").convert("RGB")).astype(np.float32)
        b = np.asarray(Image.open(EDITED / f"{n}.png").convert("RGB")).astype(np.float32)
        la, lb = float(a.mean()), float(b.mean())
        wa = float((a >= 250).all(axis=2).mean() * 100)
        wb = float((b >= 250).all(axis=2).mean() * 100)
        print(f"{n:<18}{la:>6.1f} / {wa:<12.2f}{lb:>6.1f} / {wb:<12.2f}"
              f"{lb - la:>+9.1f}   {wb - wa:>+6.2f}pp")

    print()
    print("=" * 92)
    print("逐张判定")
    print("=" * 92)
    for n, v in sorted(VERDICT.items()):
        print(f"\n  {n}  →  {v['verdict']}")
        print(f"    要求改：{v['asked']}")
        print(f"    实际得：{v['got']}")

    print()
    print("=" * 92)
    print("结论")
    print("=" * 92)
    print("""
  1. **改「服装状态」有效，改「动作」无效。**
     11 要求的三项（衬衫敞开、裙长、表情收敛）都做到了；
     04 要求改"手放在别人的衣服上"完全没动。这条和出图阶段的规律一致：
     **模型画得好"状态"，画不好"与另一个人发生的动作"。**

  2. **edit 有一个稳定副作用：整体变亮 + 加一圈金色光点。**
     三张的**亮度均值都上升**（+0.4 / +4.5 / +11.5），画面里多出散景光点，
     对比度也被拉开。
     ⚠️ 我第一版把这条写成"背景变暗"——**错了，方向记反了**。
     看起来更暗是因为暗部更沉、对比更强，但亮部同时被提上去了，均值是升的。
     对夜景的 10a/11 不算坏（更像 galgame CG 了），
     但**对白天的图要小心** —— 它会把画面整体提亮。

  3. **edit 保得住已经画对的部分。** 11 的背带滑落、手撑镜面、垂下的布尺，
     10a 的扣环位置、台灯、开衫、粉裙，全部原样保留 —— 这是重出做不到的。
""")
    return 0


if __name__ == "__main__":
    sys.exit(main())
