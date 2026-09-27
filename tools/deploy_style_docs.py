# -*- coding: utf-8 -*-
"""把控制台要用的官方文档搬到位，部署，重启，并实测按钮指向的端点。

  python tools/deploy_style_docs.py            # 只做本地同步 + dry-run 看会传什么
  python tools/deploy_style_docs.py --push     # 真部署（含 server.py / index.html / 文档）
  python tools/deploy_style_docs.py --push --restart    # 再重启服务
  python tools/deploy_style_docs.py --check    # 只测远端端点（不动任何东西）

做三件事：
  1. 从 docs/upstream/ 取官方原文，复制进 service/ui/docs/（跟随 service/ 的常规部署载荷）
  2. 可选：调 deploy_service.py 增量上实例，再重启服务
  3. 可选：走 SSH 隧道打 /v1/style-docs* 与 / 两个端点，核对按钮真能打开

复制策略是刻意"复制"而不是"让部署去读仓库根的 docs/"：
  服务端只认 service/ui/docs/，这样部署脚本不用为仓库根另开一条传输规则；
  代价是两份文件可能漂移，所以 --check-sync 会比对哈希并报警。
"""
from __future__ import annotations

import argparse
import hashlib
import pathlib
import shutil
import subprocess
import sys
import threading
import time

import paramiko
import requests

TOOLS = pathlib.Path(__file__).resolve().parent
ROOT = TOOLS.parent
UP = ROOT / "docs" / "upstream"
DST = ROOT / "service" / "ui" / "docs"

# 源（docs/upstream 里的官方原文）→ 目标文件名（控制台按钮指向的名字）
COPY = {
    "prompt-rewriter-T2I-system-prompt.txt": "prompt-rewriter-T2I-system-prompt.txt",
    "prompt-rewriter-I2I-system-prompt.txt": "prompt-rewriter-I2I-system-prompt.txt",
    "qwen-image-2.1-hf-modelcard.md": "qwen-image-2.1-hf-modelcard.md",
}
# 控制台最需要的那两份：漂移检查以它们为准
CRITICAL = ["prompt-rewriter-T2I-system-prompt.txt",
            "prompt-rewriter-I2I-system-prompt.txt"]


