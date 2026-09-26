set -e
export PATH=/root/miniconda3/bin:$PATH
mkdir -p /root/qwen-image-2.1/{logs,outputs,scripts,service}
cd /root/qwen-image-2.1
echo "=== pip config ==="
pip config list 2>/dev/null || true
python -c "import sys,site;print(sys.prefix);print(site.getsitepackages())"
echo "=== disk of site-packages ==="
df -h /root/miniconda3 | tail -1
echo "=== install (log -> logs/install.log) ==="
source /etc/network_turbo >/dev/null 2>&1
nohup bash -c '
set -x
export PATH=/root/miniconda3/bin:$PATH
source /etc/network_turbo || true
pip install -U pip setuptools wheel
pip install "transformers>=5.17" accelerate safetensors "huggingface_hub[cli]" hf_transfer sentencepiece qwen-vl-utils pillow
pip install git+https://github.com/huggingface/diffusers.git
pip install fastapi "uvicorn[standard]" python-multipart requests
echo "=== INSTALL_DONE ==="
' > /root/qwen-image-2.1/logs/install.log 2>&1 &
echo "install pid: $!"
sleep 5
tail -5 /root/qwen-image-2.1/logs/install.log
