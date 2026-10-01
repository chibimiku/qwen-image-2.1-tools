# -*- coding: utf-8 -*-
"""摸清实例的持久化边界与可用的开机自启入口。

  python tools/_autostart_probe.py
"""
from __future__ import annotations

import pathlib
import sys

import paramiko

TOOLS = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))

CFG = {}
for raw in (TOOLS / "autodl_new.env").read_text(encoding="utf-8").splitlines():
    line = raw.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        CFG[k.strip()] = v.strip().strip('"').strip("'")

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(CFG["AUTODL_HOST"], port=int(CFG["AUTODL_PORT"]), username=CFG["AUTODL_USER"],
          password=CFG["AUTODL_PASS"], timeout=25, allow_agent=False, look_for_keys=False)


def sh(cmd: str, t: int = 180) -> str:
    _, o, e = c.exec_command(cmd, timeout=t)
    return (o.read().decode("utf-8", "replace") + e.read().decode("utf-8", "replace")).strip()


print("=== 1. 独立挂载点（跨容器重建保留的路径）===")
print(sh("cat /proc/mounts | grep -vE 'proc|sysfs|cgroup|devpts|mqueue|shm|tmpfs|autofs' "
         "| awk '{print $2, $3, $1}' | sort -u | head -25"))

print("\n=== 2. 根文件系统是不是 overlay（上层容器重建即丢）===")
print(sh("grep -E ' / ' /proc/mounts"))

print("\n=== 3. 镜像里有没有现成的 autodl.sh 模板 ===")
print(sh("find / -xdev -name 'autodl.sh*' 2>/dev/null | head -10") or "(没有)")
print("autodl-init:", sh("ls -la /etc/autodl-init 2>&1"))

print("\n=== 4. /root 下与 /etc 下的时间戳对比（谁被重置过）===")
print(sh("stat -c '%y  %n' /etc /etc/passwd /etc/autodl-init /root /root/.bashrc "
         "/root/qwen-image-2.1 /init/bin/customer.cmd.sh 2>&1"))

print("\n=== 5. 可用的启动钩子候选 ===")
for p in ("/etc/autodl.sh", "/etc/rc.local", "/root/.bashrc", "/root/.bash_profile",
          "/etc/profile.d/", "/init/bin/customer.cmd.sh"):
    exists = sh(f"test -e {p} && echo yes || echo no")
    writable = sh(f"test -w {p} && echo yes || echo no")
    print(f"   {p:<34} 存在={exists:<4} 可写={writable}")

print("\n=== 6. .bashrc 是否会被非交互 shell 读到（SSH 命令式登录）===")
print("BASH_ENV:", sh("echo $BASH_ENV") or "(空)")
print("非交互测试:", sh("bash -c 'echo $PS1' >/dev/null 2>&1; "
                       "grep -c 'bashrc' /root/.bashrc 2>/dev/null || echo 0"))

print("\n=== 7. 上次启动留下的日志 ===")
print(sh("cat /tmp/autodl.sh.log 2>&1"))
print("boot 相关:", sh("ls -la /tmp/*.log 2>/dev/null | head -8"))

c.close()
