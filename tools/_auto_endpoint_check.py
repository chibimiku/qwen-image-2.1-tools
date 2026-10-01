# -*- coding: utf-8 -*-
"""实测自检回路的接口（不依赖真实 LLM，key 用假的）。

  python tools/_auto_endpoint_check.py

验证：
  1. 未鉴权 → 401
  2. GET 配置：只回 has_key，**任何位置都不出现 key**
  3. POST 配置：写入生效、mode 600、空 key 不覆盖已有 key、clear_key 能清
  4. /v1/vision/test：key 是假的 → 要如实报错而不是假装成功
  5. /v1/auto/start：没配 key 时 400 且提示清晰；配了假 key 时能起任务
  6. /v1/auto/status、/list、/stop、/file 的行为
"""
from __future__ import annotations

import json
import pathlib
import sys
import threading
import time

import paramiko
import requests

TOOLS = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))
import autodl_ssh  # noqa: E402

CFG = {}
for raw in (TOOLS / "autodl_new.env").read_text(encoding="utf-8").splitlines():
    line = raw.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        CFG[k.strip()] = v.strip().strip('"').strip("'")
KEY = [l.strip() for l in (TOOLS / ".qwenkey").read_text(encoding="utf-8").splitlines()
       if l.strip() and not l.startswith("#")][0]

FAKE = "sk-THIS-IS-A-FAKE-KEY-FOR-TESTING-0123456789"
fails: list[str] = []
checks = 0


def check(cond: bool, label: str, extra: str = "") -> None:
    global checks
    checks += 1
    print(("  OK   " if cond else "  FAIL ") + label + (("  " + extra) if extra else ""))
    if not cond:
        fails.append(label)


c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(CFG["AUTODL_HOST"], port=int(CFG["AUTODL_PORT"]), username=CFG["AUTODL_USER"],
          password=CFG["AUTODL_PASS"], timeout=25, allow_agent=False, look_for_keys=False)


def sh(cmd: str, t: int = 180) -> str:
    _, o, e = c.exec_command(cmd, timeout=t)
    return (o.read().decode("utf-8", "replace") + e.read().decode("utf-8", "replace")).strip()


fwd = autodl_ssh.ForwardServer(("127.0.0.1", 16069), autodl_ssh.Handler)
fwd.dst_host, fwd.dst_port = "127.0.0.1", 6006
fwd.transport = c.get_transport()
threading.Thread(target=fwd.serve_forever, daemon=True).start()
time.sleep(0.4)
BASE = "http://127.0.0.1:16069"
H = {"Authorization": "Bearer " + KEY}

print("=== 1. 鉴权 ===")
r = requests.get(BASE + "/v1/vision/config", timeout=30)
check(r.status_code == 401, "未鉴权读配置 → 401", f"got {r.status_code}")
r = requests.post(BASE + "/v1/auto/start", timeout=30)
check(r.status_code == 401, "未鉴权启动回路 → 401", f"got {r.status_code}")

print("\n=== 2. 读配置不带 key ===")
r = requests.get(BASE + "/v1/vision/config", headers=H, timeout=30)
check(r.status_code == 200, "带鉴权读配置 → 200")
d = r.json()
check("api_key" not in d, "响应里没有 api_key 字段", f"键={sorted(d)}")
check("has_key" in d, "有 has_key 布尔值")
check(FAKE not in r.text, "响应正文不含任何 key 字样")
print("     配置：", json.dumps({k: v for k, v in d.items()
                                if k not in ("vision_modes", "style_tiers")},
                               ensure_ascii=False))

print("\n=== 3. 写配置 ===")
r = requests.post(BASE + "/v1/vision/config", headers=H, timeout=30,
                  json={"base_url": "https://api.deepseek.com", "model": "deepseek-flash",
                        "detail": "high", "max_rounds": 2, "pass_score": 6.5,
                        "api_key": FAKE})
d2 = r.json()
check(r.status_code == 200 and d2.get("has_key") is True, "写入后 has_key=True")
check(d2.get("model") == "deepseek-flash", "model 生效")
check(d2.get("max_rounds") == 2 and abs(d2.get("pass_score") - 6.5) < 1e-6, "轮数/分数线生效")
check(FAKE not in r.text, "写配置的响应也不回显 key")

