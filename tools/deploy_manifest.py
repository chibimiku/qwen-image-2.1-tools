# -*- coding: utf-8 -*-
"""部署映射清单 —— 「仓库里的哪个文件 → 实例上的哪个路径」。

`tools/deploy_service.py`（负责传）与 `tools/check_deploy.py`（负责对账）都从这里读，
免得两边各写一套映射、然后悄悄对不上。

实例布局（实际观测到的，不是设计出来的）：

    /root/qwen-image-2.1/
      server.py?          否 —— server.py 在 service/ 下
      service/            server.py · client.py · face_fix.py · ui/
      scripts/            *.sh · bench.py · inspect_ckpt.py · qwen-image.service
      ui/?                否 —— UI 在 service/ui/ 下
      qwen_env.sh         直接在根，serve.sh 里 source 的就是这份
      logs/ outputs/ inputs/ 由脚本自建

所以三条规则：
  1. `service/<x>.py`、`service/ui/<x>`      → `<root>/service/<x>`
  2. `service/scripts/<x>`                    → `<root>/scripts/<x>`
  3. `service/scripts/qwen_env.sh`            → `<root>/qwen_env.sh`   （唯一提级）
"""
from __future__ import annotations

#: 仓库内目录 → 实例内目录
DIR_MAP = [
    ("service/scripts", "scripts"),
    ("service/ui", "service/ui"),
    ("service", "service"),
]

#: 单文件覆盖（仓库相对路径 → 实例相对路径）
FILE_OVERRIDE = {
    "service/scripts/qwen_env.sh": "qwen_env.sh",
}

#: 这些文件远端可能存着真值（如 key），默认不覆盖
PROTECTED_BASENAMES = {"qwen_env.sh"}

REMOTE_ROOT = "/root/qwen-image-2.1"


def repo_to_remote(rel_in_repo: str) -> str | None:
    """仓库相对路径 → 实例相对路径。不属于部署载荷则返回 None。"""
    rel = rel_in_repo.replace("\\", "/")
    if rel in FILE_OVERRIDE:
        return FILE_OVERRIDE[rel]
    for repo_dir, remote_dir in DIR_MAP:
        if rel == repo_dir:
            continue
        if rel.startswith(repo_dir + "/"):
            tail = rel[len(repo_dir) + 1:]
            return f"{remote_dir}/{tail}"
    return None


def remote_to_repo(rel_on_remote: str) -> str | None:
    """实例相对路径 → 仓库相对路径。用于 check_deploy 反查。"""
    rel = rel_on_remote.lstrip("/")
    for repo_path, remote_path in FILE_OVERRIDE.items():
        if rel == remote_path:
            return repo_path
    for repo_dir, remote_dir in DIR_MAP:
        if rel.startswith(remote_dir + "/"):
            tail = rel[len(remote_dir) + 1:]
            return f"{repo_dir}/{tail}"
    return None
