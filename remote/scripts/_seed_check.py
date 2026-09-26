#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""验证种子语义：留空=真随机且可用返回的种子复现；指定=严格可复现。"""
import base64
import hashlib
import json
import os
import sys
import urllib.request

KEY = os.environ.get("KEY", "")
API = "http://127.0.0.1:6006"


def gen(seed=None, steps=8, size=512):
    body = {"prompt": "a red cube on a white table, studio light",
            "num_inference_steps": steps, "width": size, "height": size,
            "output_format": "png"}
    if seed is not None:
        body["seed"] = seed
    req = urllib.request.Request(API + "/v1/images/generations",
                                 data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    if KEY:
        req.add_header("Authorization", "Bearer " + KEY)
    with urllib.request.urlopen(req, timeout=600) as r:
        d = json.loads(r.read())
    it = d["data"][0]
    png = base64.b64decode(it["b64_json"])
    return it["seed"], it.get("seed_given"), hashlib.md5(png).hexdigest()[:12]


print("=== A. 留空两次：种子应该不同，图也应该不同 ===")
s1, given1, h1 = gen()
s2, given2, h2 = gen()
print(f"  第1次 seed={s1} seed_given={given1} md5={h1}")
print(f"  第2次 seed={s2} seed_given={given2} md5={h2}")
print(f"  种子是否不同: {'是 ✅' if s1 != s2 else '否 ❌（随机性有问题）'}")
print(f"  图是否不同  : {'是 ✅' if h1 != h2 else '否（可能偶然相同）'}")
print(f"  seed_given 应均为 False: {'✅' if given1 is False and given2 is False else '❌'}")

print("\n=== B. 用 A 返回的种子复现：应该一模一样 ===")
s3, given3, h3 = gen(seed=s1)
print(f"  指定 seed={s1} → md5={h3}  seed_given={given3}")
print(f"  与第1次是否相同: {'是 ✅ 可复现' if h3 == h1 else '否 ❌'}")
print(f"  seed_given 应为 True: {'✅' if given3 is True else '❌'}")

print("\n=== C. 换种子应该换图 ===")
s4, _, h4 = gen(seed=s1 + 1)
print(f"  seed={s1 + 1} → md5={h4}")
print(f"  与 seed={s1} 是否不同: {'是 ✅' if h4 != h3 else '否 ❌'}")

print("\n=== D. 同一个种子连跑两次（确认确定性稳定） ===")
_, _, h5 = gen(seed=1234)
_, _, h6 = gen(seed=1234)
print(f"  seed=1234 两次: {h5} / {h6}  {'一致 ✅' if h5 == h6 else '不一致 ❌'}")

ok = (s1 != s2 and h1 != h2 and h3 == h1 and h4 != h3 and h5 == h6
      and given1 is False and given3 is True)
print("\n结论:", "全部通过 ✅" if ok else "有失败项 ❌")
sys.exit(0 if ok else 1)
