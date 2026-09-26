export PATH=/root/miniconda3/bin:$PATH
source /root/qwen-image-2.1/qwen_env.sh
K="$QWEN_API_KEY"
B=localhost:6006

echo '=== 1) 会话流程（协议层）==='
printf '  GET  /v1/session 未登录      -> %s  %s\n' \
  "$(curl -s -o /dev/null -w '%{http_code}' $B/v1/session)" \
  "$(curl -s $B/v1/session)"
printf '  POST /v1/session 错 key      -> %s\n' \
  "$(curl -s -o /dev/null -w '%{http_code}' -X POST $B/v1/session -H 'Content-Type: application/json' -d '{"key":"wrong"}')"
echo '  POST /v1/session 正确 key    -> 看下面的 Set-Cookie'
curl -s -D - -o /dev/null -X POST $B/v1/session -H 'Content-Type: application/json' \
  -d "{\"key\":\"$K\"}" | grep -iE '^(HTTP|set-cookie)'
COOKIE=$(curl -s -D - -o /dev/null -X POST $B/v1/session -H 'Content-Type: application/json' \
  -d "{\"key\":\"$K\"}" | grep -i '^set-cookie' | sed -E 's/^[Ss]et-[Cc]ookie: ([^;]+).*/\1/' | tr -d '\r')
echo "  拿到 Cookie: ${COOKIE:0:24}..."
printf '  带 Cookie /v1/models         -> %s  （期望 200）\n' \
  "$(curl -s -o /dev/null -w '%{http_code}' -H "Cookie: $COOKIE" $B/v1/models)"
printf '  不带 Cookie /v1/models       -> %s  （期望 401）\n' \
  "$(curl -s -o /dev/null -w '%{http_code}' $B/v1/models)"
printf '  带 Cookie 出图               -> '
curl -s -X POST $B/v1/images/generations -H 'Content-Type: application/json' \
  -H "Cookie: $COOKIE" \
  -d '{"prompt":"a paper boat on a puddle","width":512,"height":512,"num_inference_steps":6,"seed":11}' \
  | python3 -c "import sys,json;d=json.load(sys.stdin);print(d['size'], 'b64', len(d['data'][0]['b64_json']))"
printf '  DELETE /v1/session           -> %s\n' \
  "$(curl -s -o /dev/null -w '%{http_code}' -X DELETE $B/v1/session -H "Cookie: $COOKIE")"
printf '  退出后带旧 Cookie /v1/models -> %s  （期望 401）\n' \
  "$(curl -s -o /dev/null -w '%{http_code}' -H "Cookie: $COOKIE" $B/v1/models)"

echo
echo '=== 2) 新 UI 里的功能片段 ==='
BODY=$(curl -s $B/)
for pat in collectForm loadForm saveForm syncRatio rationote FORM_STORE 'id="login"' 'id="sessbar"'; do
  printf '  %-16s %s\n' "$pat" "$(echo "$BODY" | grep -c "$pat")"
done
echo -n "  页面含 key 明文: "; echo "$BODY" | grep -qF "$K" && echo '有 ✗' || echo '没有 ✓'
echo -n "  localStorage 用法: "; echo "$BODY" | grep -o 'localStorage\.[a-zA-Z]*' | sort -u | tr '\n' ' '; echo

echo
echo '=== 3) 服务与显存 ==='
curl -s $B/health | python3 -c "
import sys, json
h = json.load(sys.stdin)
g = h['gpu']
print(f\"  loaded={h['loaded']} 鉴权需要={h.get('auth_required')} UI模式={h.get('ui_key_mode')} 会话TTL={h.get('session_ttl_h')}h\")
print(f\"  显存 空闲 {g['free_gb']}G / 已用 {g['reserved_gb']}G / 总 {g['total_gb']}G\")
"