mode = sh("stat -c '%a' /root/qwen-image-2.1/vision.env 2>/dev/null")
check(mode == "600", "vision.env 权限为 600", f"实际 {mode}")
check(sh("grep -c 'QWEN_VISION_API_KEY' /root/qwen-image-2.1/vision.env") == "1",
      "key 已写入文件")

print("\n=== 4. 空 key 不清覆盖，clear_key 能清 ===")
requests.post(BASE + "/v1/vision/config", headers=H, timeout=30,
              json={"model": "deepseek-flash", "api_key": ""})
d3 = requests.get(BASE + "/v1/vision/config", headers=H, timeout=30).json()
check(d3.get("has_key") is True, "传空 key = 不修改（key 仍在）")
requests.post(BASE + "/v1/vision/config", headers=H, timeout=30, json={"clear_key": True})
d4 = requests.get(BASE + "/v1/vision/config", headers=H, timeout=30).json()
check(d4.get("has_key") is False, "clear_key 能清掉 key")

print("\n=== 5. 假 key 的连通性测试要如实报错 ===")
requests.post(BASE + "/v1/vision/config", headers=H, timeout=30, json={"api_key": FAKE})
r = requests.post(BASE + "/v1/vision/test", headers=H, timeout=120)
t = r.json()
check(r.status_code == 200, "test 端点返回 200（结果在 body 里）")
check(t.get("ok") is False, "假 key → ok=False（不假装成功）")
check(FAKE not in r.text, "错误信息里不回显 key", f"error={str(t.get('error'))[:90]}")
print("     报错：", str(t.get("error"))[:160])

print("\n=== 6. 启动回路（有 key 但会失败在判定阶段）===")
p = TOOLS.parent / "exp" / "galgame-cg-20260928" / "refs" / "char.png"
files = [("image", ("char.png", open(p, "rb"), "image/png"))]
data = {"prompt": "A girl standing in a garden.", "num_inference_steps": "8",
        "width": "1024", "height": "1024", "max_rounds": "1", "pass_score": "9",
        "seed": "42"}
r = requests.post(BASE + "/v1/auto/start", headers=H, data=data, files=files, timeout=120)
check(r.status_code == 202, "启动回路 → 202", f"got {r.status_code} {r.text[:120]}")
job = (r.json() or {}).get("job_id") if r.status_code == 202 else None
check(bool(job), "拿到 job_id", str(job))

if job:
    print("     等回路跑（出图约 10s，然后判定会因假 key 失败）…")
    status = None
    for _ in range(40):
        time.sleep(3)
        rr = requests.get(BASE + f"/v1/auto/status/{job}", headers=H, timeout=30)
        if rr.status_code != 200:
            break
        status = rr.json()
        if status.get("status") in ("done", "finished_unpassed", "failed"):
            break
    check(status is not None, "能查到状态")
    if status:
        print("     最终状态：", status.get("status"), "占位轮次：", status.get("round"))
        print("     日志尾：")
        for line in (status.get("log") or [])[-6:]:
            print("       ", line)
        check(FAKE not in json.dumps(status, ensure_ascii=False),
              "状态里也不含 key")
    rl = requests.get(BASE + "/v1/auto/list", headers=H, timeout=30).json()
    check(any(j["job_id"] == job for j in rl.get("jobs", [])), "list 里能查到该任务")

print("\n=== 7. 停止与文件接口 ===")
if job:
    r = requests.post(BASE + f"/v1/auto/stop/{job}", headers=H, timeout=30)
    check(r.status_code == 200, "stop 返回 200")
r = requests.get(BASE + "/v1/auto/status/nope-nope", headers=H, timeout=30)
check(r.status_code == 404, "不存在的任务 → 404")
r = requests.get(BASE + f"/v1/auto/file/{job}/../../etc/passwd", headers=H, timeout=30)
check(r.status_code in (400, 404), "目录穿越被挡住", f"got {r.status_code}")

# 收尾：把测试用的假 key 清掉，不留在实例上
requests.post(BASE + "/v1/vision/config", headers=H, timeout=30, json={"clear_key": True})
print("\n（已清掉测试用的假 key）")

fwd.shutdown()
c.close()
print()
print(f"断言 {checks} 项，失败 {len(fails)} 项")
for f in fails:
    print("   -", f)
print("结论:", "全部通过" if not fails else "有失败")
sys.exit(0 if not fails else 1)
