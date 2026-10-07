# -*- coding: utf-8 -*-
"""实例重启后验证自启：webui 自己起来了吗？

  python tools/_autostart_verify.py                # 等 SSH 最多 10 分钟，然后验证
  python tools/_autostart_verify.py --wait 1800    # 等更久
  python tools/_autostart_verify.py --no-wait      # 只试一次，立刻出结论

只读，不改任何东西。开机后跑它，看四件事：
  1. `/init/bin/customer.cmd.sh` 的引导行**在不在** —— 容器重建会把 /init 按镜像还原，
     这行丢了就没有容器启动触发了（本次修过一次：原来从来没贴过）
  2. `boot.log` 里重启后有没有触发记录、走了哪条分支
  3. `/health` 是不是 ok、**`loaded` 是不是 true**（health ok 但 loaded false 等于不能出图）
  4. 平台入口 8443 通不通（网关 404 = 后端没监听）

如果第 1 项没了、或服务没起来，按最后打印的建议走（tools/deploy_autostart.py）。
"""
from __future__ import annotations

import argparse
import json
import socket
import sys
import time
import urllib.request

import paramiko

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HOST = "connect.westd.seetacloud.com"
PORT = 26791
USER = "root"
PASS = "xzkx5EgMwhvy"
ENTRY = "https://u57736-math-74f052d3.westd.seetacloud.com:8443"


def wait_ssh(deadline: float) -> paramiko.SSHClient | None:
    delay, n = 3.0, 0
    while True:
        n += 1
        try:
            cli = paramiko.SSHClient()
            cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            cli.connect(HOST, port=PORT, username=USER, password=PASS, timeout=15,
                        banner_timeout=60, auth_timeout=60,
                        look_for_keys=False, allow_agent=False)
            print(f"[SSH] 第 {n} 次尝试连上（{HOST}:{PORT}）")
            return cli
        except Exception as e:
            print(f"[SSH] 第 {n} 次失败: {type(e).__name__} {str(e)[:60]}")
            if time.time() > deadline:
                return None
            time.sleep(delay)
            delay = min(delay * 1.6, 20.0)


def sh(cli: paramiko.SSHClient, cmd: str, timeout: int = 120) -> str:
    chan = cli.get_transport().open_session(timeout=timeout)
    chan.settimeout(2.0)
    chan.exec_command(f"timeout -k 5 {timeout} bash -c " + "'" + cmd.replace("'", "'\"'\"'") + "'")
    buf, t0 = b"", time.time()
    while time.time() - t0 < timeout:
        got = False
        while chan.recv_ready():
            buf += chan.recv(65536)
            got = True
        if got:
            t0 = time.time()
        elif chan.exit_status_ready() and not chan.recv_ready():
            time.sleep(0.3)
            while chan.recv_ready():
                buf += chan.recv(65536)
            break
        else:
            time.sleep(0.1)
    chan.close()
    return buf.decode("utf-8", "replace")


def entry_health() -> tuple[str, str]:
    try:
        with urllib.request.urlopen(f"{ENTRY}/health", timeout=20) as r:
            return f"HTTP {r.status}", r.read(200).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return f"HTTP {e.code}", ""
    except Exception as e:
        return type(e).__name__, str(e)[:80]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--wait", type=float, default=600.0, help="等 SSH 恢复的最长秒数")
    ap.add_argument("--no-wait", action="store_true", help="只试一次")
    a = ap.parse_args()

    t0 = time.time()
    cli = wait_ssh(time.time() + (0 if a.no_wait else a.wait))
    if cli is None:
        print("\n[结论] SSH 还没回来 —— 实例可能还没开机，或开机后 SSH 还没起。")
        return 2
    print(f"[SSH] 会话建立用时 {time.time() - t0:.1f}s\n")

    problems: list[str] = []

    print("=== 1. /init 引导行（容器重建会还原，丢了就没有启动触发）===")
    hook = sh(cli, "grep -c qwen-autostart /init/bin/customer.cmd.sh 2>/dev/null || echo 0")
    n_hook = hook.strip().splitlines()[-1] if hook.strip() else "0"
    print(f"  customer.cmd.sh 命中 {n_hook} 处")
    tail = sh(cli, "tail -3 /init/bin/customer.cmd.sh")
    for line in tail.strip().splitlines():
        print("   ", line)
    if n_hook == "0":
        problems.append("/init 引导行丢了 → 跑 tools/deploy_autostart.py 重贴")

    print("\n=== 2. .bashrc 退路（登录路径，应为 --quick）===")
    br = sh(cli, "head -3 /root/.bashrc")
    for line in br.strip().splitlines():
        print("   ", line)
    if "--quick" not in br:
        problems.append(".bashrc 退路不是 --quick → 每条 ssh 会卡宽限期，跑 deploy_autostart.py")

    print("\n=== 3. 自启记录（重启后走了哪条分支）===")
    for line in sh(cli, "tail -14 /root/autodl-tmp/autostart/boot.log").strip().splitlines():
        print("   ", line)

    print("\n=== 4. 服务状态 ===")
    local = sh(cli, "curl -s --max-time 8 http://127.0.0.1:6006/health")
    print("  本机 /health:", local.strip()[:220] or "(无响应)")
    loaded = '"loaded":true' in local
    ok = '"status":"ok"' in local
    print(f"  status ok = {ok}    loaded true = {loaded}")
    if not ok:
        problems.append("本机 6006 /health 不通 → 服务没起来，在实例上跑 bash /root/autodl-tmp/autostart/qwen-autostart.sh")
    elif not loaded:
        problems.append("health ok 但 loaded=false → 权重没加载完或加载失败，看 service.log 与 load_error")

    print("\n=== 5. 平台入口 8443 ===")
    code, body = entry_health()
    print(f"  {ENTRY}/health -> {code} {body[:120]}")
    if "200" not in code:
        problems.append(f"平台入口不是 200（{code}）→ 后端没监听，先修服务再看映射")

    cli.close()

    print("\n" + "=" * 56)
    if not problems:
        print("[结论] 自启正常：服务自己起来了，loaded=true，平台入口 200。")
        return 0
    print("[结论] 有需要处理的地方：")
    for p in problems:
        print("   -", p)
    print("\n修复入口：python tools/deploy_autostart.py（上传脚本 + 重贴 /init 与 .bashrc 引导）")
    return 1


if __name__ == "__main__":
    sys.exit(main())
