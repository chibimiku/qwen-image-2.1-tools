export PATH=/root/miniconda3/bin:$PATH
source /root/qwen-image-2.1/qwen_env.sh
B=localhost:6006
H="Authorization: Bearer $QWEN_API_KEY"

echo '=== 分叉点验证 ==='
echo
echo '1) 不传尺寸时，有参考图 / 没参考图的默认输出尺寸是否不同？'
printf '   文生图（不传尺寸）  -> '
curl -s -X POST $B/v1/images/generations -H 'Content-Type: application/json' -H "$H" \
  -d '{"prompt":"a small boat","num_inference_steps":6,"seed":1}' \
| python3 -c "
import sys,json;d=json.load(sys.stdin)
print(d['size'] if 'size' in d else 'FAIL '+str(d.get('detail'))[:60])"
printf '   编辑 768×1024 参考图 -> '
curl -s -X POST $B/v1/images/edits -H "$H" \
  -F "prompt=a small boat" -F "num_inference_steps=6" -F "seed=1" \
  -F "image=@/tmp/person_a.png" \
| python3 -c "
import sys,json;d=json.load(sys.stdin)
print(d['size'] if 'size' in d else 'FAIL '+str(d.get('detail'))[:60])"

echo
echo '2) 输出尺寸上限是否不同？（同样的显式尺寸，两条路各试一次）'
for WH in "2048 2048" "1184 1600"; do
  set -- $WH
  printf '   %-12s 文生图 -> ' "$1x$2"
  curl -s -X POST $B/v1/images/generations -H 'Content-Type: application/json' -H "$H" \
    -d "{\"prompt\":\"a small boat\",\"width\":$1,\"height\":$2,\"num_inference_steps\":6,\"seed\":1}" \
  | python3 -c "
import sys,json;d=json.load(sys.stdin)
print(d['size'] if 'size' in d else 'FAIL '+str(d.get('detail',''))[:50])"
  printf '   %-12s 编辑   -> ' "$1x$2"
  curl -s -X POST $B/v1/images/edits -H "$H" \
    -F "prompt=a small boat" -F "num_inference_steps=6" -F "seed=1" \
    -F "image=@/tmp/person_a.png" -F "width=$1" -F "height=$2" \
  | python3 -c "
import sys,json;d=json.load(sys.stdin)
print(d['size'] if 'size' in d else 'FAIL '+str(d.get('detail',''))[:50])"
  curl -s -X POST $B/v1/admin/empty_cache -H "$H" >/dev/null
done

echo
echo '3) 文生图接口能不能吃 image 参数？（能不能合并成一个入口）'
printf '   POST /v1/images/generations 带 image[]：'
curl -s -X POST $B/v1/images/generations -H "$H" \
  -F "prompt=a small boat" -F "image=@/tmp/person_a.png" -o /dev/null -w '%{http_code}\n' 2>/dev/null || echo '（表单不支持）'
printf '   带 image_b64 字段：'
curl -s -X POST $B/v1/images/generations -H 'Content-Type: application/json' -H "$H" \
  -d '{"prompt":"x","image_b64":"AAAA"}' | head -c 120
echo
