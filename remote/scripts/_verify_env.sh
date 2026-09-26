export PATH=/root/miniconda3/bin:$PATH
source /root/qwen-image-2.1/qwen_env.sh
echo '=== download ==='
du -sh /root/autodl-tmp/Qwen-Image-2.1; find /root/autodl-tmp/Qwen-Image-2.1 -name '*.incomplete' | wc -l
grep -c DOWNLOAD_DONE /root/qwen-image-2.1/logs/download2.log || true
echo '=== sync service files ==='
mkdir -p /root/qwen-image-2.1/{service,scripts,logs,outputs}
chmod +x /root/qwen-image-2.1/scripts/*.sh 2>/dev/null
python -c "import ast,sys;ast.parse(open('/root/qwen-image-2.1/service/server.py').read());print('server.py syntax OK')"
python - <<'PY'
import importlib
for m in ['torch','transformers','diffusers','accelerate','fastapi','uvicorn','safetensors','PIL','qwen_vl_utils']:
    try:
        mod = importlib.import_module(m)
        print(f"{m:16s} {getattr(mod,'__version__','?')}")
    except Exception as e:
        print(f"{m:16s} FAIL {type(e).__name__}: {e}")
from diffusers import QwenImage21Pipeline
print('QwenImage21Pipeline import OK')
PY
