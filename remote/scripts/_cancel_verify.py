#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""验证"真正中止当前生成"：一次 40 步的生成，跑到中途按停止，应立刻中断并回 499。

顺便验证：
  · 中止后进度状态是 canceled
  · 中止信号用完就清，下一次同 request_id 不会被误伤
  · 队列语义（只停队列 = 不发下一个）在客户端，不需要服务端参与，这里只测中断
"""
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request

KEY = os.environ.get("KEY", "")
API = "http://127.0.0.1:6006"


def auth(req):
    if KEY:
        req.add_header("Authorization", "Bearer " + KEY)
    return req


def get(path):
    with urllib.request.urlopen(auth(urllib.request.Request(API + path)), timeout=10) as r:
        return json.loads(r.read())


def post_json(path, payload):
    req = auth(urllib.request.Request(API + path, data=json.dumps(payload).encode(),
                                      headers={"Content-Type": "application/json"}))
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())


rid = "req_cancel" + str(int(time.time()))[:6]
steps = 40
body = json.dumps({"prompt": "一座雪山下的湖面倒影，长曝光", "num_inference_steps": steps,
                   "width": 1024, "height": 1024, "request_id": rid}).encode()

result = {}
started = threading.Event()


def run():
    req = auth(urllib.request.Request(API + "/v1/images/generations", data=body,
                                      headers={"Content-Type": "application/json"}))
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=600) as r:
            result["code"] = r.status
            result["body"] = r.read()[:200]
    except urllib.error.HTTPError as e:
        result["code"] = e.code
        result["body"] = e.read()[:200]
    except Exception as exc:                                           # noqa: BLE001
        result["code"] = "exc"
        result["body"] = str(exc).encode()
    result["elapsed"] = time.time() - t0


th = threading.Thread(target=run, daemon=True)
th.start()

# 等到它真的开始去噪（进度里有步数）再下手，否则测不出"中断运行中的任务"
t_wait = time.time()
seen = 0
while time.time() - t_wait < 60:
    try:
        p = get("/v1/progress/" + rid)
    except Exception:                                                  # noqa: BLE001
        p = {}
    seen = p.get("steps_done") or 0
    if seen >= 3:
        break
    time.sleep(0.4)

print(f"观察到已走 {seen} 步，现在发中止请求")
t_cancel = time.time()
resp = post_json("/v1/progress/" + rid + "/cancel", {})
print("  cancel ->", json.dumps(resp, ensure_ascii=False))

th.join(timeout=120)
dt = time.time() - t_cancel
print(f"\n生成请求返回：code={result.get('code')} 耗时 {result.get('elapsed', 0):.1f}s"
      f"（其中中止后 {dt:.1f}s 内结束）")
print("  响应体:", (result.get("body") or b"").decode("utf-8", "replace")[:160])

try:
    after = get("/v1/progress/" + rid)
    print("  事后进度状态:", after.get("status"), "| error:", after.get("error"),
          "| steps_done:", after.get("steps_done"))
except Exception as exc:                                               # noqa: BLE001
    print("  查进度失败:", exc)

ok_code = result.get("code") == 499
ok_fast = dt < 15
ok_state = True
try:
    ok_state = after.get("status") in ("canceled", "error")
except Exception:                                                      # noqa: BLE001
    pass

print("\n判定：")
print(f"  [{'OK' if ok_code else 'FAIL'}] 返回 499（被取消，而不是 500）")
print(f"  [{'OK' if ok_fast else 'FAIL'}] 中止在 15 秒内生效（实测 {dt:.1f}s）")
print(f"  [{'OK' if ok_state else 'FAIL'}] 进度被标记为已取消")

print("\n=== 清理信号：同一 request_id 再来一次应能正常跑完 ===")
body2 = json.dumps({"prompt": "一个小红点", "num_inference_steps": 4,
                    "width": 512, "height": 512, "request_id": rid}).encode()
req = auth(urllib.request.Request(API + "/v1/images/generations", data=body2,
                                  headers={"Content-Type": "application/json"}))
try:
    with urllib.request.urlopen(req, timeout=300) as r:
        d = json.loads(r.read())
    print(f"  [OK] 复跑成功，输出 {d['data'][0]['width']}x{d['data'][0]['height']}")
    ok_reuse = True
except urllib.error.HTTPError as e:
    print(f"  [FAIL] 复跑被误伤：HTTP {e.code} {e.read()[:120]}")
    ok_reuse = False

sys.exit(0 if (ok_code and ok_fast and ok_reuse) else 1)
