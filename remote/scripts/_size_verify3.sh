export PATH=/root/miniconda3/bin:$PATH
source /root/qwen-image-2.1/qwen_env.sh
B=localhost:6006
H="Authorization: Bearer $QWEN_API_KEY"
for i in $(seq 1 60); do
  H2=$(curl -s -m 5 $B/health 2>/dev/null)
  case "$H2" in *'"loaded":true'*) echo "READY"; break;; esac
  sleep 3
done
curl -s -X POST $B/v1/admin/empty_cache -H "$H" >/dev/null

echo
echo '=== 修正预检后的行为（期望：2.17MP 由预检拦住并给出可用尺寸建议）==='
printf '%-16s %-8s %s\n' "尺寸" "MP" "结果"
for WH in "1024 1360" "1200 1600" "1280 1696" "1696 2528"; do
  set -- $WH
  OUT=$(curl -s -X POST $B/v1/images/edits -H "$H" \
        -F "prompt=make it a watercolor" -F "num_inference_steps=6" -F "seed=4" \
        -F "image=@/tmp/ref_34.png" -F "width=$1" -F "height=$2")
  R=$(echo "$OUT" | python3 -c "
import sys,json
d=json.load(sys.stdin)
if 'size' in d: print('OK ' + d['size'])
else: print('拦住: ' + str(d.get('detail',''))[:90])")
  MP=$(python3 -c "print(f'{$1*$2/1e6:.2f}')")
  printf '%-16s %-8s %s\n' "$1x$2" "$MP" "$R"
  curl -s -X POST $B/v1/admin/empty_cache -H "$H" >/dev/null
done

echo
echo '=== 文生图 2048² 仍然正常（不该被新公式误拦）==='
curl -s -X POST $B/v1/images/generations -H 'Content-Type: application/json' -H "$H" \
  -d '{"prompt":"a quiet mountain lake","width":2048,"height":2048,"num_inference_steps":8,"seed":3}' \
  | python3 -c "
import sys,json
d=json.load(sys.stdin)
print('  ' + (d['size'] + ' OK  每步 ' + str(d['data'][0]['timing']['per_step_s']) + 's') if 'size' in d else '  拦住: ' + str(d.get('detail'))[:90])"

echo
echo '=== 前端新片段 ==='
BODY=$(curl -s $B/)
for p in sizeAdvice EDIT_OK_MP EDIT_BAD_MP LAST_FREE_GIB; do
  printf '  %-16s %s\n' "$p" "$(echo "$BODY" | grep -c "$p")"
done
