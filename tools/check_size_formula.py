# -*- coding: utf-8 -*-
"""离线校验"从参考图推导输出尺寸"的公式，与实测值对照（不需要 GPU）。"""


def derive(w, h, budget=1024):
    """官方 calculate_dimensions 的实现（源码 L148-157）——注意宽/高是**各自独立**算完再各自取整：
        width = math.sqrt(target_area * ratio)
        height = width / ratio          # 用的是未取整的 width
        width  = round(width / 32) * 32
        height = round(height / 32) * 32
    不能拿取整后的宽度反算高度，否则高会偏。
    """
    ratio = w / h
    area = budget * budget
    raw_w = (area * ratio) ** 0.5
    raw_h = raw_w / ratio
    return round(raw_w / 32) * 32, round(raw_h / 32) * 32


MEASURED = [
    ((768, 1024), 1024, (896, 1184)),
    ((1024, 1024), 1024, (1024, 1024)),
    ((1024, 768), 1024, (1184, 896)),
    ((1696, 2528), 1024, (832, 1248)),
    ((768, 1024), 1280, (1120, 1472)),
    ((1024, 768), 1280, (1472, 1120)),
    ((768, 1024), 512, (448, 576)),
]

print(f"{'参考图':<14}{'budget':>7}{'公式推导':>14}{'实测':>14}   一致")
print("-" * 62)
bad = 0
for (w, h), budget, exp in MEASURED:
    got = derive(w, h, budget)
    ok = got == exp
    bad += 0 if ok else 1
    print(f"{w}x{h:<8}{budget:>7}{str(got):>14}{f'{exp[0]}x{exp[1]}':>14}   {'OK' if ok else 'MISMATCH'}")

print()
print("结论：" + ("公式与实测完全一致 ✓" if bad == 0 else f"{bad} 处不一致 ✗"))
print("依据：diffusers `calculate_dimensions(target_area, ratio)`")
print("      width = sqrt(target_area * ratio); height = width / ratio")
