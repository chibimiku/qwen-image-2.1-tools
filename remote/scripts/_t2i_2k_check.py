#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""实测文生图能不能跑官方 2K 档位（用来定 T2I_KNOWN_GOOD_MP，而不是靠外推）。"""
import json
import os
import time
import urllib.error
import urllib.request

KEY = os.environ.get("KEY", "")
API = "http://127.0.0.1:6006"


def gen(w, h, steps=20, label=""):
    body = json.dumps({"prompt": "雪山与湖面倒影，长曝光", "num_inference_steps": steps,
                       "width": w, "height": h}).encode()
    req = urllib.request.Request(API + "/v1/images/generations", data=body,
                                 headers={"Content-Type": "application/json",
                                          "Authorization": "Bearer " + KEY})
    t = time.time()
    try:
        d = json.loads(urllib.request.urlopen(req, timeout=900).read())
        it = d["data"][0]
        print(f"  {label or ''} {w}x{h} ({w * h / 1e6:.2f}MP) → OK "
              f"{it['width']}x{it['height']}  {time.time() - t:.0f}s", flush=True)
        return True
    except urllib.error.HTTPError as e:
        msg = e.read()[:180].decode("utf-8", "replace")
        print(f"  {label or ''} {w}x{h} ({w * h / 1e6:.2f}MP) → HTTP {e.code}: {msg}", flush=True)
        return False


print("=== 文生图能跑多大（官方 2K 档位共 7 个，全试一遍）===")
cases = [(2048, 2048), (2400, 1792), (1792, 2400), (2528, 1696),
         (1696, 2528), (2752, 1536), (1536, 2752)]
results = {}
for w, h in cases:
    results[(w, h)] = gen(w, h, 20)

ok = [f"{w}x{h}" for (w, h), v in results.items() if v]
bad = [f"{w}x{h}" for (w, h), v in results.items() if not v]
print(f"\n能跑 {len(ok)}/{len(cases)}：{', '.join(ok)}")
if bad:
    print(f"跑不动：{', '.join(bad)}")
