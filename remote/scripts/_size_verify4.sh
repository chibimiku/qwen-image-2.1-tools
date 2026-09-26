export PATH=/root/miniconda3/bin:$PATH
source /root/qwen-image-2.1/qwen_env.sh
B=localhost:6006
H="Authorization: Bearer $QWEN_API_KEY"

pkill -f 'service/server.py' 2>/dev/null; sleep 3
cd /root/qwen-image-2.1
nohup python service/server.py > logs/service.log 2>&1 &
echo $! > service.pid
echo "pid=$(cat service.pid)"
for i in $(seq 1 60); do
  H2=$(curl -s -m 5 $B/health 2>/dev/null)
  case "$H2" in *'"loaded":true'*) echo "READY after $((i*3))s"; break;; esac
  sleep 3
done
curl -s -X POST $B/v1/admin/empty_cache -H "$H" >/dev/null

echo
echo '=== 文生图（不该被误拦）==='
for WH in "1024 1024" "2048 2048"; do
  set -- $WH
  curl -s -X POST $B/v1/images/generations -H 'Content-Type: application/json' -H "$H" \
    -d "{\"prompt\":\"a quiet mountain lake\",\"width\":$1,\"height\":$2,\"num_inference_steps\":8,\"seed\":3}" \
  | python3 -c "
import sys,json
d=json.load(sys.stdin)
print('  '+('OK '+d['size']+'  每步 '+str(d['data'][0]['timing']['per_step_s'])+'s' if 'size' in d else '拦住: '+str(d.get('detail',''))[:80]))"
done

echo
echo '=== 编辑（实测边界应被正确执行）==='
for WH in "1200 1600" "1280 1696"; do
  set -- $WH
  curl -s -X POST $B/v1/images/edits -H "$H" \
    -F "prompt=make it a watercolor" -F "num_inference_steps=6" -F "seed=4" \
    -F "image=@/tmp/ref_34.png" -F "width=$1" -F "height=$2" \
  | python3 -c "
import sys,json
d=json.load(sys.stdin)
print('  '+('OK '+d['size'] if 'size' in d else '拦住: '+str(d.get('detail',''))[:80]))"
  curl -s -X POST $B/v1/admin/empty_cache -H "$H" >/dev/null
done

echo
echo '=== 服务端生效的公式系数 ==='
python3 -c "
import sys; sys.path.insert(0,'/root/qwen-image-2.1/service')
import server as s
print(f'  EDIT 二次项={s.LATENT_QUADRATIC_EDIT}  T2I 二次项={s.LATENT_QUADRATIC_T2I}  线性={s.LATENT_GIB_2K}')
for w,h,m in [(2048,2048,'t2i'),(1280,1696,'edit'),(1184,1600,'edit')]:
    print(f'  {w}x{h} {m}: 需要 {s.estimate_transient_gib(w,h,8,m)}G')
" 2>&1 | tail -5
