# -*- coding: utf-8 -*-
"""盯服务的权重加载：等到 loaded=true 或超时，并把加载错误一并报出来。

  python tools/_svc_watch_load.py [超时秒数]

为什么需要单独一个：`/health` 在**权重加载完成之前**就已经返回 `status:"ok"` 了，
所以"能 ping 通 health"不等于"能出图"。真正的就绪判据是 `"loaded":true`，
失败时看 `"load_error"`（实测遇到过 OOM：孤儿进程占着显存，新实例加载失败，
health 照样是 ok，只有 loaded 是 false）。
"""
from __future__ import annotations

import pathlib
import sys
import time

import paramiko

TOOLS = pathlib.Path(__file__).resolve().parent
CFG = {}
for raw in (TOOLS / "autodl_new.env").read_text(encoding="utf-8").splitlines():
    line = raw.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        CFG[k.strip()] = v.strip().strip('"').strip("'")

timeout = int(sys.argv[1]) if len(sys.argv) > 1 else 300

cli = paramiko.SSHClient()
cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())
cli.connect(CFG["AUTODL_HOST"], port=int(CFG["AUTODL_PORT"]), username=CFG["AUTODL_USER"],
            password=CFG["AUTODL_PASS"], timeout=25, allow_agent=False, look_for_keys=False)


def sh(cmd: str, t: int = 300) -> str:
    _, o, e = cli.exec_command(cmd, timeout=t)
    return (o.read().decode("utf-8", "replace") + e.read().decode("utf-8", "replace")).strip()


print("=== 进程与显存 ===")
print(sh("ps -eo pid,etime,rss,cmd | grep \"[s]erver.py\"") or "(无进程)")
print(sh("nvidia-smi --query-gpu=memory.used,memory.free --format=csv,noheader"))
print(sh("nvidia-smi --query-compute-apps=pid,used_memory --format=csv"))

print(f"\n=== 轮询就绪状态（最多 {timeout}s）===")
loaded_at = None
waited = 0
while waited <= timeout:
    h = sh("curl -s --max-time 6 http://127.0.0.1:6006/health")
    is_loaded = '"loaded":true' in h
    is_ok = '"status":"ok"' in h
    err = ""
    if '"load_error":"' in h and '"load_error":null' not in h:
        err = h.split('"load_error":"', 1)[1].split('"', 1)[0][:90]
    tag = "loaded" if is_loaded else ("ok但未加载" if is_ok else "无响应")
    print(f"  [{waited:>3}s] {tag}" + (f"   ERR: {err}" if err else ""))
    if is_loaded:
        loaded_at = waited
        break
    if err:
        print("  -> 加载已失败（load_error 非空），不用再等")
        break
    time.sleep(10)
    waited += 10

print()
if loaded_at is not None:
    print(f"结论: 就绪（等了 {loaded_at}s）")
else:
    print("结论: 未就绪，看下面的日志")
    print(sh("grep -aE 'Loading|OOM|Error|error' /root/qwen-image-2.1/logs/service.log | tail -8")[-1200:])

cli.close()
sys.exit(0 if loaded_at is not None else 1)
