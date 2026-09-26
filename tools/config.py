# -*- coding: utf-8 -*-
"""Central paths for the Qwen-Image-2.1 tooling.

Everything lives under D:\\workspace\\dsh-default\\qwen-image-2.1-tools; import this
module instead of hard-coding paths in the individual test scripts.
"""
from __future__ import annotations

import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # ...\qwen-image-2.1-tools
TOOLS = os.path.join(ROOT, "tools")
SERVICE = os.path.join(ROOT, "service")
DOCS = os.path.join(ROOT, "docs")
TEST_DATA = os.path.join(ROOT, "test-data")
REPORT = os.path.join(ROOT, "reports")
REMOTE = os.path.join(ROOT, "remote")

# 原始输入（用户给的 1696x2528 图，测试统一 resize 到 1088x1600）
INPUT_EDIT = os.path.join(TEST_DATA, "input_edit.jpg")

# 工作画布
W, H = 1088, 1600

# 归一化区域（x0, y0, x1, y1），乘上 W/H 得到像素框
REGIONS = {
    "face": (0.22, 0.03, 0.78, 0.30),      # 头像区：表情/发型/头部朝向
    "torso": (0.20, 0.28, 0.80, 0.62),     # 上半身：服装颜色/款式
    "border": (0.00, 0.00, 1.00, 1.00),    # 全图（背景检查用边角采样）
    "figure": (0.10, 0.30, 0.90, 0.97),    # 人物主体：姿势
}


def px(box, w=W, h=H):
    x0, y0, x1, y1 = box
    return int(x0 * w), int(y0 * h), int(x1 * w), int(y1 * h)


def ensure(*dirs):
    for d in dirs:
        os.makedirs(d, exist_ok=True)
    return dirs
