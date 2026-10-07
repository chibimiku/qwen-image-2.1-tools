# -*- coding: utf-8 -*-
"""在实例上执行一条命令，容忍这台机特有的"会话建立慢"。

  python tools/_remote_exec.py "curl -s http://127.0.0.1:6006/health"
  python tools/_remote_exec.py "tail -20 /root/autodl-tmp/autostart/boot.log" 120

为什么单独有这个脚本：
  这台实例的 SSH 曾经有个坑 —— `.bashrc` 退路跑的是全量自启流程，撞上 pidfile
  宽限期后每条连接固定卡 ~181 秒才吐第一行（详见 docs/AUTOSTART.md 坑 6）。
  已修（退路加了 `--quick`），但这个脚本的写法依然值得保留：
  · 命令先写成远端脚本文件，再 `exec` 执行 —— 避免长命令在慢会话里被截断
  · 输出边到边 flush，不攒到最后一次性打印，卡住时能立刻看出卡在哪一步
  · 用 `timeout -k` 兜底，远端进程不会因为本地断开而留下孤儿

连接信息来源：环境变量优先（QWEN_HOST/QWEN_PORT/QWEN_USER/QWEN_PASS），
否则用当前在用的 westd 实例。别去读 tools/tunnel.conf 或 tools/autodl_new.env ——
那两套是过期实例（westb / westc），早就不在了。
"""
from __future__ import annotations

import argparse
import os
import sys
import time

import paramiko

# 远端输出里多的是中文与进度符号，Windows 控制台默认 GBK 会打成乱码
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HOST = os.environ.get("QWEN_HOST", "connect.westd.seetacloud.com")
PORT = int(os.environ.get("QWEN_PORT", "26791"))
USER = os.environ.get("QWEN_USER", "root")
PASS = os.environ.get("QWEN_PASS", "xzkx5EgMwhvy")

REMOTE_SCRIPT = "/root/_remote_exec.sh"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("command", help="要在实例上执行的 shell 命令")
    ap.add_argument("budget", nargs="?", type=float, default=180.0,
                    help="最长等待秒数（默认 180）")
    a = ap.parse_args()

    t0 = time.time()
    cli = paramiko.SSHClient()
    cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    cli.connect(HOST, port=PORT, username=USER, password=PASS, timeout=30,
                banner_timeout=120, auth_timeout=120,
                look_for_keys=False, allow_agent=False)
    print(f"[{HOST}:{PORT} 会话建立 {time.time() - t0:.1f}s]", flush=True)

    sftp = paramiko.SFTPClient.from_transport(cli.get_transport())
    with sftp.open(REMOTE_SCRIPT, "w") as f:
        f.write("#!/bin/bash\n" + a.command + "\n")

    chan = cli.get_transport().open_session(timeout=a.budget)
    chan.settimeout(2.0)
    chan.exec_command(f"timeout -k 5 {int(a.budget)} bash {REMOTE_SCRIPT} 2>&1")
    t1 = time.time()
    while time.time() - t1 < a.budget + 30:
        if chan.recv_ready():
            sys.stdout.write(chan.recv(65536).decode("utf-8", "replace"))
            sys.stdout.flush()
        elif chan.exit_status_ready() and not chan.recv_ready():
            time.sleep(0.3)
            while chan.recv_ready():
                sys.stdout.write(chan.recv(65536).decode("utf-8", "replace"))
            break
        else:
            time.sleep(0.1)
    print(f"\n[执行耗时 {time.time() - t1:.1f}s]")
    cli.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
