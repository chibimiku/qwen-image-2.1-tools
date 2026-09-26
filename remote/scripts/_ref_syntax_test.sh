export PATH=/root/miniconda3/bin:$PATH
source /root/qwen-image-2.1/qwen_env.sh
B=localhost:6006
H="Authorization: Bearer $QWEN_API_KEY"

# 造两张"辨识度极高"的参考图，便于肉眼判断模型有没有正确引用
python3 - <<'PY'
from PIL import Image, ImageDraw
# 甲：红色背景 + 白字 A
a = Image.new("RGB", (768, 1024), (200, 40, 40))
d = ImageDraw.Draw(a)
d.ellipse([280, 150, 490, 360], fill=(255, 230, 200))
d.polygon([(380, 350), (560, 620), (200, 620)], fill=(255, 255, 255))
a.save("/tmp/ref_A_red.png")
# 乙：蓝色背景 + 白字 B
b = Image.new("RGB", (768, 1024), (40, 60, 200))
d = ImageDraw.Draw(b)
d.rectangle([280, 150, 490, 360], fill=(255, 230, 200))
d.rectangle([260, 380, 510, 640], fill=(255, 255, 255))
b.save("/tmp/ref_B_blue.png")
print("参考图: A=红色竖构图 /tmp/ref_A_red.png, B=蓝色竖构图 /tmp/ref_B_blue.png")
PY

run () {
  local tag="$1"; local prompt="$2"
  local out
  out=$(curl -s -X POST $B/v1/images/generations -H "$H" \
        -F "prompt=$prompt" -F "num_inference_steps=10" -F "seed=77" \
        -F "image=@/tmp/ref_A_red.png" -F "image=@/tmp/ref_B_blue.png")
  local sz
  sz=$(echo "$out" | python3 -c "
import sys,json
try:
    d=json.load(sys.stdin); print(d.get('size','FAIL'))
except Exception: print('FAIL')")
  printf '  %-40s -> %s\n' "$tag" "$sz"
  echo "$out" | python3 -c "
import sys, json, base64, os
try:
    d = json.load(sys.stdin)
    if 'data' in d:
        raw = base64.b64decode(d['data'][0]['b64_json'])
        p = '/root/qwen-image-2.1/outputs/ref_syntax_$tag.png'
        open(p, 'wb').write(raw)
except Exception: pass"
}

echo
echo '=== 参考图引用语法对照实验（同一 seed、同样两张图，只改 prompt 写法）==='
echo
run "01_plain"     "A red creature and a blue creature standing side by side"
run "02_image12"   "image1 is a red creature, image2 is a blue creature; put them side by side"
run "03_angle"     "The creature in <image1> is red, the creature in <image2> is blue; put them side by side"
run "04_natural"   "The first reference image shows a red creature, the second shows a blue creature. Draw both of them standing side by side"
run "05_chinese"   "参考图1 是红色角色，参考图2 是蓝色角色，把两个角色并排画在一起"
run "06_swap"      "<image2> 里的角色站在左边，<image1> 里的角色站在右边"

echo
echo '=== 产物 ==='
ls -la /root/qwen-image-2.1/outputs/ref_syntax_*.png 2>/dev/null | awk '{print "  " $5, $9}'
curl -s $B/health | python3 -c "
import sys,json;g=json.load(sys.stdin)['gpu'];print(f'\n显存 空闲 {g[\"free_gb\"]}G')"
