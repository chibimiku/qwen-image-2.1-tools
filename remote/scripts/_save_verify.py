#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""验证自动落盘：YYYY-MM-DD/序号-seed.png，序号当天连续，回包与文件逐字节一致。"""
import base64
import hashlib
import json
import os
import pathlib
import sys
import time
import urllib.request

KEY = os.environ.get("KEY", "")
API = "http://127.0.0.1:6006"
OUT = pathlib.Path("/root/qwen-image-2.1/outputs")


def post(body):
    req = urllib.request.Request(API + "/v1/images/generations",
                                 data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json",
                                          "Authorization": "Bearer " + KEY})
    return json.loads(urllib.request.urlopen(req, timeout=600).read())


def gen(prompt, seed=None, steps=6, w=512, h=512):
    b = {"prompt": prompt, "num_inference_steps": steps, "width": w, "height": h}
    if seed is not None:
        b["seed"] = seed
    return post(b)


today = time.strftime("%Y-%m-%d")
day = OUT / today
before = sorted([p.name for p in day.iterdir()]) if day.exists() else []
print(f"生成前 {day} : {before or '（空/不存在）'}")

print("\n=== 连出 3 张，看序号是否连续、内容是否与回包一致 ===")
ok = True
for i in range(3):
    d = gen(f"第 {i + 1} 张：一个红色立方体放在白桌上", seed=1000 + i)
    it = d["data"][0]
    md = it.get("metadata") or {}
    saved = md.get("saved_path")
    print(f"  [{i + 1}] seed={it['seed']}  saved_path={saved}")
    if not saved:
        print("      ❌ 回包里没有 saved_path")
        ok = False
        continue
    p = pathlib.Path(saved)
    if not p.exists():
        print("      ❌ 文件不存在")
        ok = False
        continue
    disk = p.read_bytes()
    resp = base64.b64decode(it["b64_json"])
    same = hashlib.sha256(disk).hexdigest() == hashlib.sha256(resp).hexdigest()
    print(f"      文件 {p.name}  {len(disk) / 1024:.0f} KB  "
          f"{'✅ 与回包逐字节一致' if same else '❌ 与回包不一致'}")
    ok = ok and same
    # 命名格式
    import re
    m = re.match(r"^(\d+)-(\d+)\.png$", p.name)
    if not m:
        print(f"      ❌ 命名不符合 序号-seed.png：{p.name}")
        ok = False
    else:
        print(f"      命名 OK：序号={m.group(1)} seed={m.group(2)}"
              f"  {'（与返回 seed 一致）' if int(m.group(2)) == it['seed'] else '（与返回 seed 不一致 ❌）'}")
        ok = ok and int(m.group(2)) == it["seed"]

print(f"\n=== 当天目录最终内容 ===")
for n in sorted(p.name for p in day.iterdir()):
    print(f"  {n}")

print("\n=== 序号连续性（应无重复、无跳号）===")
import re
nums = sorted(int(re.match(r"^(\d+)-", n).group(1)) for n in (p.name for p in day.iterdir())
              if re.match(r"^\d+-", n))
print(f"  序号: {nums}")
if nums and nums == list(range(1, len(nums) + 1)):
    print("  ✅ 从 1 连续")
else:
    print(f"  （不连续：{nums}）")

print("\n=== 也能看到历史那 16 张（旧命名，不该被当成序号）===")
legacy = [n for n in sorted(p.name for p in OUT.iterdir()) if p.is_file()]
print(f"  根目录散图 {len(legacy)} 个，例如 {legacy[:3]}")

print("\n结论:", "通过 ✅" if ok else "有失败项 ❌")
sys.exit(0 if ok else 1)
