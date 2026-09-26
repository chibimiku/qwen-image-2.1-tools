# -*- coding: utf-8 -*-
"""分模式校验显存估算公式与实测边界是否一致（不需要 GPU）。"""
GIB_TOTAL, GIB_WEIGHTS = 47.4, 30.24
LAT2K = 8.0
Q_EDIT, Q_T2I = 3.65, 0.5


def latent(w, h, mode):
    mp = w * h / 1e6
    linear = LAT2K * (w * h) / (2048 * 2048)
    quad = (Q_EDIT if mode == "edit" else Q_T2I) * mp * mp
    return max(linear, quad)


def verdict(w, h, mode):
    need = latent(w, h, mode)
    return need, ("拦住" if need > GIB_TOTAL - GIB_WEIGHTS else "放行")


print("编辑 edit（权重常驻 30.2G，可用 17.2G）")
print(f"{'尺寸':<14}{'MP':>6}{'需临时量':>10}  实测           预检")
for w, h, real in [(896, 1184, "OK"), (1024, 1344, "OK"), (1088, 1440, "OK"),
                   (1152, 1536, "OK"), (1184, 1600, "OK"), (1280, 1696, "OOM"),
                   (1696, 2528, "OOM")]:
    need, v = verdict(w, h, "edit")
    mark = "✓" if (v == "拦住") == (real == "OOM") else "✗ 不一致"
    print(f"{w}x{h:<9}{w*h/1e6:>6.2f}{need:>9.1f}G  {real:<13}{v}  {mark}")

print()
print("文生图 t2i（峰值 32.5G 实测能跑，绝不能被拦）")
print(f"{'尺寸':<14}{'MP':>6}{'需临时量':>10}  实测           预检")
for w, h, real in [(1024, 1024, "OK 峰值 36.8G"), (2048, 2048, "OK 峰值 32.5G")]:
    need, v = verdict(w, h, "t2i")
    mark = "✓" if v == "放行" else "✗ 误拦"
    print(f"{w}x{h:<9}{w*h/1e6:>6.2f}{need:>9.1f}G  {real:<16}{v}  {mark}")

print()
print("如果 t2i 也用 edit 的系数会怎样：")
need, v = verdict(2048, 2048, "edit")
print(f"  2048x2048 -> 需 {need:.1f}G -> {v}  ← 这就是刚才误拦的原因")
