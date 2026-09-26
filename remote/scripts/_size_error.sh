export PATH=/root/miniconda3/bin:$PATH
source /root/qwen-image-2.1/qwen_env.sh
B=localhost:6006
H="Authorization: Bearer $QWEN_API_KEY"

echo '=== 显式尺寸的完整响应（含错误）==='
for ARGS in "-F width=1696 -F height=2528" "-F width=1280 -F height=1696" "-F width=1088 -F height=1440" "-F aspect_ratio=2:3"; do
  echo "--- ${ARGS}"
  curl -s -X POST $B/v1/images/edits -H "$H" \
    -F "prompt=make it a watercolor" -F "num_inference_steps=6" -F "seed=4" \
    -F "image=@/tmp/ref_34.png" $ARGS | head -c 400
  echo
done

echo
echo '=== 服务端日志里的异常 ==='
tail -40 /root/qwen-image-2.1/logs/service.log | grep -iE '\[size\]|error|exception|oom|Traceback|memory' | tail -12

echo
echo '=== 显存现状 ==='
curl -s $B/health | python3 -c "
import sys,json;g=json.load(sys.stdin)['gpu'];print(f\"  free {g['free_gb']}G / reserved {g['reserved_gb']}G / total {g['total_gb']}G\")"

echo
echo '=== 估算：2K 编辑需要多少显存 ==='
python3 - <<'PY'
# 经验公式：编辑路径 = 常驻权重 30.2G + 目标图 latent/attention（随像素线性）
# 参考：1024² 编辑峰值约 36-39G；2048² 文生图（分块 VAE）峰值 32.5G
for w, h in [(768,1024), (896,1184), (1088,1440), (1280,1696), (1536,2048), (1696,2528)]:
    px = w*h
    est = 30.2 + 8.0 * px / (2048*2048)
    print(f"  {w}x{h} ({px/1e6:.2f}MP)  估算峰值 ≈ {est:.1f}G")
print("  可用 47.4G（其中权重已占 30.2G）")
PY
