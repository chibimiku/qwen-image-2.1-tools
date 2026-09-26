export PATH=/root/miniconda3/bin:$PATH
source /root/qwen-image-2.1/qwen_env.sh
B=localhost:6006
H="Authorization: Bearer $QWEN_API_KEY"

echo '=== 用 serve.sh 重启（它会设 QWEN_TILE_VAE=1，别用裸 python 起）==='
pkill -f 'service/server.py' 2>/dev/null; sleep 4
bash /root/qwen-image-2.1/scripts/serve.sh start
for i in $(seq 1 60); do
  H2=$(curl -s -m 5 $B/health 2>/dev/null)
  case "$H2" in *'"loaded":true'*) echo "READY"; break;; esac
  sleep 3
done

echo
echo '=== 确认 VAE 分块已开 ==='
grep -o 'tile_vae=[01]' /root/qwen-image-2.1/logs/service.log | tail -1
python3 -c "
import sys; sys.path.insert(0,'/root/qwen-image-2.1/service')
import os
os.environ.setdefault('QWEN_OFFLOAD','none')
print('  进程内 QWEN_TILE_VAE =', os.environ.get('QWEN_TILE_VAE','(未设→0)'))
" 2>&1 | tail -1
curl -s $B/health | python3 -c "
import sys,json;h=json.load(sys.stdin);g=h['gpu'];print(f'  初始 空闲 {g[\"free_gb\"]}G / 已用 {g[\"reserved_gb\"]}G')"

echo
echo '=== 1) 文生图 2048²（分块 VAE 下应能跑）==='
curl -s -X POST $B/v1/images/generations -H 'Content-Type: application/json' -H "$H" \
  -d '{"prompt":"a quiet mountain lake at dawn, mist","width":2048,"height":2048,"num_inference_steps":12,"seed":3}' \
| python3 -c "
import sys,json
d=json.load(sys.stdin)
print('  '+('OK '+d['size']+'  每步 '+str(d['data'][0]['timing']['per_step_s'])+'s' if 'size' in d else 'FAIL: '+str(d.get('detail',''))[:90]))"
curl -s -X POST $B/v1/admin/empty_cache -H "$H" >/dev/null

echo
echo '=== 2) 编辑 1184×1600（边界内）==='
curl -s -X POST $B/v1/images/edits -H "$H" \
  -F "prompt=make it a watercolor" -F "num_inference_steps=6" -F "seed=4" \
  -F "image=@/tmp/ref_34.png" -F "width=1184" -F "height=1600" \
| python3 -c "
import sys,json
d=json.load(sys.stdin)
print('  '+('OK '+d['size'] if 'size' in d else 'FAIL: '+str(d.get('detail',''))[:100]))"
curl -s -X POST $B/v1/admin/empty_cache -H "$H" >/dev/null

echo
echo '=== 3) 编辑 1280×1696（应被预检拦住）==='
curl -s -X POST $B/v1/images/edits -H "$H" \
  -F "prompt=make it a watercolor" -F "num_inference_steps=6" -F "seed=4" \
  -F "image=@/tmp/ref_34.png" -F "width=1280" -F "height=1696" \
| python3 -c "
import sys,json
d=json.load(sys.stdin)
print('  '+('OK '+d['size'] if 'size' in d else '拦住: '+str(d.get('detail',''))[:100]))"

echo
echo '=== 最终显存 ==='
curl -s $B/health | python3 -c "
import sys,json;h=json.load(sys.stdin);g=h['gpu']
print(f'  空闲 {g[\"free_gb\"]}G / 已用 {g[\"reserved_gb\"]}G / 峰值 {h[\"peak_allocated_gib\"]}G')"
