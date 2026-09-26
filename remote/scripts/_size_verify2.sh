export PATH=/root/miniconda3/bin:$PATH
source /root/qwen-image-2.1/qwen_env.sh
B=localhost:6006
K="$QWEN_API_KEY"
H="Authorization: Bearer $K"
for i in $(seq 1 60); do
  H2=$(curl -s -m 5 $B/health 2>/dev/null)
  case "$H2" in *'"loaded":true'*) echo "READY"; break;; esac
  sleep 3
done

echo
echo '=== 编辑接口尺寸规则复测（预期：不传跟随参考图 / 传了用你给的值 / 档位可覆盖）==='
printf '%-14s %-34s %s\n' "参考图" "参数" "实际输出"
echo '--------------------------------------------------------------------------'
for REF in /tmp/ref_34.png /tmp/ref_43.png; do
  for CASE in "none|" "res1024|-F output_resolution=1024" "res1280|-F output_resolution=1280" "wh1536|-F width=1536 -F height=2048" "ratio23|-F aspect_ratio=2:3"; do
    NAME="${CASE%%|*}"; ARGS="${CASE#*|}"
    OUT=$(curl -s -X POST $B/v1/images/edits -H "$H" \
          -F "prompt=make it a watercolor painting" -F "num_inference_steps=6" -F "seed=4" \
          -F "image=@$REF" $ARGS)
    SZ=$(echo "$OUT" | python3 -c "
import sys,json
try: print(json.load(sys.stdin)['size'])
except Exception: print('ERR')")
    printf '%-14s %-34s %s\n' "$(basename $REF)" "$NAME" "$SZ"
  done
done

echo
echo '=== 编辑显式 2K 是否真的出得来（重点）==='
for ARGS in "-F width=1696 -F height=2528" "-F aspect_ratio=2:3"; do
  OUT=$(curl -s -X POST $B/v1/images/edits -H "$H" \
        -F "prompt=a knight standing in a rainy forest, full body, detailed" \
        -F "num_inference_steps=8" -F "seed=12" -F "image=@/tmp/ref_34.png" $ARGS)
  echo "$OUT" | python3 -c "
import sys,json
d=json.load(sys.stdin); it=d['data'][0]
print(f\"  {'$ARGS'[:34]:36s} -> {d['size']}  耗时 {it['elapsed_s']}s  每步 {it['timing']['per_step_s']}s\")" 2>/dev/null || echo "  失败"
done

echo
echo '=== 显存 ==='
curl -s $B/health | python3 -c "
import sys,json;g=json.load(sys.stdin)['gpu'];print(f\"  空闲 {g['free_gb']}G / 已用 {g['reserved_gb']}G\")"
