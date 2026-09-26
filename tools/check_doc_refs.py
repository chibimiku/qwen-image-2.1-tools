# -*- coding: utf-8 -*-
"""核对 markdown 里引用的「文件:行号」是否还对得上。

为什么需要它：文档里大量用 `xxx.py:123` 当证据索引。上游源码一更新行号就漂移，
而文档不会自己报错 —— 读者照着查会发现对不上。这个脚本把引用抠出来逐条核对。

用法：
    python tools/check_doc_refs.py docs/RESOLUTION.md [更多.md ...]
    python tools/check_doc_refs.py                # 默认检查 RESOLUTION.md
"""
from __future__ import annotations

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
UPSTREAM = ROOT / "docs" / "upstream"

# 行号 -> 该行应出现的关键词。上游更新导致行号变化时，这里会失败并提示实际内容。
EXPECT = {
    149: "def calculate_dimensions",
    199: "compresses 16x",
    266: "RGBA",
    389: "def check_inputs",
    410: "def _pack_latents",
    527: "output_resolution",
    579: "output_resolution",
    621: "calculate_dimensions",
    624: "height = height or calculated_height",
    648: "one resize feeds both",
    656: "calculate_dimensions",
    768: "torch.cat",
    666: "arange(8192)",
    766: "latent_model_input = latents",
    768: "torch.cat",
}

REF = re.compile(r"([\w.-]+\.py):(\d+)")


def main() -> int:
    docs = sys.argv[1:] or ["docs/RESOLUTION.md"]
    ok = bad = skip = 0
    seen = set()
    for doc in docs:
        p = ROOT / doc
        if not p.exists():
            print(f"  跳过（不存在）: {doc}")
            continue
        print(f"=== {doc} ===")
        text = p.read_text(encoding="utf-8")
        for m in REF.finditer(text):
            fname, num = m.group(1), int(m.group(2))
            key = (fname, num)
            if key in seen:
                continue
            seen.add(key)
            src = UPSTREAM / fname
            if not src.exists():
                print(f"  [skip] {fname}:{num}（不在 docs/upstream/ 下）")
                skip += 1
                continue
            lines = src.read_text(encoding="utf-8", errors="replace").splitlines()
            if num > len(lines):
                print(f"  [FAIL] {fname}:{num} — 文件只有 {len(lines)} 行")
                bad += 1
                continue
            line = lines[num - 1]
            want = EXPECT.get(num)
            if want is None:
                print(f"  [?]    {fname}:{num}（未登记期望值，仅确认行存在）")
                ok += 1
            elif want in line:
                print(f"  [OK]   {fname}:{num} 含 {want!r}")
                ok += 1
            else:
                print(f"  [FAIL] {fname}:{num} 不含 {want!r}")
                print(f"         实际: {line.strip()[:96]}")
                bad += 1
    print(f"\n核对结果: OK {ok} / FAIL {bad} / skip {skip}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
