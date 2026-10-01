# -*- coding: utf-8 -*-
"""精确看清实例上 Qwen 服务的进程与显存占用（排除自身 SSH 命令行的干扰）。

  python tools/_svc_procs.py

为什么要有这个：`pgrep -f "service/server.py"` 会把**执行这条 pgrep 命令的 ssh 会话**
自己也匹配上（它的命令行里就含这个字符串），于是输出里冒出一串永远不会消失的 pid，
看起来像"杀不干净"。真正的判据是：
  · 进程：ps 里 cmd 以 python 开头且参数指向 server.py
  · 显存：nvidia-smi --query-compute-apps 列出的 pid
"""
from __future__ import annotations

import pathlib
import sys

import paramiko

TOOLS = pathlib.Path(__file__).resolve().parent
CFG = {}
for raw in (TOOLS / "autodl_new.env").read_text(encoding="utf-8").splitlines():
    line = raw.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        CFG[k.strip()] = v.strip().strip('"').strip("'")

cli = paramiko.SSHClient()
cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())
cli.connect(CFG["AUTODL_HOST"], port=int(CFG["AUTODL_PORT"]), username=CFG["AUTODL_USER"],
            password=CFG["AUTODL_PASS"], timeout=25, allow_agent=False, look_for_keys=False)


def sh(cmd: str, t: int = 300) -> str:
    _, o, e = cli.exec_command(cmd, timeout=t)
    return (o.read().decode("utf-8", "replace") + e.read().decode("utf-8", "replace")).strip()


# 精确匹配：cmd 是 python 且在跑 service/server.py（不匹配任何含该字符串的别的东西）
PY = "ps -eo pid,etime,rss,cmd --no-headers | awk '$4 ~ /python/ && $0 ~ /service\\/server\\.py/ {print}'"

print("=== 真正的服务进程 ===")
print(sh(PY) or "(无)")

print("\n=== 显存占用进程（权威）===")
apps = sh("nvidia-smi --query-compute-apps=pid,used_memory --format=csv,noheader")
print(apps or "(无进程占显存)")

print("\n=== GPU 总览 ===")
print(sh("nvidia-smi --query-gpu=memory.used,memory.free --format=csv,noheader"))

print("\n=== pidfile ===")
print(sh("cat /root/qwen-image-2.1/service.pid 2>/dev/null") or "(无)")

print("\n=== 6006 的 LISTEN（/proc/net/tcp，6006=0x1776）===")
print(sh("grep -i ':1776 ' /proc/net/tcp | head -3") or "(没有)")

print("\n=== health ===")
print(sh("curl -s --max-time 6 http://127.0.0.1:6006/health | head -c 220") or "(无响应)")

cli.close()
