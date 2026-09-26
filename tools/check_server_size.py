# -*- coding: utf-8 -*-
"""本地验证：server.py 语法 + 尺寸推导/补全算术（不加载模型、不依赖 torch）。

覆盖：
  1) _derive_size 与官方公式一致（复用 tools/check_size_formula.py 的期望值）
  2) 新增的"只给一边"补全逻辑，复刻 server.py 里的算式逐条核对
"""
import ast
import sys
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT / "service" / "server.py"

# ---------- 1. 语法 ----------
src = SRC.read_text(encoding="utf-8")
try:
    tree = ast.parse(src)
except SyntaxError as e:
    print("SYNTAX FAIL:", e)
    sys.exit(1)
print("syntax OK  (%d lines, %d bytes)" % (src.count("\n") + 1, len(src.encode())))

# ---------- 2. 从源码里抠出 _derive_size 与 _resolve_size，排除 torch 依赖 ----------
want = {"_derive_size", "_resolve_size"}
#   父节点是 Expr（被装饰器包着），所以用 body 里的 FunctionDef 抓
ns = {"List": list, "Tuple": tuple, "Dict": dict, "Any": object, "Optional": object}
for node in ast.walk(tree):
    if isinstance(node, ast.FunctionDef) and node.name in want:
        # 装饰器可能有，直接剥掉再编译
        node.decorator_list = []
        mod = ast.Module(body=[node], type_ignores=[])
        ast.fix_missing_locations(mod)
        exec(compile(mod, str(SRC), "exec"), ns)
print("extracted:", sorted(k for k in ns if k in want))

derive = ns["_derive_size"]


class _FakeImg:
    def __init__(self, w, h):
        self.size = (w, h)


# ---------- 3. _derive_size 对照 ----------
CASES = [
    # (参考图尺寸, budget, 期望输出)  —— 期望值来自 tools/check_size_formula.py（已与官方公式对过）
    ((768, 1024), 1024, (896, 1184)),
    ((1024, 1024), 1024, (1024, 1024)),
    ((1024, 768), 1024, (1184, 896)),
    ((1696, 2528), 1024, (832, 1248)),
    ((768, 1024), 1280, (1120, 1472)),
    ((1024, 768), 1280, (1472, 1120)),
    ((768, 1024), 512, (448, 576)),
    # 下面两条不是实测值，是按官方公式手算的边界（1920x1080 这种非 3:2 比例）
    ((1920, 1080), 1024, (1376, 768)),
    ((1000, 1000), 1024, (1024, 1024)),
]
bad = 0
for size, budget, exp in CASES:
    got = derive([_FakeImg(*size)], budget)
    ok = got == exp
    bad += 0 if ok else 1
    print("  derive %s budget=%d -> %s  %s" % (size, budget, got, "OK" if ok else "MISMATCH exp=%s" % (exp,)))

# ---------- 4. 补全逻辑（复刻 server.py 新增块） ----------
def fill_one_side(width, height, ref_ratio=1.0):
    """复刻 server.py 的补全块。ref_ratio: 有参考图时 image[-1] 的 w/h，否则 1.0。"""
    if bool(width) != bool(height):
        ratio = ref_ratio
        if width:
            raw_w, raw_h = float(width), float(width) / ratio
        else:
            raw_w = float(height) * ratio
            raw_h = float(height)
        width = round(raw_w / 32) * 32
        height = round(raw_h / 32) * 32
    return width, height


FILL = [
    # (w, h, ref_ratio, 期望) —— 期望按"未取整反算 + 各自 round32"手算
    (None, None, 1.0, (None, None)),          # 两边都缺 → 这段不管
    (1024, 1600, 1.0, (1024, 1600)),          # 两边都有 → 原样不动
    (None, 1600, 1.0, (1600, 1600)),          # 只给高 → 方图
    (1600, None, 1.0, (1600, 1600)),
    (768, None, 0.75, (768, 1024)),           # 只给宽，参考图 768x1024
    (None, 1024, 0.75, (768, 1024)),
    (1200, None, 0.75, (1216, 1600)),         # round(1200/32)*32=1216；高 1200/0.75=1600
    (None, 1600, 0.75, (1216, 1600)),
]
print("--- fill-one-side ---")
for w, h, rr, exp in FILL:
    got = fill_one_side(w, h, rr)
    ok = got[0] is None or got == exp
    bad += 0 if ok else 1
    print("  w=%-5s h=%-5s ratio=%.2f -> %-16s %s" % (w, h, rr, got, "OK" if ok else "MISMATCH exp=%s" % (exp,)))

print("\n%s" % ("ALL GOOD" if bad == 0 else "%d MISMATCH" % bad))
sys.exit(1 if bad else 0)
