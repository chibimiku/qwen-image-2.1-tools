# -*- coding: utf-8 -*-
"""部署对账：比"实例上实际跑的"与"仓库里提交的"，输出一致/不一致/缺失。

用法（仓库根目录）：
    python tools/check_deploy.py
需要 tools/autodl.env（git-ignored）或环境变量 AUTODL_*。
"""
from __future__ import annotations

import hashlib
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import autodl_run          # noqa: E402  复用 SSH 连接
import deploy_manifest as M  # noqa: E402  复用路径映射

ROOT = pathlib.Path(__file__).resolve().parent.parent

#: 要核对的实例文件（相对 REMOTE_ROOT）。全量列出，一眼能看出漏了什么。
REMOTE_FILES = [
    "service/server.py",
    "service/client.py",
    "service/face_fix.py",
    "service/ui/index.html",
    "service/ui/Qwen-Image-2.1-console.ipynb",
    "qwen_env.sh",
    "scripts/serve.sh",
    "scripts/bootstrap.sh",
    "scripts/download_model.sh",
    "scripts/watch_download.sh",
    "scripts/show_url.sh",
    "scripts/export_source.sh",
    "scripts/bench.py",
    "scripts/inspect_ckpt.py",
    "scripts/qwen-image.service",
]


def md5_local(p: pathlib.Path) -> str | None:
    if not p.is_file():
        return None
    return hashlib.md5(p.read_bytes()).hexdigest()


#: 这些变量在两边的值本来就该不同（实例上是真值，仓库里是占位符）。
#: 对账时按"语义等价"处理：去掉这些行再比，一致就算 OK。
SECRET_KEYS = ("QWEN_API_KEY", "QWEN_API_KEYS")


def _strip_secret_lines(text: str) -> list[str]:
    out = []
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("#") or "=" not in s:
            continue
        if any(s.lstrip("export ").startswith(k + "=") for k in SECRET_KEYS):
            continue
        out.append(s)
    return out


def env_semantically_equal(local: pathlib.Path, remote_text: str) -> bool:
    return _strip_secret_lines(local.read_text(encoding="utf-8", errors="replace")) \
        == _strip_secret_lines(remote_text)


def main() -> int:
    autodl_run.load_env_file()
    paths = [f"{M.REMOTE_ROOT}/{r}" for r in REMOTE_FILES]
    c = autodl_run.connect()
    try:
        _rc, out, _err = autodl_run.run(c, "md5sum " + " ".join(paths) + " 2>&1")
        _rc2, env_text, _e2 = autodl_run.run(c, f"cat {M.REMOTE_ROOT}/qwen_env.sh 2>&1")
    finally:
        c.close()

    remote: dict[str, str] = {}
    for line in out.splitlines():
        parts = line.split(None, 1)
        if len(parts) == 2 and len(parts[0]) == 32:
            remote[parts[1].strip()] = parts[0]

    print(f"{'实例路径 (相对 /root/qwen-image-2.1/)':<46} {'状态':<8} 仓库对应")
    print("-" * 104)
    same, diff, miss_local, absent = [], [], [], []
    for rel in REMOTE_FILES:
        local_rel = M.remote_to_repo(rel)
        local = (ROOT / local_rel) if local_rel else None
        rh = remote.get(f"{M.REMOTE_ROOT}/{rel}")
        lh = md5_local(local) if local else None
        if rh is None:
            state, bucket = "远端无", absent
        elif lh is None:
            state, bucket = "仓库缺", miss_local
        elif rh == lh:
            state, bucket = "一致", same
        elif rel == "qwen_env.sh" and local and env_semantically_equal(local, env_text):
            # 只有 key 值不同 —— 这是设计使然，不是漂移
            state, bucket = "一致*", same
        else:
            state, bucket = "不一致", diff
        bucket.append(rel)
        print(f"{rel:<46} {state:<8} {local_rel or '—'}")

    print()
    print(f"一致 {len(same)} / 不一致 {len(diff)} / 仓库缺 {len(miss_local)} / 远端无 {len(absent)}")
    print("* = 除 QWEN_API_KEY/QWEN_API_KEYS 的值外完全一致（实例存真值，仓库存占位符）")
    if diff:
        print("\n不一致（实例上跑的与仓库提交的不是同一版）：")
        for m in diff:
            print(f"  - {m}")
    if miss_local:
        print("\n仓库缺（实例有但仓库没有 → 换机补不回来）：")
        for m in miss_local:
            print(f"  - {m}")
    if absent:
        print("\n远端无（仓库有但没部署上去）：")
        for m in absent:
            print(f"  - {m}   → python tools/deploy_service.py")
    return 1 if (diff or miss_local) else 0


if __name__ == "__main__":
    raise SystemExit(main())
