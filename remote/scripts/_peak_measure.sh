export PATH=/root/miniconda3/bin:$PATH
source /root/qwen-image-2.1/qwen_env.sh
B=localhost:6006
H="Authorization: Bearer $QWEN_API_KEY"

echo '=== 记录逐级峰值显存（全常驻 offload=none）==='
for WH in "1024 1360" "1152 1536" "1200 1600"; do
  set -- $WH
  curl -s -X POST $B/v1/admin/empty_cache -H "$H" >/dev/null
  BEFORE=$(curl -s $B/health | python3 -c "import sys,json;print(json.load(sys.stdin)['peak_allocated_gib'])")
  OUT=$(curl -s -X POST $B/v1/images/edits -H "$H" \
        -F "prompt=make it a watercolor" -F "num_inference_steps=6" -F "seed=4" \
        -F "image=@/tmp/ref_34.png" -F "width=$1" -F "height=$2")
  SZ=$(echo "$OUT" | python3 -c "
import sys,json
try: d=json.load(sys.stdin); print(d.get('size','ERR'))
except Exception: print('ERR')")
  AFTER=$(curl -s $B/health | python3 -c "import sys,json;print(json.load(sys.stdin)['peak_allocated_gib'])")
  MP=$(python3 -c "print(f'{$1*$2/1e6:.2f}')")
  printf '  %-12s %-6s MP  ->  %-12s  peak %s -> %s G\n' "$1x$2" "$MP" "$SZ" "$BEFORE" "$AFTER"
  # 峰值是累积最大值，这里看的是"是否被这次推高"
  curl -s -X POST $B/v1/admin/empty_cache -H "$H" >/dev/null
done
