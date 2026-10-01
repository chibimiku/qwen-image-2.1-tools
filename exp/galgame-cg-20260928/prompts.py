# -*- coding: utf-8 -*-
"""按文件打印每张出图的**原始 prompt**，用于逐张核对"要求 vs 实画"。

  python exp/galgame-cg-20260928/prompts.py                 # 全部
  python exp/galgame-cg-20260928/prompts.py story-03-street # 单张
  python exp/galgame-cg-20260928/prompts.py --scene         # 只打场景段（去掉三段固定模板）

打"只场景段"是因为前三段（分工声明/样式词/禁止清单）每张都一样，
逐张核对时它只是噪音；真正决定画面的那句在最后。
"""
from __future__ import annotations

import json
import pathlib
import sys

EXP = pathlib.Path(__file__).resolve().parent


def load() -> list[dict]:
    mf = EXP / "manifest.jsonl"
    recs = [json.loads(l) for l in mf.read_text(encoding="utf-8").splitlines() if l.strip()]
    # 同一名字只留最后一条成功的（失败重试会被覆盖掉）
    best: dict[str, dict] = {}
    for r in recs:
        if r.get("status") != "ok":
            continue
        best[r["name"]] = r
    return [best[k] for k in sorted(best)]


def scene_only(prompt: str) -> str:
    """最后一段 = 角色圣经 + 场景，去掉前三段固定模板。<image2> 行也去掉。"""
    parts = [p.strip() for p in prompt.split("\n\n") if p.strip()]
    return parts[-1] if parts else prompt


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    only_scene = "--scene" in sys.argv
    recs = load()
    if args:
        recs = [r for r in recs if r["name"] in args]
    print(f"共 {len(recs)} 张\n")
    for r in recs:
        print("=" * 100)
        print(f"{r['name']}   {r.get('size')}   seed={r.get('seed')}   "
              f"{r.get('seconds')}s   refs={r.get('refs')}")
        print("-" * 100)
        if only_scene:
            print(scene_only(r["prompt"]))
        else:
            print(r["prompt"])
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
