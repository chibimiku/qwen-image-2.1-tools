hostname
echo '--- date ---'; date
echo '--- gpu ---'; nvidia-smi 2>&1 | head -20
echo '--- cpu/mem ---'; nproc; free -g
echo '--- df -h ---'; df -h
echo '--- python ---'; python -V; which python pip conda
echo '--- torch ---'
python - <<'PY'
try:
    import torch
    print('torch', torch.__version__, 'cuda', torch.version.cuda, 'avail', torch.cuda.is_available())
except Exception as e:
    print('torch import failed:', e)
PY
echo '--- pip list (filtered) ---'
pip list 2>/dev/null | grep -iE 'torch|transformers|diffusers|accelerate|tokenizers|fastapi|uvicorn|pillow|modelscope|huggingface|numpy|safetensors'
echo '--- net ---'
curl -s -m 8 -o /dev/null -w 'hf:%{http_code}\n' https://huggingface.co
curl -s -m 8 -o /dev/null -w 'modelscope:%{http_code}\n' https://www.modelscope.cn
curl -s -m 8 -o /dev/null -w 'pypi:%{http_code}\n' https://pypi.org/simple/
echo '--- autodl-tmp ---'
ls -lah /root/autodl-tmp 2>&1 | head
echo '--- network_turbo ---'
ls -la /etc/network_turbo 2>&1
