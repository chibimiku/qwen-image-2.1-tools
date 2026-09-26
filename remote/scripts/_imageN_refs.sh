#!/usr/bin/env bash
# 受控实验：确认 <image1>/<image2> 引用语法是否真的改变语义
# 素材：红圆 A / 蓝三角 B / 合成图 C(左红圆+右蓝三角)
# 若 <imageN> 生效且编号=上传顺序 → P2 出(左红圆+右蓝三角)；P3 编号对调应指向错误对象。
# KEY 由本地脚本注入到环境变量。
set -u
PY=/root/miniconda3/bin/python
API=http://127.0.0.1:6006
KEY="${KEY:?KEY 未注入}"
OUT=/root/autodl-tmp/imageN_check
mkdir -p "$OUT"
echo "key_len=${#KEY}"

$PY - <<'PY'
from PIL import Image, ImageDraw
im = Image.new("RGB", (768,1024), (245,245,245)); d = ImageDraw.Draw(im)
d.ellipse([184, 332, 584, 732], fill=(220,40,40)); im.save("/tmp/ref_A_red.png")
im = Image.new("RGB", (768,1024), (245,245,245)); d = ImageDraw.Draw(im)
d.polygon([(384,300),(600,760),(168,760)], fill=(40,60,220)); im.save("/tmp/ref_B_blue.png")
c = Image.new("RGB", (768,1024), (245,245,245)); d = ImageDraw.Draw(c)
d.ellipse([60,332,400,672], fill=(220,40,40))
d.polygon([(600,330),(740,700),(460,700)], fill=(40,60,220))
c.save("/tmp/ref_C_both.png")
print("refs built")
PY

run() {
  local name="$1"; shift
  local imgs="$1"; shift
  local prompt="$1"
  local args=()
  for f in $imgs; do args+=(-F "image=@$f"); done
  echo "===== $name ====="
  curl -s -m 900 -H "Authorization: Bearer $KEY" \
    -F num_inference_steps=12 -F seed=1234 -F width=768 -F height=1024 -F output_format=png \
    "${args[@]}" --form-string "prompt=$prompt" \
    "$API/v1/images/generations" -o "$OUT/$name.json"
  $PY - "$OUT/$name.json" "$OUT/$name.png" <<'PY'
import json,base64,sys
try:
    d=json.load(open(sys.argv[1]))
except Exception as ex:
    print("  JSONERR", ex); raise SystemExit
if 'data' in d:
    open(sys.argv[2],'wb').write(base64.b64decode(d['data'][0]['b64_json']))
    print("  OK", d['data'][0]['width'], "x", d['data'][0]['height'])
else:
    print("  ERR", str(d)[:200])
PY
}

R=/tmp/ref_A_red.png
B=/tmp/ref_B_blue.png
C=/tmp/ref_C_both.png

run P1_none     "$R $B" "左半边是一个红色圆，右半边是一个蓝色三角形。"
run P2_imageN   "$R $B" "<image1>是红色圆，<image2>是蓝色三角形。把它们并排放在同一张图里，左边红色圆，右边蓝色三角形。"
run P3_shuffle  "$R $B" "<image2>是红色圆，<image1>是蓝色三角形。把它们并排放在同一张图里，左边红色圆，右边蓝色三角形。"
run P4_ordinal  "$R $B" "第一张参考图是红色圆，第二张参考图是蓝色三角形。把它们并排放在同一张图里，左边红色圆，右边蓝色三角形。"
run P5_singleC  "$C"    "把这张图里同时出现的红色圆和蓝色三角形分开，并排放在同一张图里，左边红色圆，右边蓝色三角形。"

echo "===== done ====="
ls -l "$OUT"
