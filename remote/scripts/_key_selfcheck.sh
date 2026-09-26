export PATH=/root/miniconda3/bin:$PATH
source /root/qwen-image-2.1/qwen_env.sh
B=localhost:6006
for i in $(seq 1 60); do
  H=$(curl -s -m 5 $B/health 2>/dev/null)
  case "$H" in *'"loaded":true'*) echo "READY after $((i*3))s"; break;; esac
  sleep 3
done

echo
echo '=== 配置 ==='
grep -E '^export QWEN_API_KEY|^export QWEN_API_KEYS|^export QWEN_UI_KEY' /root/qwen-image-2.1/qwen_env.sh | sed -E 's/(KEY=[^:]*:-)([a-z0-9]{4})[a-z0-9]*/\1\2…/'

echo
echo '=== 两个 key 都应可用 ==='
printf '  主 key  /v1/models      -> %s\n' "$(curl -s -o /dev/null -w '%{http_code}' -H "Authorization: Bearer $QWEN_API_KEY" $B/v1/models)"
printf '  1730    /v1/models      -> %s\n' "$(curl -s -o /dev/null -w '%{http_code}' -H 'Authorization: Bearer 1730' $B/v1/models)"
printf '  ?key=1730               -> %s\n' "$(curl -s -o /dev/null -w '%{http_code}' "$B/v1/models?key=1730")"
printf '  错误 key                -> %s   （期望 401）\n' "$(curl -s -o /dev/null -w '%{http_code}' -H 'Authorization: Bearer nope' $B/v1/models)"
printf '  无 key                  -> %s   （期望 401）\n' "$(curl -s -o /dev/null -w '%{http_code}' $B/v1/models)"
printf '  /docs?key=1730          -> %s\n' "$(curl -s -o /dev/null -w '%{http_code}' "$B/docs?key=1730")"

echo
echo '=== 登录接口两个 key 都能换会话 ==='
for K in "$QWEN_API_KEY" 1730; do
  CODE=$(curl -s -o /dev/null -w '%{http_code}' -X POST $B/v1/session \
         -H 'Content-Type: application/json' -d "{\"key\":\"$K\"}")
  printf '  POST /v1/session key=%s… -> %s\n' "${K:0:6}" "$CODE"
done
printf '  POST /v1/session 错 key  -> %s   （期望 401）\n' \
  "$(curl -s -o /dev/null -w '%{http_code}' -X POST $B/v1/session -H 'Content-Type: application/json' -d '{"key":"bad"}')"

echo
echo '=== 用 1730 登录后靠 Cookie 出图（模拟你在浏览器里操作）==='
COOKIE=$(curl -s -D - -o /dev/null -X POST $B/v1/session -H 'Content-Type: application/json' \
  -d '{"key":"1730"}' | grep -i '^set-cookie' | sed -E 's/^[Ss]et-[Cc]ookie: ([^;]+).*/\1/' | tr -d '\r')
echo "  Cookie: ${COOKIE:0:22}..."
curl -s -X POST $B/v1/images/generations -H 'Content-Type: application/json' -H "Cookie: $COOKIE" \
  -d '{"prompt":"a warm kitchen with bread on the table, morning light","width":768,"height":768,"num_inference_steps":10,"seed":5}' \
  | python3 -c "import sys,json;d=json.load(sys.stdin);print('  出图', d['size'], '| b64', len(d['data'][0]['b64_json']), '字节 | 每步', d['data'][0]['timing']['per_step_s'], 's')"

echo
echo '=== /health 里的鉴权信息 ==='
curl -s $B/health | python3 -c "
import sys,json;h=json.load(sys.stdin)
print(f\"  auth_required={h.get('auth_required')} ui_key_mode={h.get('ui_key_mode')} session_ttl={h.get('session_ttl_h')}h loaded={h['loaded']}\")"
