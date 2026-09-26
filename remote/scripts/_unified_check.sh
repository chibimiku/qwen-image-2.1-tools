export PATH=/root/miniconda3/bin:$PATH
source /root/qwen-image-2.1/qwen_env.sh
B=localhost:6006
H="Authorization: Bearer $QWEN_API_KEY"

pkill -f 'service/server.py' 2>/dev/null; sleep 4
cd /root/qwen-image-2.1
bash scripts/serve.sh start
for i in $(seq 1 60); do
  H2=$(curl -s -m 5 $B/health 2>/dev/null)
  case "$H2" in *'"loaded":true'*) echo "READY"; break;; esac
  sleep 3
done
curl -s -X POST $B/v1/admin/empty_cache -H "$H" >/dev/null

echo
echo '=== 单入口矩阵：同一个端点，image 可选 ==='
printf '%-46s %-12s %s\n' "请求" "输出" "说明"
echo '----------------------------------------------------------------------------'

# 1) 纯 JSON 无图
R=$(curl -s -X POST $B/v1/images/generations -H 'Content-Type: application/json' -H "$H" \
    -d '{"prompt":"a small boat on a lake","num_inference_steps":6,"seed":1}')
printf '%-46s %-12s %s\n' "JSON，无图，不传尺寸" \
  "$(echo "$R" | python3 -c "import sys,json;d=json.load(sys.stdin);print(d.get('size','FAIL'))")" \
  "应 = 官方默认 2048²"

# 2) JSON 带 image_b64
B64=$(python3 -c "import base64;print(base64.b64encode(open('/tmp/person_a.png','rb').read()).decode())")
R=$(curl -s -X POST $B/v1/images/generations -H 'Content-Type: application/json' -H "$H" \
    -d "{\"prompt\":\"a small boat on a lake\",\"num_inference_steps\":6,\"seed\":1,\"image_b64\":[\"$B64\"]}")
printf '%-46s %-12s %s\n' "JSON，带 1 张 image_b64" \
  "$(echo "$R" | python3 -c "import sys,json;d=json.load(sys.stdin);print(d.get('size','FAIL'))")" \
  "应跟随参考图比例"

# 3) multipart 无图
R=$(curl -s -X POST $B/v1/images/generations -H "$H" \
    -F "prompt=a small boat on a lake" -F "num_inference_steps=6" -F "seed=1")
printf '%-46s %-12s %s\n' "multipart，无图" \
  "$(echo "$R" | python3 -c "import sys,json;d=json.load(sys.stdin);print(d.get('size','FAIL'))")" \
  "与 JSON 等价"

# 4) multipart 1 张图
R=$(curl -s -X POST $B/v1/images/generations -H "$H" \
    -F "prompt=a small boat on a lake" -F "num_inference_steps=6" -F "seed=1" \
    -F "image=@/tmp/person_a.png")
printf '%-46s %-12s %s\n' "multipart，1 张图" \
  "$(echo "$R" | python3 -c "import sys,json;d=json.load(sys.stdin);print(d.get('size','FAIL'))")" \
  "= 原来的「编辑」用法"

# 5) multipart 2 张图 + 显式尺寸
R=$(curl -s -X POST $B/v1/images/generations -H "$H" \
    -F "prompt=These two people are hugging each other warmly" -F "num_inference_steps=10" -F "seed=21" \
    -F "image=@/tmp/person_a.png" -F "image=@/tmp/person_b.png" \
    -F "width=1184" -F "height=1600")
printf '%-46s %-12s %s\n' "multipart，2 张图 + width/height" \
  "$(echo "$R" | python3 -c "import sys,json;d=json.load(sys.stdin);print(d.get('size','FAIL'))")" \
  "多主体合成 + 显式尺寸"
curl -s -X POST $B/v1/admin/empty_cache -H "$H" >/dev/null

# 6) 档位
R=$(curl -s -X POST $B/v1/images/generations -H "$H" \
    -F "prompt=a mountain lake" -F "num_inference_steps=6" -F "seed=1" -F "aspect_ratio=16:9")
printf '%-46s %-12s %s\n' "multipart，无图 + aspect_ratio=16:9" \
  "$(echo "$R" | python3 -c "import sys,json;d=json.load(sys.stdin);print(d.get('size','FAIL'))")" \
  "官方档位 2752×1536"

echo
echo '=== 旧端点仍然等价（/v1/images/edits 转发到同一实现）==='
R=$(curl -s -X POST $B/v1/images/edits -H "$H" \
    -F "prompt=a small boat on a lake" -F "num_inference_steps=6" -F "seed=1" \
    -F "image=@/tmp/person_a.png")
printf '  /v1/images/edits 1 张图 -> %s\n' \
  "$(echo "$R" | python3 -c "import sys,json;d=json.load(sys.stdin);print(d.get('size','FAIL'))")"

curl -s $B/health | python3 -c "
import sys,json;g=json.load(sys.stdin)['gpu'];print(f'\n显存 空闲 {g[\"free_gb\"]}G')"
