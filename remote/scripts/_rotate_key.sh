export PATH=/root/miniconda3/bin:$PATH
source /root/qwen-image-2.1/qwen_env.sh
echo "=== 当前配置 ==="
grep -E '^export QWEN_API_KEY|^export QWEN_UI_KEY' /root/qwen-image-2.1/qwen_env.sh
echo "  key 长度: ${#QWEN_API_KEY}   模式: ${QWEN_UI_KEY}"

echo
echo '=== 重启服务 ==='
bash /root/qwen-image-2.1/scripts/serve.sh stop >/dev/null 2>&1
pkill -f 'service/server.py' 2>/dev/null; sleep 3
bash /root/qwen-image-2.1/scripts/serve.sh start
for i in $(seq 1 60); do
  H=$(curl -s -m 5 localhost:6006/health 2>/dev/null)
  case "$H" in *'"loaded":true'*) echo "  READY after $((i*3))s"; break;; esac
  sleep 3
done

echo
echo '=== 验证：auto 模式下页面不再包含 key ==='
BODY=$(curl -s localhost:6006/)
echo "  页面字节: ${#BODY}"
echo -n "  含 key 明文: "; if echo "$BODY" | grep -qF "$QWEN_API_KEY"; then echo "有 ✗ (不该有)"; else echo "没有 ✓"; fi
echo -n "  __QWEN_KEY_INJECT__ 占位符残留: "; echo "$BODY" | grep -c '__QWEN_KEY_INJECT__'
echo -n "  apikey 输入框的值: "; echo "$BODY" | grep -oP 'id="apikey" value="\K[^"]*' | head -1
echo -n "  KEY_MODE 注入值: "; echo "$BODY" | grep -oP 'const KEY_MODE = "\K[^"]*' | head -1
echo -n "  响应头 X-UI-Key-Mode: "; curl -s -D - -o /dev/null localhost:6006/ | grep -i 'x-ui-key-mode' | tr -d '\r'

echo
echo '=== 验证：接口鉴权仍然有效（新 key）==='
printf '  /health            免鉴权 -> %s\n' "$(curl -s -o /dev/null -w '%{http_code}' localhost:6006/health)"
printf '  /                  免鉴权 -> %s\n' "$(curl -s -o /dev/null -w '%{http_code}' localhost:6006/)"
printf '  /v1/models         无 key -> %s\n' "$(curl -s -o /dev/null -w '%{http_code}' localhost:6006/v1/models)"
printf '  /v1/models         旧 key -> %s\n' "$(curl -s -o /dev/null -w '%{http_code}' -H 'Authorization: Bearer 1730' localhost:6006/v1/models)"
printf '  /v1/models         新 key -> %s\n' "$(curl -s -o /dev/null -w '%{http_code}' -H "Authorization: Bearer $QWEN_API_KEY" localhost:6006/v1/models)"
printf '  /docs              无 key -> %s\n' "$(curl -s -o /dev/null -w '%{http_code}' localhost:6006/docs)"
printf '  /docs              新 key -> %s\n' "$(curl -s -o /dev/null -w '%{http_code}' "localhost:6006/docs?key=$QWEN_API_KEY")"

echo
echo '=== 验证：带新 key 真出一张图 ==='
python - <<'PY'
import base64, json, os, time, urllib.request
key = os.environ["QWEN_API_KEY"]
body = json.dumps({"prompt": "a cozy wooden cabin in a snowy pine forest, warm window light",
                   "width": 768, "height": 768, "num_inference_steps": 12, "seed": 7}).encode()
r = urllib.request.Request("http://127.0.0.1:6006/v1/images/generations", data=body,
                           headers={"Content-Type": "application/json",
                                    "Authorization": "Bearer " + key})
t0 = time.time()
with urllib.request.urlopen(r, timeout=600) as resp:
    d = json.loads(resp.read())
it = d["data"][0]
open("/root/qwen-image-2.1/outputs/01_after_key_rotate.png", "wb").write(base64.b64decode(it["b64_json"]))
print(f"  {it['width']}x{it['height']} · {time.time()-t0:.1f}s · 每步 {it['timing']['per_step_s']}s")
print("  已存 outputs/01_after_key_rotate.png")
PY
