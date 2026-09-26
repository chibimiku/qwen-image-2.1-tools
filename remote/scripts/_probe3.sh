export PATH=/root/miniconda3/bin:$PATH
source /etc/profile 2>/dev/null
echo '--- python ---'; python -V; which python pip
echo '--- torch/transformers ---'
python - <<'PY'
mods = ['torch','torchvision','transformers','diffusers','accelerate','safetensors','PIL','numpy','huggingface_hub','modelscope','fastapi','uvicorn','tokenizers','sentencepiece','einops']
for m in mods:
    try:
        mod = __import__(m)
        print(f"{m:16s} OK   {getattr(mod,'__version__','?')}")
    except Exception as e:
        print(f"{m:16s} MISS {type(e).__name__}")
try:
    import torch
    print('cuda compiled:', torch.version.cuda, 'available:', torch.cuda.is_available())
except Exception as e:
    print('torch err', e)
PY
echo '--- pip list ---'
pip list 2>/dev/null | head -60
echo '--- turbo + hf test ---'
source /etc/network_turbo >/dev/null 2>&1
curl -s -m 12 -o /dev/null -w 'hf_api:%{http_code}\n' https://huggingface.co/api/models/Qwen/Qwen-Image-2.1
curl -s -m 12 -o /dev/null -w 'github:%{http_code}\n' https://github.com
echo '--- gpu visible ---'
ls -la /dev/nvidia* 2>&1 | head
cat /proc/driver/nvidia/version 2>&1 | head -3
echo '--- autodl-fs space ---'
df -h /autodl-fs/data
echo '--- autodl proxy cfg ---'
ls -la /init/proxy; cat /init/proxy/* 2>/dev/null | head -20
