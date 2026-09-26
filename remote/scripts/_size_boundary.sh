export PATH=/root/miniconda3/bin:$PATH
source /root/qwen-image-2.1/qwen_env.sh
B=localhost:6006
H="Authorization: Bearer $QWEN_API_KEY"

# 先清一次缓存，保证从干净状态开始
curl -s -X POST $B/v1/admin/empty_cache -H "$H" >/dev/null
echo "清理后显存: $(curl -s $B/health | python3 -c "import sys,json;print(json.load(sys.stdin)['gpu']['free_gb'],'G 空闲')")"

echo
echo '=== 编辑模式的显存边界（二分）==='
printf '%-18s %-8s %s\n' "目标尺寸" "MP" "结果"
for WH in "1024 1360" "1088 1440" "1152 1536" "1200 1600" "1280 1696"; do
  set -- $WH
  OUT=$(curl -s -X POST $B/v1/images/edits -H "$H" \
        -F "prompt=make it a watercolor" -F "num_inference_steps=6" -F "seed=4" \
        -F "image=@/tmp/ref_34.png" -F "width=$1" -F "height=$2")
  R=$(echo "$OUT" | python3 -c "
import sys,json
try:
    d=json.load(sys.stdin)
    print('OK ' + d['size'] if 'size' in d else 'ERR ' + str(d.get('detail',''))[:40])
except Exception: print('ERR parse')")
  MP=$(python3 -c "print(f'{$1*$2/1e6:.2f}')")
  printf '%-18s %-8s %s\n' "$1x$2" "$MP" "$R"
  curl -s -X POST $B/v1/admin/empty_cache -H "$H" >/dev/null
done

echo
echo '=== 每次请求后的峰值显存 ==='
curl -s $B/health | python3 -c "
import sys,json;h=json.load(sys.stdin)
print(f\"  peak_allocated={h['peak_allocated_gib']}G  now free={h['gpu']['free_gb']}G\")"
