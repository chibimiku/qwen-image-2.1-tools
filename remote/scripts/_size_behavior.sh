export PATH=/root/miniconda3/bin:$PATH
source /root/qwen-image-2.1/qwen_env.sh
B=localhost:6006
K="$QWEN_API_KEY"
H="Authorization: Bearer $K"

python3 - <<'PY'
from PIL import Image, ImageDraw
for wh, name in [((1024,1024),"/tmp/ref_square.png"), ((768,1024),"/tmp/ref_34.png"),
                 ((1024,768),"/tmp/ref_43.png")]:
    im = Image.new("RGB", wh, (30,60,110))
    d = ImageDraw.Draw(im)
    d.rectangle([wh[0]//4, wh[1]//4, wh[0]*3//4, wh[1]*3//4], fill=(240,200,60))
    im.save(name)
    print("ref:", name, wh)
PY

echo
echo '=== 编辑接口：输出尺寸到底由什么决定 ==='
echo "参考图        请求参数                              实际输出"
echo "---------------------------------------------------------------"
for REF in /tmp/ref_square.png /tmp/ref_34.png /tmp/ref_43.png; do
  for ARGS in "" "width=2048&height=2048" "output_resolution=1024" "output_resolution=1280" "output_resolution=512"; do
    OUT=$(curl -s -X POST $B/v1/images/edits -H "$H" \
          -F "prompt=change the background to a plain green field" \
          -F "num_inference_steps=6" -F "seed=3" -F "image=@$REF" \
          $(for kv in $ARGS; do echo -n " -F $kv"; done) 2>/dev/null)
    SZ=$(echo "$OUT" | python3 -c "
import sys,json
try:
    d=json.load(sys.stdin); print(d['size'])
except Exception as e:
    print('ERR', str(e)[:40])
")
    printf '%-14s %-36s %s\n' "$(basename $REF)" "${ARGS:-（不传）}" "$SZ"
  done
done
echo
echo '=== 参考图上传尺寸是否影响输出比例（同一档位、不同比例参考图）==='
for REF in /tmp/ref_square.png /tmp/ref_34.png /tmp/ref_43.png; do
  OUT=$(curl -s -X POST $B/v1/images/edits -H "$H" \
        -F "prompt=make it a watercolor" -F "num_inference_steps=6" -F "seed=9" \
        -F "image=@$REF" -F "output_resolution=1024")
  printf '  %-14s -> %s\n' "$(basename $REF)" "$(echo "$OUT" | python3 -c "
import sys,json;print(json.load(sys.stdin)['size'])")"
done

echo
echo '=== diffusers 管线里 output_resolution / width / height 的关系（读源码）==='
python3 - <<'PY'
import inspect, re
from diffusers import QwenImage21Pipeline
src = inspect.getsource(QwenImage21Pipeline.__call__)
for i, line in enumerate(src.splitlines()):
    if re.search(r'output_resolution|aspect|width|height', line) and not line.strip().startswith('#'):
        s = line.strip()
        if len(s) > 4:
            print(f"  {i:4d}| {s[:150]}")
PY
