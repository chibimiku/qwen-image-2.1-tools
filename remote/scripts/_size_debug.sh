export PATH=/root/miniconda3/bin:$PATH
source /root/qwen-image-2.1/qwen_env.sh
B=localhost:6006
H="Authorization: Bearer $QWEN_API_KEY"

# 带调试日志重启
pkill -f 'service/server.py' 2>/dev/null; sleep 3
QWEN_DEBUG_SIZE=1 nohup python /root/qwen-image-2.1/service/server.py \
  > /root/qwen-image-2.1/logs/service.log 2>&1 &
echo $! > /root/qwen-image-2.1/service.pid
for i in $(seq 1 60); do
  H2=$(curl -s -m 5 $B/health 2>/dev/null)
  case "$H2" in *'"loaded":true'*) echo "READY"; break;; esac
  sleep 3
done

echo
echo '=== 直接打接口（绕开脚本拼参），看服务端收到的值 ==='
for ARGS in "" "-F width=1696 -F height=2528" "-F aspect_ratio=2:3" "-F output_resolution=1280"; do
  echo "--- 参数: ${ARGS:-（无）}"
  OUT=$(curl -s -X POST $B/v1/images/edits -H "$H" \
        -F "prompt=make it a watercolor" -F "num_inference_steps=6" -F "seed=4" \
        -F "image=@/tmp/ref_34.png" $ARGS)
  echo "$OUT" | python3 -c "
import sys,json
try:
    d=json.load(sys.stdin); print('    输出:', d['size'])
except Exception as e:
    print('    解析失败:', sys.stdin.read()[:200] if False else e)"
done

echo
echo '=== 服务端 [size] 日志 ==='
grep '\[size\]' /root/qwen-image-2.1/logs/service.log | tail -8
