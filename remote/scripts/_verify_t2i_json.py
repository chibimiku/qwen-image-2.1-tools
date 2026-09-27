#!/usr/bin/env python3
"""端到端验证 /v1/images/generations 的两条请求路径行为一致。

背景：JSON 分支以前不把 width/height 转成 int，字符串一路走到
`enforce_fitting_size` 里变成 `"1024" * "1024"` → TypeError → HTTP 500。
multipart 分支有 int()，所以同样参数能跑 —— 一个接口两种行为，这是最坏的一种 bug。

这里对同一个"文本生成"请求分别用 JSON 和 multipart 打一次，断言都 200 且尺寸一致。
不打 t2i 全量（那是 _cfg_ab_generate.py 的事），只验证解析层。
"""
import base64
import io
import json
import os
import sys
import time
import urllib.error
import urllib.request

API = os.environ.get("API", "http://127.0.0.1:6006")
KEY = os.environ["KEY"]
PROMPT = "a red apple on a wooden table, studio light"
BASE = {"prompt": PROMPT, "num_inference_steps": "4", "seed": "4242",
        "output_format": "png", "width": "1024", "height": "1024"}


def post_json(payload):
    req = urllib.request.Request(
        API + "/v1/images/generations", data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + KEY})
    return urllib.request.urlopen(req, timeout=900)


def post_multipart(fields):
    b = "----ab" + str(int(time.time() * 1000))
    body = b""
    for k, v in fields.items():
        body += (f"--{b}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n").encode()
    body += f"--{b}--\r\n".encode()
    req = urllib.request.Request(
        API + "/v1/images/generations", data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={b}",
                 "Authorization": "Bearer " + KEY})
    return urllib.request.urlopen(req, timeout=900)


def probe(name, fn, payload):
    t0 = time.time()
    try:
        r = fn(payload)
    except urllib.error.HTTPError as e:
        detail = e.read()[:300].decode("utf-8", "replace")
        print(f"  {name:<28} HTTP {e.code}  {detail}")
        return None
    d = json.loads(r.read())
    it = d["data"][0]
    nbytes = len(base64.b64decode(it["b64_json"]))
    print(f"  {name:<28} 200  {d.get('size')}  {nbytes} B  {time.time() - t0:.1f}s")
    return d


def dims(res):
    """响应顶层就有 size（服务端自己回填的最终尺寸），不用去解 PNG。"""
    return res.get("size") if res else None


results = {}
print("=== 回归：字符串宽高必须走通（曾经 500）===")
results["json_str"] = probe("JSON width='1024'", post_json, dict(BASE))

print("\n=== 数字宽高（本来就该通）===")
j = dict(BASE, width=1024, height=1024)
results["json_int"] = probe("JSON width=1024", post_json, j)

print("\n=== OpenAI 的 size 字段（以前被静默忽略、退回 2048）===")
s = {"prompt": PROMPT, "num_inference_steps": "4", "seed": "4242",
     "output_format": "png", "size": "1024x1536"}
results["json_size"] = probe('JSON size="1024x1536"', post_json, s)

print("\n=== multipart 对照（一直是对的）===")
results["mp_str"] = probe("multipart str", post_multipart, dict(BASE))

print("\n=== 垃圾输入必须是 400，不能是 500 ===")
for bad in ({"width": "abc", "height": "1024"}, {"width": "0", "height": "1024"}):
    probe("JSON " + json.dumps(bad), post_json, dict(BASE, **bad))

fail = 0
if not results["json_str"]:
    print("\nFAIL: JSON 字符串宽高仍然失败")
    fail += 1
if not results["json_int"]:
    print("\nFAIL: JSON 数字宽高失败")
    fail += 1

def dims(res):
    return res.get("size") if res else None


if results["json_str"] and results["json_int"]:
    if dims(results["json_str"]) != dims(results["json_int"]):
        print("\nFAIL: 字符串与数字宽高得到不同尺寸 %s vs %s"
              % (dims(results["json_str"]), dims(results["json_int"])))
        fail += 1
    if dims(results["json_str"]) != "1024x1024":
        print("\nFAIL: 期望 1024x1024，实得 %s" % (dims(results["json_str"]),))
        fail += 1
if results["json_size"] and dims(results["json_size"]) != "1024x1536":
    print("\nFAIL: size=1024x1536 没被采用，实得 %s" % (dims(results["json_size"]),))
    fail += 1

print("\n" + ("ALL GOOD" if fail == 0 else "%d FAIL" % fail))
sys.exit(1 if fail else 0)
