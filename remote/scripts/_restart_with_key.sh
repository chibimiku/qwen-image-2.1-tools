export PATH=/root/miniconda3/bin:$PATH
source /root/qwen-image-2.1/qwen_env.sh
cd /root/qwen-image-2.1
pkill -f 'service/server.py' 2>/dev/null; sleep 3
bash scripts/serve.sh start
for i in $(seq 1 40); do
  H=$(curl -s -m 5 localhost:6006/health 2>/dev/null)
  case "$H" in *'"loaded":true'*) echo "READY"; break;; esac
  sleep 5
done
echo
echo '=== 鉴权自测（服务启动后 QWEN_API_KEY=1730）==='
K="${QWEN_API_KEY}"
echo "key = $K"
printf '  /health  无key        -> %s\n' "$(curl -s -o /dev/null -w '%{http_code}' localhost:6006/health)"
printf '  /        无key        -> %s\n' "$(curl -s -o /dev/null -w '%{http_code}' localhost:6006/)"
printf '  /v1/models 无key      -> %s\n' "$(curl -s -o /dev/null -w '%{http_code}' localhost:6006/v1/models)"
printf '  /v1/models Bad key    -> %s\n' "$(curl -s -o /dev/null -w '%{http_code}' localhost:6006/v1/models -H 'Authorization: Bearer wrong')"
printf '  /v1/models Bearer ok  -> %s\n' "$(curl -s -o /dev/null -w '%{http_code}' localhost:6006/v1/models -H "Authorization: Bearer $K")"
printf '  /v1/models ?key=ok    -> %s\n' "$(curl -s -o /dev/null -w '%{http_code}' "localhost:6006/v1/models?key=$K")"
printf '  /openapi.json 无key   -> %s\n' "$(curl -s -o /dev/null -w '%{http_code}' localhost:6006/openapi.json)"
printf '  /docs 无key           -> %s\n' "$(curl -s -o /dev/null -w '%{http_code}' localhost:6006/docs)"
printf '  /docs ?key=ok         -> %s\n' "$(curl -s -o /dev/null -w '%{http_code}' "localhost:6006/docs?key=$K")"
echo
echo '=== 页面是否注入了 key ==='
curl -s localhost:6006/ | grep -o 'id="apikey" value="[^"]*"' | head -1
echo
echo '=== 真跑一张（带 key）==='
curl -s -m 300 -X POST "localhost:6006/v1/images/generations" \
  -H 'Content-Type: application/json' -H "Authorization: Bearer $K" \
  -d '{"prompt":"a small red boat on a calm sea at dawn","width":512,"height":512,"num_inference_steps":8,"seed":7}' \
  | python -c "import sys,json;d=json.load(sys.stdin);print('OK', d['size'], 'b64 len', len(d['data'][0]['b64_json']))"
