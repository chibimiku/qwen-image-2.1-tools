export PATH=/root/miniconda3/bin:$PATH
source /root/qwen-image-2.1/qwen_env.sh
B=localhost:6006
H="Authorization: Bearer $QWEN_API_KEY"

# 干净重启（碎片化必须重启才能清掉，empty_cache 不够）
pkill -f 'service/server.py' 2>/dev/null; sleep 4
cd /root/qwen-image-2.1
nohup python service/server.py > logs/service.log 2>&1 &
echo $! > service.pid
for i in $(seq 1 60); do
  H2=$(curl -s -m 5 $B/health 2>/dev/null)
  case "$H2" in *'"loaded":true'*) echo "READY（干净状态）"; break;; esac
  sleep 3
done
curl -s $B/health | python3 -c "
import sys,json;g=json.load(sys.stdin)['gpu'];print(f'  初始 空闲 {g[\"free_gb\"]}G / 已用 {g[\"reserved_gb\"]}G')"

echo
echo '=== 1) 文生图 2048²（干净状态下应能跑）==='
curl -s -X POST $B/v1/images/generations -H 'Content-Type: application/json' -H "$H" \
  -d '{"prompt":"a quiet mountain lake at dawn, mist","width":2048,"height":2048,"num_inference_steps":10,"seed":3}' \
| python3 -c "
import sys,json
d=json.load(sys.stdin)
print('  '+('OK '+d['size']+'  每步 '+str(d['data'][0]['timing']['per_step_s'])+'s' if 'size' in d else 'FAIL: '+str(d.get('detail',''))[:90]))"
curl -s $B/health | python3 -c "
import sys,json;g=json.load(sys.stdin)['gpu'];print(f'  之后 空闲 {g[\"free_gb\"]}G')"

echo
echo '=== 2) 编辑 1184×1600（实测边界内，应 OK）==='
curl -s -X POST $B/v1/images/edits -H "$H" \
  -F "prompt=make it a watercolor" -F "num_inference_steps=6" -F "seed":=4 2>/dev/null >/dev/null
curl -s -X POST $B/v1/images/edits -H "$H" \
  -F "prompt=make it a watercolor" -F "num_inference_steps=6" -F "seed=4" \
  -F "image=@/tmp/ref_34.png" -F "width=1184" -F "height=1600" \
| python3 -c "
import sys,json
d=json.load(sys.stdin)
print('  '+('OK '+d['size'] if 'size' in d else 'FAIL: '+str(d.get('detail',''))[:90]))"

echo
echo '=== 3) 编辑 1280×1696（应被预检拦住，给出建议而不是崩）==='
curl -s -X POST $B/v1/images/edits -H "$H" \
  -F "prompt=make it a watercolor" -F "num_inference_steps=6" -F "seed=4" \
  -F "image=@/tmp/ref_34.png" -F "width=1280" -F "height=1696" \
| python3 -c "
import sys,json
d=json.load(sys.stdin)
print('  '+('OK '+d['size'] if 'size' in d else '拦住: '+str(d.get('detail',''))[:110]))"

echo
echo '=== 最终显存 ==='
curl -s $B/health | python3 -c "
import sys,json;h=json.load(sys.stdin);g=h['gpu']
print(f'  空闲 {g[\"free_gb\"]}G / 已用 {g[\"reserved_gb\"]}G / 峰值 {h[\"peak_allocated_gib\"]}G')"
