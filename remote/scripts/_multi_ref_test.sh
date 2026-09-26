export PATH=/root/miniconda3/bin:$PATH
source /root/qwen-image-2.1/qwen_env.sh
B=localhost:6006
H="Authorization: Bearer $QWEN_API_KEY"
curl -s -X POST $B/v1/admin/empty_cache -H "$H" >/dev/null

python3 - <<'PY'
from PIL import Image, ImageDraw
# 两张不同尺寸的"人"参考图：A 竖构图 768x1024，B 方构图 1024x1024
a = Image.new("RGB", (768, 1024), (40, 80, 140))
ImageDraw.Draw(a).ellipse([200, 120, 560, 480], fill=(240, 200, 170))   # 头
ImageDraw.Draw(a).rectangle([260, 480, 500, 900], fill=(200, 60, 60))   # 身体
a.save("/tmp/person_a.png")
b = Image.new("RGB", (1024, 1024), (60, 120, 80))
ImageDraw.Draw(b).ellipse([330, 180, 690, 540], fill=(230, 190, 160))
ImageDraw.Draw(b).rectangle([390, 540, 630, 940], fill=(60, 60, 200))
b.save("/tmp/person_b.png")
print("参考图 A:", a.size, " B:", b.size)
PY

echo
echo '=== 多参考图：输出尺寸由谁决定？==='
echo "参考图组合                     参数            输出        耗时"
echo '-------------------------------------------------------------------'
for COMBO in "-F image=@/tmp/person_a.png -F image=@/tmp/person_b.png|A+B" \
             "-F image=@/tmp/person_b.png -F image=@/tmp/person_a.png|B+A" \
             "-F image=@/tmp/person_a.png|A单张" \
             "-F image=@/tmp/person_b.png|B单张"; do
  ARGS="${COMBO%%|*}"; NAME="${COMBO#*|}"
  OUT=$(curl -s -X POST $B/v1/images/edits -H "$H" \
        -F "prompt=These two people are hugging each other warmly, waist up, simple background" \
        -F "num_inference_steps=8" -F "seed=21" $ARGS)
  echo "$OUT" | python3 -c "
import sys,json
d=json.load(sys.stdin)
it=d['data'][0] if 'size' in d else None
print(f\"  {'$NAME':<8} {'（默认）':<14} {d['size'] if it else 'FAIL':<12} {it['elapsed_s'] if it else ''}s\")"
  curl -s -X POST $B/v1/admin/empty_cache -H "$H" >/dev/null
done

echo
echo '=== 两张参考图 + 显式尺寸（2:3 竖构图，能放下两个拥抱的人）==='
curl -s -X POST $B/v1/images/edits -H "$H" \
  -F "prompt=These two people are hugging each other warmly, full body, veranda by the sea" \
  -F "num_inference_steps=10" -F "seed=21" \
  -F "image=@/tmp/person_a.png" -F "image=@/tmp/person_b.png" \
  -F "width=1184" -F "height=1600" \
| python3 -c "
import sys,json
d=json.load(sys.stdin)
print('  ' + ('OK ' + d['size'] + '  耗时 ' + str(d['data'][0]['elapsed_s']) + 's' if 'size' in d else 'FAIL: ' + str(d.get('detail',''))[:90]))"

echo
echo '=== 同样两张图走文生图接口会怎样（预期：参考图被忽略）==='
curl -s -X POST $B/v1/images/generations -H 'Content-Type: application/json' -H "$H" \
  -d '{"prompt":"These two people are hugging each other warmly","width":1024,"height":1024,"num_inference_steps":8,"seed":21}' \
| python3 -c "
import sys,json
d=json.load(sys.stdin)
print('  ' + ('OK ' + d['size'] + '（但没吃参考图，只是纯文本生成）' if 'size' in d else 'FAIL'))"

curl -s $B/health | python3 -c "
import sys,json;g=json.load(sys.stdin)['gpu'];print(f'\n显存 空闲 {g[\"free_gb\"]}G / 已用 {g[\"reserved_gb\"]}G')"
