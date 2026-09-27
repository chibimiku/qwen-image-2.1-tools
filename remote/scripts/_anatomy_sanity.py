#!/usr/bin/env python3
"""审图模型能不能真的判图 —— 用**故意做坏**的图验证它不是永远 PASS。

背景：`inspect_image` 加载失败时会 fail-open 返回 passed=True、confidence=0。
于是"模型加载不起来"和"图真的没问题"在汇总表里长得一模一样（都是 0% FAIL）。
这个脚本必须能分辨这两种情况。

做法：不设任何环境变量调用（复刻最容易被误用的姿势），
先看 status() 里的 loaded / load_error，再拿一张人为画出三条腿的图去问它。
如果一张明显多腿的图也 PASS，说明判据不可信，报告里必须写明"自动标签无区分力"。
"""
import os
import sys

sys.path.insert(0, "/root/qwen-image-2.1/service")

# 故意不设 QWEN_ANATOMY_MODEL：靠 qwen_env.sh / 模块默认值兜底。
# 这正是最容易踩的坑 —— 如果兜底不对，下面 status() 会直接告诉我们。
from PIL import Image, ImageDraw                            # noqa: E402
import anatomy_check                                        # noqa: E402

print("MODEL_ID     =", anatomy_check.MODEL_ID)
print("HF_HUB_OFFLINE =", os.environ.get("HF_HUB_OFFLINE"))
print("TRANSFORMERS_OFFLINE =", os.environ.get("TRANSFORMERS_OFFLINE"))

st = anatomy_check.status()
print("status loaded =", st.get("loaded"), " load_error =", st.get("load_error"))
if not st.get("loaded"):
    # 主动触发一次加载，把这行日志的加载结果打出来
    pass

# ---------- 造一张"必然异常"的图：一个躯干 + 三条腿 ----------
def _body(d, xs, skin=(228, 190, 165), cloth=(74, 96, 138), pants=(44, 50, 66)):
    """画一个尽量"不像卡通"的站姿人形：分层色块 + 描边 + 渐变阴影。

    模型指令里写着 "PASS if ... the image is stylized"，所以火柴人必然 PASS ——
    那测不出模型有没有用。这里要更接近真实渲染的质感，才有区分力。
    """
    # 头 + 脖子
    d.ellipse([330, 96, 438, 204], fill=skin, outline=(96, 72, 58), width=3)
    d.rectangle([368, 200, 400, 226], fill=skin, outline=(96, 72, 58), width=2)
    # 躯干：上宽下窄，肩胛带阴影
    d.polygon([(314, 226), (454, 226), (438, 452), (330, 452)], fill=cloth,
              outline=(36, 46, 66))
    d.polygon([(330, 452), (438, 452), (430, 470), (338, 470)], fill=pants,
              outline=(26, 30, 40))
    # 每条腿：大腿 + 小腿，膝盖处换色，末端加鞋
    for i, x in enumerate(xs):
        d.polygon([(x, 466), (x + 62, 466), (x + 54, 592), (x + 8, 592)],
                  fill=pants, outline=(26, 30, 40))
        d.polygon([(x + 6, 590), (x + 56, 590), (x + 50, 700), (x + 12, 700)],
                  fill=(36, 42, 58), outline=(20, 24, 32))
        d.ellipse([x, 692, x + 70, 722], fill=(22, 24, 30), outline=(12, 14, 18), width=2)


def make_bad(path):
    im = Image.new("RGB", (768, 768), (206, 210, 216))
    d = ImageDraw.Draw(im)
    d.rectangle([0, 640, 768, 768], fill=(176, 172, 168))          # 地面，给点景深
    _body(d, (206, 322, 440))                                       # 三条腿
    im.save(path)
    return path


def make_ok(path):
    im = Image.new("RGB", (768, 768), (206, 210, 216))
    d = ImageDraw.Draw(im)
    d.rectangle([0, 640, 768, 768], fill=(176, 172, 168))
    _body(d, (292, 386))                                            # 两条腿
    im.save(path)
    return path


bad = make_bad("/tmp/_anat_bad.png")
ok = make_ok("/tmp/_anat_ok.png")

for name, p in (("三条腿的图", bad), ("两条腿的图", ok)):
    v = anatomy_check.inspect_image(Image.open(p).convert("RGB"), "")
    print("\n%s: passed=%s label=%s conf=%s" % (name, v.get("passed"), v.get("label"), v.get("confidence")))
    print("  reason:", (v.get("reason") or "")[:200])

print("\n判读方式：")
print("  · 若两行 label 都是 'unavailable' → 模型没加载，自动标签**无区分力**，不能当判据")
print("  · 若两条腿的 PASS、三条腿的 FAIL → 模型在工作，自动标签可作辅助判据")
print("  · 若两条腿的也 FAIL → 判据过严，同样不可信")
