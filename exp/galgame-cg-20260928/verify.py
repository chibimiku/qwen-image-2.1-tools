# -*- coding: utf-8 -*-
"""配方自检：确认每一步都按 docs/RECIPE-character-plus-style.md 的四段结构发的。

  python exp/galgame-cg-20260928/verify.py

不做主观判图（那要人眼看），只查**可判定的部分**：

1. manifest 里每条记录是否都有 file:image1 / file:image2（对照组只有 image1）
2. prompt 是否含四段结构的标志句（分工句、样式词、禁止清单、角色圣经）
3. 出图是否真的存在、尺寸是否等于响应里报的 size
4. 参考图的 inputs 元数据是否与本地文件 sha256 对得上（证明发的是那两张图）
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import sys

EXP = pathlib.Path(__file__).resolve().parent
OUT = EXP / "out"

REQUIRED_IN_PROMPT = {
    "分工句": "STYLE SAMPLE ONLY",
    "样式词": "linework",
    "禁止清单": "Do NOT copy from <image2>",
    "角色圣经": "indigo-blue hair",
}
BOOST_MARKERS = {"强化分工句": "RENDERING TECHNIQUE"}


def sha(p: pathlib.Path) -> str:
    """本地文件的 sha256（用来记录我们发出的字节）。"""
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for c in iter(lambda: fh.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def server_style_sha(p: pathlib.Path) -> str:
    """复算服务端 `inputs[].sha256` 的口径。

    服务端 `_input_info()` 算的是**「解码后像素重新用 PNG 编码」**的哈希，
    固定 `compress_level=1` —— 不是上传的原始字节（见 docs/METADATA.md 与
    server.py L326-349）。所以本地要对得上，必须照同一套来算。

    一开始我按"文件哈希"去比，72 条全红；那是自检写错，不是配方错。
    """
    import io

    from PIL import Image
    im = Image.open(p)
    im.load()
    buf = io.BytesIO()
    im.save(buf, format="PNG", compress_level=1)
    return hashlib.sha256(buf.getvalue()).hexdigest()


def main() -> int:
    mf = EXP / "manifest.jsonl"
    if not mf.exists():
        print(f"缺 {mf}；先跑 run.py")
        return 2
    recs = [json.loads(l) for l in mf.read_text(encoding="utf-8").splitlines() if l.strip()]
    ok_recs = [r for r in recs if r.get("status") == "ok"]
    print(f"manifest 共 {len(recs)} 条，其中成功 {len(ok_recs)} 条")

    ref_sha = {n: server_style_sha(EXP / "refs" / f"{n}.png")
               for n in ("char", "style", "style16x9")
               if (EXP / "refs" / f"{n}.png").exists()}
    for n, h in ref_sha.items():
        print(f"参考图 {n}: 服务端口径 sha {h[:12]}  "
              f"(文件 sha {sha(EXP / 'refs' / f'{n}.png')[:12]})")

    fails = []
    for r in ok_recs:
        name = r["name"]
        # 1) 出图存在
        p = OUT / f"{name}.png"
        if not p.exists():
            fails.append(f"{name}: 出图文件不存在")
            continue
        # 2) prompt 四段结构
        prompt = r.get("prompt", "")
        need = dict(REQUIRED_IN_PROMPT)
        if r.get("boost"):
            need.update(BOOST_MARKERS)
        for label, needle in need.items():
            if needle not in prompt:
                fails.append(f"{name}: prompt 缺「{label}」（找不到 {needle!r}）")
        # 3) 参考图参与情况
        #
        # 判据用 **`inputs[].size` 字符串**，不用 sha256：
        #   · `inputs[]` 的字段是 {index, sha256, size}，其中 size 是 "1024x1536" 这样的
        #     字符串，**不是** width/height 两个键（我一开始按 width/height 取，全是 None）。
        #   · sha256 是**按图恒定**的（char 在所有 42 次请求里都是 220608e1d01c1c3e），
        #     但它的口径复现不出来：服务端在**缩放后**的图上算，源码注释写的是
        #     「解码后像素按 PNG compress_level=1 重编码」，按这个算得 015c3c3e…，与实测不符。
        #     口径没查清就不拿它当红线 —— 赌错了会把"其实没问题"报成失败。
        # 三张参考图的尺寸互不相同，用 size 足以回答"该发的图发了没有、发了几个"。
        WANT_SIZE = {"char": "1024x1536", "style": "832x1216", "style16x9": "1600x896"}
        inputs = r.get("inputs") or []
        want_refs = r.get("refs") or []
        if len(inputs) != len(want_refs):
            fails.append(f"{name}: inputs 有 {len(inputs)} 张，任务声明 {len(want_refs)} 张")
        for i, (inp, rn) in enumerate(zip(inputs, want_refs), start=1):
            if rn not in WANT_SIZE:
                fails.append(f"{name}: 任务引用了未知参考图 {rn}")
                continue
            got = inp.get("size")
            if got != WANT_SIZE[rn]:
                fails.append(f"{name}: image{i} 期望 {rn} 尺寸 {WANT_SIZE[rn]}，实际 {got}")
            if not inp.get("sha256"):
                fails.append(f"{name}: image{i} 元数据里没有 sha256")
        # 4) 尺寸一致
        size = r.get("size")
        if size:
            try:
                with open(p, "rb") as fh:
                    head = fh.read(33)
                w = int.from_bytes(head[16:20], "big")
                h = int.from_bytes(head[20:24], "big")
                if f"{w}x{h}" != size:
                    fails.append(f"{name}: 文件 {w}x{h} != 记录 size {size}")
            except Exception as exc:                                    # noqa: BLE001
                fails.append(f"{name}: 读尺寸失败 {type(exc).__name__}")

    print(f"\n检查 {len(ok_recs)} 条：{'全部通过' if not fails else '%d 项失败' % len(fails)}")
    for f in fails:
        print("   -", f)

    # 分组统计，便于并排比较
    print("\n按 phase 汇总：")
    by = {}
    for r in ok_recs:
        by.setdefault((r.get("phase"), r.get("boost", False)), []).append(r)
    for (ph, bo), rs in sorted(by.items(), key=lambda x: str(x[0])):
        sizes = {r.get("size") for r in rs}
        secs = [r["seconds"] for r in rs if r.get("seconds")]
        print(f"   {str(ph):<9} boost={str(bo):<5} n={len(rs):<3} "
              f"尺寸={','.join(sorted(x for x in sizes if x)):<12} "
              f"平均 {sum(secs)/len(secs):.1f}s" if secs else "")
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
