#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""把仓库里的 service/ 部署到 AutoDL 实例（不含模型权重）。

`service/` 的结构与实例上的 /root/qwen-image-2.1/ 一一对应，所以这里是**整树镜像**，
不是东一个西一个地传文件：

    service/server.py              -> /root/qwen-image-2.1/service/server.py
    service/ui/index.html          -> /root/qwen-image-2.1/service/ui/index.html
    service/scripts/serve.sh       -> /root/qwen-image-2.1/scripts/serve.sh
    service/scripts/qwen_env.sh    -> /root/qwen-image-2.1/qwen_env.sh   ← 特例，见下
    ...

两个刻意的例外：
  1. qwen_env.sh 里存着**真实 key**，实例上那份是真值、仓库里那份是占位符。
     默认**不覆盖**已经存在的远端文件；要覆盖得显式加 --force-env。
  2. __pycache__ / *.ipynb_checkpoints 之类一律跳过。

用法：
  python tools/deploy_service.py                  # 用 tools/autodl.env 里的凭据，只传有变化的
  python tools/deploy_service.py --dry-run        # 只列出会传什么、跳什么
  python tools/deploy_service.py --force          # 连没变化的也重传
  python tools/deploy_service.py --force-env      # 连 qwen_env.sh 也覆盖（会换掉远端 key！）
  python tools/deploy_service.py --host H --port P --password PW

凭据优先取命令行参数，其次环境变量 AUTODL_*，最后 tools/autodl.env（git-ignored）。
"""
from __future__ import annotations

import argparse
import hashlib
import os
import pathlib
import posixpath
import sys

try:
    import paramiko
except ImportError:                                                    # noqa: BLE001
    print("需要 paramiko：pip install paramiko")
    raise SystemExit(2)

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT / "service"
REMOTE_ROOT = "/root/qwen-image-2.1"

SKIP_DIRS = {"__pycache__", ".ipynb_checkpoints", ".git", ".pytest_cache"}
SKIP_EXT = {".pyc", ".pyo", ".log"}

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import deploy_manifest as M  # noqa: E402  路径映射与 check_deploy 共用一份

PROTECTED = M.PROTECTED_BASENAMES     # 不覆盖已有远端文件，除非 --force-env


def remote_path_for(rel: str) -> str | None:
    """仓库相对路径（如 service/scripts/serve.sh）→ 实例相对路径。"""
    return M.repo_to_remote(f"service/{rel}")


def local_files() -> list[tuple[str, pathlib.Path]]:
    out = []
    for p in sorted(SRC.rglob("*")):
        if not p.is_file():
            continue
        if any(part in SKIP_DIRS for part in p.parts):
            continue
        if p.suffix in SKIP_EXT:
            continue
        rel = p.relative_to(SRC).as_posix()
        out.append((rel, p))
    return out


def md5_bytes(b: bytes) -> str:
    return hashlib.md5(b).hexdigest()


def load_env_file(path: pathlib.Path) -> dict:
    env = {}
    if not path.exists():
        return env
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def connect(host: str, port: int, user: str, password: str) -> paramiko.SSHClient:
    last = None
    for kwargs in ({}, {"disabled_algorithms": {"pubkeys": ["rsa-sha2-512", "rsa-sha2-256"]}}):
        try:
            c = paramiko.SSHClient()
            c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            c.connect(host, port=port, username=user, password=password,
                      timeout=30, banner_timeout=30, auth_timeout=30,
                      allow_agent=False, look_for_keys=False, **kwargs)
            return c
        except paramiko.AuthenticationException as exc:                 # noqa: PERF203
            last = exc
    raise last


def remote_md5(sftp: paramiko.SFTPClient, path: str) -> str | None:
    try:
        with sftp.file(path, "rb") as fh:
            return md5_bytes(fh.read())
    except IOError:
        return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host")
    ap.add_argument("--port", type=int)
    ap.add_argument("--user", default=None)
    ap.add_argument("--password")
    ap.add_argument("--remote-root", default=REMOTE_ROOT)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true", help="连没变化的也重传")
    ap.add_argument("--force-env", action="store_true",
                    help="覆盖远端的 qwen_env.sh（会换掉实例上的真实 key，慎用）")
    args = ap.parse_args()

    env = load_env_file(ROOT / "tools" / "autodl.env")
    host = args.host or os.environ.get("AUTODL_HOST") or env.get("AUTODL_HOST")
    port = args.port or int(os.environ.get("AUTODL_PORT") or env.get("AUTODL_PORT") or 0)
    user = args.user or os.environ.get("AUTODL_USER") or env.get("AUTODL_USER") or "root"
    password = args.password or os.environ.get("AUTODL_PASS") or env.get("AUTODL_PASS")

    if not (host and port and password):
        print("缺少连接信息：需要 host / port / password。")
        print("可以放进 tools/autodl.env（已 git-ignored）：")
        print("  AUTODL_HOST=connect.westX.seetacloud.com")
        print("  AUTODL_PORT=12345")
        print("  AUTODL_USER=root")
        print("  AUTODL_PASS=...")
        return 2

    files = local_files()
    print(f"本地载荷：{len(files)} 个文件（来自 {SRC.relative_to(ROOT)}/）")
    print(f"目标    ：{user}@{host}:{port}  {args.remote_root}/")
    if args.dry_run:
        print("--- dry-run，不实际连接 ---")

    client = None if args.dry_run else connect(host, port, user, password)
    if client is None and not args.dry_run:
        return 1
    try:
        sftp = client.open_sftp() if client else None
        # 建目录（remote_path_for 对非载荷文件会返回 None，顺手过滤掉）
        dirs = {posixpath.dirname(args.remote_root + "/" + rp)
                for rp in (remote_path_for(r) for r, _ in files) if rp}
        for d in sorted(dirs):
            if args.dry_run:
                print(f"  mkdir -p {d}")
            else:
                try:
                    sftp.stat(d)
                except IOError:
                    sftp.mkdir(d)
                    print(f"  mkdir -p {d}")

        sent = skipped = protected = 0
        for rel, local in files:
            rp = remote_path_for(rel)
            if rp is None:
                continue
            remote = posixpath.join(args.remote_root, rp)
            data = local.read_bytes()
            lh = md5_bytes(data)
            if sftp is not None:
                rh = remote_md5(sftp, remote)
            else:
                rh = None
            if rh == lh and not args.force:
                skipped += 1
                continue
            if posixpath.basename(rp) in PROTECTED and rh is not None and not args.force_env:
                print(f"  跳过 {rp}（远端已存在，含真实 key；要覆盖加 --force-env）")
                protected += 1
                continue
            mark = "新传" if rh is None else "更新"
            if args.dry_run:
                print(f"  [{mark}] {rp}")
            else:
                with sftp.file(remote, "wb") as fh:
                    fh.write(data)
                print(f"  [{mark}] {rp}  ({len(data)} B)")
            sent += 1

        if sftp is not None:
            sftp.close()
        print(f"\n完成：传输 {sent} / 跳过(相同) {skipped} / 保护 {protected}")
        if protected:
            print("提示：远端 qwen_env.sh 保持原样，实例上的 key 没被动过。")
        print("\n接着在实例上执行（幂等）：")
        print(f"  ssh -p {port} {user}@{host} 'bash {args.remote_root}/scripts/bootstrap.sh'")
        return 0
    finally:
        if client:
            client.close()


if __name__ == "__main__":
    sys.exit(main())
