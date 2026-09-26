export PATH=/root/miniconda3/bin:$PATH
source /root/qwen-image-2.1/qwen_env.sh
B=localhost:6006
H="Authorization: Bearer $QWEN_API_KEY"

probe () {
  local desc="$1"; shift
  local out code
  out=$(curl -s -w '\n__HTTP__%{http_code}' "$@" 2>/dev/null)
  code=$(echo "$out" | tail -1 | sed 's/__HTTP__//')
  body=$(echo "$out" | sed '$d' | head -c 220)
  printf '  %-34s HTTP %s  %s\n' "$desc" "$code" "$body"
}

echo '=== 带图请求逐个诊断 ==='
B64=$(python3 -c "import base64;print(base64.b64encode(open('/tmp/person_a.png','rb').read()).decode())")
echo "  (image_b64 长度: ${#B64})"

probe "JSON 无图" -X POST $B/v1/images/generations -H 'Content-Type: application/json' -H "$H" \
  -d '{"prompt":"a boat","num_inference_steps":6,"seed":1}'

python3 - "$B64" <<'PY' > /tmp/req_b64.json
import json, sys
print(json.dumps({"prompt": "a boat", "num_inference_steps": 6, "seed": 1,
                  "image_b64": [sys.argv[1]]}))
PY
probe "JSON + image_b64" -X POST $B/v1/images/generations -H 'Content-Type: application/json' -H "$H" \
  --data-binary @/tmp/req_b64.json

probe "multipart 无图" -X POST $B/v1/images/generations -H "$H" \
  -F "prompt=a boat" -F "num_inference_steps=6" -F "seed=1"

probe "multipart + 1 图" -X POST $B/v1/images/generations -H "$H" \
  -F "prompt=a boat" -F "num_inference_steps=6" -F "seed=1" -F "image=@/tmp/person_a.png"

probe "旧端点 /edits + 1 图" -X POST $B/v1/images/edits -H "$H" \
  -F "prompt=a boat" -F "num_inference_steps=6" -F "seed=1" -F "image=@/tmp/person_a.png"

echo
echo '=== 服务端日志里的异常 ==='
grep -nE 'Traceback|Error|error|raise|Exception' /root/qwen-image-2.1/logs/service.log | tail -15
echo
echo '=== 日志尾部 ==='
tail -12 /root/qwen-image-2.1/logs/service.log