def sha256(p: pathlib.Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for c in iter(lambda: fh.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def sync() -> int:
    DST.mkdir(parents=True, exist_ok=True)
    for src_name, dst_name in COPY.items():
        src = UP / src_name
        if not src.exists():
            print(f"  !! 缺源文件：{src}")
            return 1
        dst = DST / dst_name
        same = dst.exists() and sha256(src) == sha256(dst)
        if not same:
            shutil.copyfile(src, dst)
        print(f"  {'unchanged' if same else 'copied   '} {dst_name}  "
              f"({src.stat().st_size} B, sha256 {sha256(src)[:12]}…)")
    return 0


def check_sync() -> int:
    bad = 0
    for name in CRITICAL:
        a, b = UP / name, DST / name
        if not (a.exists() and b.exists()):
            print(f"  !! missing: {name} (upstream={a.exists()} ui={b.exists()})")
            bad += 1
            continue
        ha, hb = sha256(a), sha256(b)
        state = "OK" if ha == hb else "DRIFT"
        print(f"  {state:<6} {name}  upstream={ha[:12]}… ui={hb[:12]}…")
        bad += 0 if ha == hb else 1
    return 0 if not bad else 1


def ssh_cfg() -> dict:
    cfg = {}
    for raw in (TOOLS / "autodl_new.env").read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            cfg[k.strip()] = v.strip().strip('"').strip("'")
    return cfg


def endpoint_check(with_key: bool = True) -> int:
    sys.path.insert(0, str(TOOLS))
    import autodl_ssh
    cfg = ssh_cfg()
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(cfg["AUTODL_HOST"], port=int(cfg["AUTODL_PORT"]), username=cfg["AUTODL_USER"],
              password=cfg["AUTODL_PASS"], timeout=25, banner_timeout=30, auth_timeout=30,
              allow_agent=False, look_for_keys=False)
    fwd = autodl_ssh.ForwardServer(("127.0.0.1", 16055), autodl_ssh.Handler)
    fwd.dst_host, fwd.dst_port = "127.0.0.1", 6006
    fwd.transport = c.get_transport()
    threading.Thread(target=fwd.serve_forever, daemon=True).start()
    time.sleep(0.4)
    base = "http://127.0.0.1:16055"

    key = ""
    for line in (TOOLS / ".qwenkey").read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.strip().startswith("#"):
            key = line.strip()
            break
    q = f"?key={key}" if (with_key and key) else ""

    rc = 0
    try:
        h = requests.get(base + "/health", timeout=20).json()
        print(f"  /health          200  mock={h.get('mock')} loaded={h.get('loaded')}")
    except Exception as exc:                                            # noqa: BLE001
        print(f"  /health          FAIL {type(exc).__name__}: {exc}")
        fwd.shutdown(); c.close(); return 1

    # 控制台页面必须带上替换后的 key
    try:
        page = requests.get(base + "/", timeout=20).text
        has_row = 'id="docrow"' in page
        leftover = "__QWEN_DOC_KEY__" in page
        doc_key = 'href="/v1/style-docs?key=' in page
        print(f"  /                {'有' if has_row else '没有'} docrow，"
              f"占位符{'未' if leftover else '已'}替换，"
              f"链接{'带' if doc_key else '不带'} key")
        if not has_row or leftover:
            rc = 1
    except Exception as exc:                                            # noqa: BLE001
        print(f"  /                FAIL {type(exc).__name__}: {exc}")
        rc = 1

    for path in ("/v1/style-docs", "/v1/style-docs/prompt-rewriter-T2I-system-prompt.txt",
                 "/v1/style-docs/prompt-rewriter-I2I-system-prompt.txt",
                 "/v1/style-docs/qwen-image-2.1-prompt-rewriting.md",
                 "/v1/style-docs/qwen-image-2.1-hf-modelcard.md",
                 "/v1/style-docs/nope.txt"):
        try:
            r = requests.get(base + path + q, timeout=25, allow_redirects=False)
            body = r.content[:70].decode("utf-8", "replace").replace("\n", " ")
            print(f"  {path:<56} {r.status_code}  {len(r.content):>7} B  "
                  f"{r.headers.get('content-type','')[:32]}  {body[:44]}")
            want = 404 if path.endswith("nope.txt") else 200
            if r.status_code != want:
                rc = 1
        except Exception as exc:                                        # noqa: BLE001
            print(f"  {path:<56} FAIL {type(exc).__name__}")
            rc = 1

    # token 计数接口：数值要和管线自己的 tokenizer 对得上
    try:
        hdrs = {"Authorization": f"Bearer {key}"} if key else {}
        r = requests.post(base + "/v1/tokenize",
                          json={"prompt": "a red teapot on a wooden table", "t2i": True},
                          headers=hdrs, timeout=120)
        d = r.json()
        print(f"  /v1/tokenize                                    {r.status_code}  "
              f"wrapped={d.get('wrapped_tokens')} overhead={d.get('template_overhead_tokens')} "
              f"total={d.get('total_positions')}/{d.get('max_positions')} "
              f"over={d.get('over_limit')}")
        if r.status_code != 200 or d.get("wrapped_tokens") != 30:
            rc = 1
            print("     ^ 期望 wrapped_tokens=30（短句 8 + 模板 22）")
        r2 = requests.post(base + "/v1/tokenize",
                           json={"prompt": "hi", "width": 1024, "height": 1024},
                           headers=hdrs, timeout=180)
        d2 = r2.json()
        print(f"  /v1/tokenize (1024² 参考图)                       {r2.status_code}  "
              f"vision={d2.get('vision_tokens')} total={d2.get('total_positions')}")
        if d2.get("vision_tokens") != 1024:
            rc = 1
            print("     ^ 期望 vision_tokens=1024（实测标定值）")
    except Exception as exc:                                            # noqa: BLE001
        print(f"  /v1/tokenize                                    FAIL {type(exc).__name__}: {exc}")
        rc = 1

    # 不带 key 时应 401（证明守卫还在）
    try:
        r = requests.get(base + "/v1/style-docs", timeout=20)
        print(f"  /v1/style-docs   未带 key -> {r.status_code}（期望 401）")
        if r.status_code == 200 and key:
            rc = 1
    except Exception as exc:                                            # noqa: BLE001
        print(f"  no-key probe FAIL {type(exc).__name__}")

    print(f"  [endpoint] {'PASS' if rc == 0 else 'FAIL'}")
    fwd.shutdown(); c.close()
    return rc


def remote_listing() -> None:
    cfg = ssh_cfg()
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(cfg["AUTODL_HOST"], port=int(cfg["AUTODL_PORT"]), username=cfg["AUTODL_USER"],
              password=cfg["AUTODL_PASS"], timeout=25, allow_agent=False, look_for_keys=False)
    for label, cmd in (
        ("instance docs dir", "ls -la /root/qwen-image-2.1/service/ui/docs/ 2>&1"),
        ("server hash", "sha256sum /root/qwen-image-2.1/service/server.py"),
        ("ui mtime", "stat -c '%y %n' /root/qwen-image-2.1/service/ui/index.html"),
        ("service log tail", "tail -6 /root/qwen-image-2.1/logs/service.log 2>&1"),
    ):
        _, out, err = c.exec_command(cmd, timeout=60)
        print(f"--- {label} ---")
        print((out.read().decode("utf-8", "replace") or
               err.read().decode("utf-8", "replace")).rstrip())
    c.close()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--push", action="store_true", help="部署到实例")
    ap.add_argument("--restart", action="store_true", help="部署后重启服务")
    ap.add_argument("--check", action="store_true", help="只测远端端点")
    ap.add_argument("--check-sync", action="store_true", help="只比对 docs/upstream 与 ui/docs")
    ap.add_argument("--list", action="store_true", help="列远端目录与日志")
    a = ap.parse_args()

    if a.check_sync:
        print("[sync] docs/upstream vs service/ui/docs")
        return check_sync()

    if a.check:
        print("[endpoint] 远端实测")
        return endpoint_check()

    if a.list:
        remote_listing()
        return 0

    print("[1] 本地同步 docs/upstream -> service/ui/docs")
    rc = sync()
    if rc:
        return rc
    bad = check_sync()
    if bad:
        print("  !! 同步后仍有漂移，手工查一下")

    if not a.push:
        print("\n[dry-run] 想真部署加 --push（--push --restart 会顺带重启服务）")
        return 0

    print("\n[2] 部署（service/ 载荷，含 ui/docs）")
    # 直接在本进程里调 deploy_service.main()：Windows 沙箱下用 subprocess 捕获管道会 EPERM，
    # 而且这里也不需要另开进程。凭据从 autodl_new.env 读，走环境变量传给部署脚本。
    import os as _os
    cfg = ssh_cfg()
    _os.environ.setdefault("AUTODL_HOST", cfg["AUTODL_HOST"])
    _os.environ.setdefault("AUTODL_PORT", str(cfg["AUTODL_PORT"]))
    _os.environ.setdefault("AUTODL_USER", cfg["AUTODL_USER"])
    _os.environ.setdefault("AUTODL_PASS", cfg["AUTODL_PASS"])
    sys.path.insert(0, str(TOOLS))
    import deploy_service
    saved_argv = sys.argv
    try:
        sys.argv = [str(TOOLS / "deploy_service.py")]
        rc2 = deploy_service.main()
    finally:
        sys.argv = saved_argv
    print(f"  deploy_service 返回 {rc2}")

    if a.restart:
        print("\n[3] 重启服务")
        cfg = ssh_cfg()
        c = paramiko.SSHClient()
        c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        c.connect(cfg["AUTODL_HOST"], port=int(cfg["AUTODL_PORT"]),
                  username=cfg["AUTODL_USER"], password=cfg["AUTODL_PASS"],
                  timeout=25, allow_agent=False, look_for_keys=False)
        _, out, err = c.exec_command(
            "bash /root/qwen-image-2.1/scripts/serve.sh restart 2>&1 | tail -20", timeout=300)
        print(out.read().decode("utf-8", "replace"))
        print(err.read().decode("utf-8", "replace"))
        print("  等服务起来（重新加载权重要十几秒才会监听端口）…")
        for attempt in range(12):
            time.sleep(10)
            try:
                _, o2, _ = c.exec_command("curl -s -m 5 -o /dev/null -w '%{http_code}' "
                                          "localhost:6006/health", timeout=30)
                code = o2.read().decode("utf-8", "replace").strip()
                if code == "200":
                    print(f"  实例内 /health 200（等了 {(attempt + 1) * 10}s）")
                    break
            except Exception:                                           # noqa: BLE001
                pass
        else:
            print("  等了 120s 还没就绪，下面照样跑端点检查")
            _, o3, _ = c.exec_command("tail -20 /root/qwen-image-2.1/logs/service.log",
                                      timeout=60)
            print(o3.read().decode("utf-8", "replace"))
        c.close()

    print("\n[4] 端点实测")
    return endpoint_check()


if __name__ == "__main__":
    sys.exit(main())
