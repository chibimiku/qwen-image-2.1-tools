# -*- coding: utf-8 -*-
"""测试脚本共用的 key 读取（避免把 key 硬编码在各个脚本里）。

优先级：环境变量 QWEN_API_KEY > tools/.qwenkey 文件 > 空串
"""
import os

_HERE = os.path.dirname(os.path.abspath(__file__))
KEY_FILE = os.path.join(_HERE, ".qwenkey")


def api_key() -> str:
    v = os.environ.get("QWEN_API_KEY")
    if v:
        return v.strip()
    try:
        for line in open(KEY_FILE, encoding="utf-8"):
            line = line.strip()
            if line and not line.startswith("#"):
                return line
    except Exception:                                                 # noqa: BLE001
        pass
    return ""


def auth_header() -> dict:
    k = api_key()
    return {"Authorization": f"Bearer {k}"} if k else {}
