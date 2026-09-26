#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""读取生成图里的元数据（PNG 的 iTXt 块 qwen_image_21）。

    python tools/read_metadata.py out.png              # 摘要
    python tools/read_metadata.py out.png --json       # 原始 JSON
    python tools/read_metadata.py out.png --verify     # 顺带校验 png_sha256 对不对
    python tools/read_metadata.py test-data/**/*.png   # 批量

设计约定（读取方按这个兼容）：
  · 载荷是带 schema / schema_version 的 JSON；**不认识的字段一律忽略**，
    所以服务端以后加字段不会让老工具报错。
  · 顶层字段缺失不报错，只是不显示。
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import json
import pathlib
import sys

try:
    from PIL import Image
except ImportError:                                                    # noqa: BLE001
    print("需要 pillow：pip install pillow")
    raise SystemExit(2)

CHUNK = "qwen_image_21"


def read_meta(path: pathlib.Path) -> dict | None:
    with Image.open(path) as im:
        im.load()
        raw = im.info.get(CHUNK)
    if raw is None:
        return None
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", "replace")
    try:
        return json.loads(raw)
    except Exception:                                                  # noqa: BLE001
        return {"__parse_error__": True, "__raw__": raw[:200]}


def pixels_sha256(im) -> str:
    """与服务端同一套算法：统一 RGBA、尺寸拌进去、哈希 tobytes()。

    注意不能拿 PNG 文件字节去比 —— 编码结果依赖 Pillow/zlib 版本，跨机器不一致。
    """
    im2 = im if im.mode == "RGBA" else im.convert("RGBA")
    h = hashlib.sha256()
    h.update(f"RGBA\0{im2.width}\0{im2.height}\0".encode())
    h.update(im2.tobytes())
    return h.hexdigest()


def show(path: pathlib.Path, meta: dict, args) -> bool:
    if args.json:
        print(json.dumps(meta, ensure_ascii=False, indent=2))
        return True
    if meta.get("__parse_error__"):
        print(f"■ {path.name}\n  元数据存在但不是合法 JSON（可能是别的工具写的）")
        return False

    r = meta.get("request") or {}
    m = meta.get("model") or {}
    o = meta.get("output") or {}
    g = meta.get("generator") or {}
    t = meta.get("timing") or {}
    ins = meta.get("inputs") or []

    print(f"■ {path.name}  ({path.stat().st_size / 1e6:.2f} MB)")
    print(f"   schema      {meta.get('schema')} v{meta.get('schema_version')}")
    print(f"   generator   {g.get('name')} {g.get('version')} @ {g.get('created_at')}")
    print(f"   模型        {m.get('model')}  hash={(m.get('weights_sha256') or 'n/a')[:16]}"
          f"  state={m.get('state')}")
    if m.get("note"):
        print(f"               ({m['note']})")
    print(f"   尺寸        {r.get('width')}x{r.get('height')}"
          f"   steps={r.get('num_inference_steps')}  seed={r.get('seed')}"
          f"{'' if r.get('seed_given') is not False else ' (自动掷)'}")
    if r.get("aspect_ratio"):
        print(f"   aspect      {r['aspect_ratio']}   output_resolution={r.get('output_resolution')}")
    prompt = r.get("prompt") or ""
    print(f"   prompt      {prompt[:160]}{'…' if len(prompt) > 160 else ''}")
    if r.get("negative_prompt"):
        print(f"   negative    {str(r['negative_prompt'])[:100]}")
    if ins:
        print(f"   输入图      {len(ins)} 张")
        for x in ins:
            print(f"     <image{x.get('index')}>  {x.get('width')}x{x.get('height')}"
                  f"  sha256={(x.get('sha256') or 'n/a')[:16]}  {x.get('name') or ''}")
    if t:
        print(f"   耗时        总 {t.get('total_s')}s  每步 {t.get('per_step_s')}s"
              f"  解码 {t.get('decode_s')}s  编码 {t.get('encode_s')}s")
    if meta.get("anatomy_check"):
        a = meta["anatomy_check"]
        print(f"   审图        passed={a.get('passed')} attempts={a.get('attempts')}"
              f" retries={a.get('retries')}")
    if o.get("content_sha256"):
        print(f"   content_sha256  {o['content_sha256'][:32]}…  （像素内容指纹，认图用）")
        if args.verify:
            # 校验内容：按同一套算法（RGBA 像素 + 尺寸）重算，与 PNG 编码版本无关。
            # 文件自身的完整哈希（png_sha256）不会写在文件里 —— 那是自指，
            # 它只出现在 API 响应里，用来核对文件是不是服务端发出的那个。
            with Image.open(path) as im:
                im.load()
                actual = pixels_sha256(im)
            mark = "  ✅ 内容校验通过" if actual == o["content_sha256"] else f"  ❌ 实际 {actual[:16]}"
            print(f"                   {mark}")
    elif args.verify:
        print("   content_sha256  缺失，无法校验内容")

    known = {"schema", "schema_version", "generator", "model", "request", "inputs",
             "output", "timing", "environment", "anatomy_check"}
    extra = sorted(set(meta) - known)
    if extra:
        # 关键：新版本加的字段在这里列出来，而不是让老工具崩掉
        print(f"   (本工具不认识的字段，已忽略：{', '.join(extra)})")
    return True


def expand(patterns: list[str]) -> list[pathlib.Path]:
    out = []
    for p in patterns:
        hits = [pathlib.Path(x) for x in glob.glob(p, recursive=True)]
        out.extend(sorted(h for h in hits if h.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp")))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("paths", nargs="+", help="图片路径或 glob")
    ap.add_argument("--json", action="store_true", help="打印原始 JSON")
    ap.add_argument("--verify", action="store_true", help="校验 png_sha256")
    args = ap.parse_args()

    files = expand(args.paths) or [pathlib.Path(p) for p in args.paths]
    have = miss = 0
    for f in files:
        try:
            meta = read_meta(f)
        except Exception as exc:                                       # noqa: BLE001
            print(f"■ {f.name}: 打不开（{exc}）")
            continue
        if meta is None:
            print(f"■ {f.name}：**没有** qwen_image_21 元数据")
            miss += 1
            continue
        show(f, meta, args)
        print()
        have += 1
    print(f"合计 {len(files)} 张：有元数据 {have} / 没有 {miss}")
    return 1 if miss and not have else 0


if __name__ == "__main__":
    sys.exit(main())
