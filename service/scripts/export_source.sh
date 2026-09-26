export PATH=/root/miniconda3/bin:$PATH
OUT=/root/qwen-image-2.1/docs_upstream
mkdir -p $OUT

echo '=== 导出 diffusers 的 QwenImage21 权威实现 ==='
D=$(python -c "import diffusers, os; print(os.path.dirname(diffusers.__file__))")
echo "diffusers: $D"
cp "$D/pipelines/qwenimage21/pipeline_qwenimage21.py" $OUT/diffusers-pipeline_qwenimage21.py
cp "$D/models/autoencoders/autoencoder_kl_qwenimage21.py" $OUT/diffusers-autoencoder_kl_qwenimage21.py
cp "$D/models/transformers/transformer_qwenimage21.py" $OUT/diffusers-transformer_qwenimage21.py 2>/dev/null || echo "  (transformer 文件名不同，列一下)"
ls "$D/models/transformers/" | grep -i qwen

echo
echo '=== 抓取 QwenImage21Pipeline.__call__ 的完整签名与文档字符串 ==='
python3 - <<'PY'
import inspect
from diffusers import QwenImage21Pipeline
src = inspect.getsource(QwenImage21Pipeline.__call__)
sig = src.split("):", 1)[0] + "):"
print(sig)
print()
# 只取 Args 段落
import re
m = re.search(r'Args:(.*?)(Returns:|Examples:|$)', inspect.getdoc(QwenImage21Pipeline.__call__) or "", re.S)
print(m.group(1).strip()[:4000] if m else "(no Args doc)")
PY

echo
echo '=== 产物 ==='
ls -la $OUT/
