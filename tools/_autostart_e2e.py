# -*- coding: utf-8 -*-
"""端到端验证开机自启：停服务 → 按启动时的调用方式触发 → 确认自己回来。

  python tools/_autostart_e2e.py

验证两条链路，且**分别验证**（不能只测一条就说"自启可用"）：
  1. /init/bin/customer.cmd.sh —— AutoDL 每次容器启动都会跑它（主链路）
  2. ~/.bashrc —— 任何登录 shell 触发（退路）

注意：本脚本会**停掉正在跑的服务**。验证窗口约 20 秒，之后服务会恢复。
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


def connect():
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(CFG["AUTODL_HOST"], port=int(CFG["AUTODL_PORT"]), username=CFG["AUTODL_USER"],
              password=CFG["AUTODL_PASS"], timeout=25, allow_agent=False, look_for_keys=False)
    return c


def main() -> int:
    c = connect()

    def sh(cmd: str, t: int = 300) -> str:
        _, o, e = c.exec_command(cmd, timeout=t)
        return (o.read().decode("utf-8", "replace") + e.read().decode("utf-8", "replace")).strip()

    def health() -> str:
        return sh("curl -s --max-time 5 http://127.0.0.1:6006/health 2>/dev/null")

    def wait_health(timeout: int) -> bool:
        for _ in range(timeout // 5):
            h = health()
            if '"status":"ok"' in h:
                return True
            time.sleep(5)
        return False

    fails: list[str] = []

    def check(cond: bool, label: str, extra: str = "") -> None:
        print(("  OK   " if cond else "  FAIL ") + label + (("  " + extra) if extra else ""))
        if not cond:
            fails.append(label)

    print("=== 前置状态 ===")
    before = health()
    check('"status":"ok"' in before, "测试前服务是活的")
    check('"mock":false' in before, "不是 mock 模式")

    # ── 链路 1：customer.cmd.sh（主链路）──────────────────────────────────
    print("\n=== 链路 1：/init/bin/customer.cmd.sh（容器启动时执行的那个）===")
    sh("bash /root/qwen-image-2.1/scripts/serve.sh stop 2>&1 | tail -2")
    time.sleep(3)
    check('"status":"ok"' not in health(), "服务已停（为验证腾出位置）")

    # 完全按 boot 的方式跑：customer.cmd.sh 内部就是 bash 这个文件
    out = sh("bash /init/bin/customer.cmd.sh 2>&1 | tail -5")
    print("       customer.cmd.sh 输出:", (out or "(空)")[:160].replace("\n", " | "))

    def mode_of(h: str) -> str:
        return "mock" if '"mock":true' in h else ("real" if '"mock":false' in h else "?")

    ok = wait_health(180)
    h = health()
    check(ok, "服务被自启拉起来了", "mode=" + mode_of(h))
    check('"mock":false' in h, "起来的是真实模式，不是 mock")

    print("       自启记录:")
    for line in sh("tail -5 /root/autodl-tmp/autostart/boot.log 2>/dev/null").splitlines():
        print("         " + line)

    # ── 链路 2：~/.bashrc（退路）──────────────────────────────────────────
    print("\n=== 链路 2：~/.bashrc（登录 shell 触发）===")
    sh("bash /root/qwen-image-2.1/scripts/serve.sh stop 2>&1 | tail -1")
    sh("rm -f /root/qwen-image-2.1/service.pid")     # 别让陈旧 pidfile 影响判定
    time.sleep(3)
    check('"status":"ok"' not in health(), "服务已停")

    # 关键：本机 .bashrc 开头有 `[ -z "$PS1" ] && return`，非交互 shell 会在那里返回。
    # 所以退路必须插在它**之前**才有效 —— 这里就用非交互 shell 验证（最严的路径）。
    print("       退路在 .bashrc 中的行号 vs 提前 return 的行号:")
    print("         " + sh("grep -n 'qwen-autostart\\|PS1' /root/.bashrc | head -4")
          .replace("\n", "\n         "))
    sh("bash -c 'source /root/.bashrc' 2>&1 | tail -3")
    ok2 = wait_health(180)
    h2 = health()
    check(ok2, "退路也能把服务拉起来（非交互 shell 路径）", "mode=" + mode_of(h2))
    check('"mock":false' in h2, "退路起来的是真实模式")

    # ── 并发触发（最关键的回归）：服务正在加载权重时再触发一次不能换进程 ──
    #
    # 这条是实测踩出来的：服务从启动到 /health 200 要十几秒，期间 alive() 为假。
    # 没有宽限期时，任何一次并发触发都会删掉 pidfile 再拉一个，把正在加载权重的
    # 实例挤掉（pidfile 指向新进程、旧进程变孤儿）—— 跑出过 5285→5647。
    print("\n=== 并发触发：加载窗口内重复触发不能换进程 ===")
    sh("bash /root/qwen-image-2.1/scripts/serve.sh stop >/dev/null 2>&1")
    sh("rm -f /root/qwen-image-2.1/service.pid")
    time.sleep(2)
    sh("bash /root/autodl-tmp/autostart/qwen-autostart.sh >/dev/null 2>&1")
    time.sleep(3)
    pid1 = sh("cat /root/qwen-image-2.1/service.pid 2>/dev/null").strip()
    print(f"       第一次触发后 pidfile={pid1}")
    # 加载还没完成时再触发两次
    sh("bash /root/autodl-tmp/autostart/qwen-autostart.sh >/dev/null 2>&1")
    sh("bash /init/bin/customer.cmd.sh >/dev/null 2>&1")
    time.sleep(4)
    pid2 = sh("cat /root/qwen-image-2.1/service.pid 2>/dev/null").strip()
    check(pid1 == pid2 and bool(pid1), "加载窗口内的重复触发没有换进程",
          f"pid {pid1} -> {pid2}")
    check(wait_health(240), "最终仍然正常就绪", "mode=" + mode_of(health()))

    # ── 幂等：服务已就绪后再触发 ──────────────────────────────────────────
    print("\n=== 幂等：就绪状态下重复触发 ===")
    pid_before = sh("cat /root/qwen-image-2.1/service.pid 2>/dev/null").strip()
    sh("bash /root/autodl-tmp/autostart/qwen-autostart.sh >/dev/null 2>&1")
    sh("bash /init/bin/customer.cmd.sh >/dev/null 2>&1")
    time.sleep(4)
    pid_after = sh("cat /root/qwen-image-2.1/service.pid 2>/dev/null").strip()
    check(pid_before == pid_after and bool(pid_before),
          "状态未变，没有换进程", f"pid {pid_before} -> {pid_after}")

    # 这个镜像里**没有 ss、也没有 netstat**（实测 `ss: command not found`）——
    # 之前用 `ss -ltn | grep` 判定监听，恒为 0，属于无效判据。
    # 用 /proc/net/tcp 兜底：6006 = 0x1776，状态 0A = LISTEN。
    # 再补一条：GPU 上挂着的服务进程必须只有一个，这条能直接抓住"孤儿进程占显存"。
    def listen_count() -> str:
        return sh("awk '$2 ~ /:1776$/ && $4 == \"0A\" {n++} END {print n+0}' /proc/net/tcp").strip()

    def gpu_procs() -> int:
        out = sh("nvidia-smi --query-compute-apps=pid --format=csv,noheader 2>/dev/null")
        return len([x for x in out.split() if x.strip().isdigit()])

    lc = listen_count()
    check(lc == "1", "6006 只有一个 LISTEN socket（/proc/net/tcp）", f"listening={lc}")
    gp = gpu_procs()
    check(gp == 1, "GPU 上只有一个服务进程（无孤儿）", f"gpu_procs={gp}")

    # ── 陈旧 pidfile：伪造一个死 pid，看脚本能不能自己清掉并启动 ──────────
    print("\n=== 陈旧 pidfile 的场景 ===")
    sh("bash /root/qwen-image-2.1/scripts/serve.sh stop >/dev/null 2>&1")
    sh("echo 999999 > /root/qwen-image-2.1/service.pid")   # 一个肯定不存在的 pid
    time.sleep(2)
    check('"status":"ok"' not in health(), "服务已停，且 pidfile 被伪造成死 pid")
    sh("bash /root/autodl-tmp/autostart/qwen-autostart.sh >/dev/null 2>&1")
    ok3 = wait_health(180)
    check(ok3, "自启能识破陈旧 pidfile 并正常拉起", "mode=" + mode_of(health()))

    print("\n=== 收尾状态 ===")
    print("  等服务就绪（最后一次测试刚拉起来，权重加载要十几秒）…")
    ready = wait_health(300)
    h = health()
    check(ready, "收尾时 /health 返回 ok")
    check('"loaded":true' in h, "权重已完全加载",
          "loaded=" + ("true" if '"loaded":true' in h else "false"))
    # 加载失败会写在 load_error 里（实测遇到过一次 OOM：孤儿进程占了 28 GiB，
    # 新实例加载失败，health 仍是 ok 但 loaded=false、load_error 有内容）
    if '"load_error":"' in h and '"load_error":null' not in h:
        err = h.split('"load_error":"', 1)[1].split('"', 1)[0]
        check(False, "没有加载错误", err[:120])
    else:
        check(True, "没有加载错误")
    check('"mock":false' in h, "收尾时是真实模式")
    print("  health:", h[:130] or "(无)")
    print("  公网入口:", sh("curl -s -m 10 -o /dev/null -w '%{http_code}' "
                           "https://u57736-800d-68da697c.westc.seetacloud.com:8443/health "
                           "2>/dev/null || echo n/a"))

    c.close()
    print()
    print(f"结论: {'两条链路都通过' if not fails else '%d 项失败' % len(fails)}")
    for f in fails:
        print("   -", f)
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
