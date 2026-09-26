export PATH=/root/miniconda3/bin:$PATH
echo '=== resume backround download with 8 parallel workers ==='
pgrep -f snapshot_download >/dev/null && echo 'already running' || nohup python - <<'PY' > /root/qwen-image-2.1/logs/download.log 2>&1 &
from modelscope import snapshot_download
p = snapshot_download('Qwen/Qwen-Image-2.1', local_dir='/root/autodl-tmp/Qwen-Image-2.1',
                      max_workers=8)
print('DOWNLOAD_DONE', p)
PY
sleep 2
echo '=== speed test: single 256MB range from each mirror ==='
echo '-- modelscope (follow redirect) --'
curl -sL -m 20 -r 0-268435455 -o /dev/null -w 'code=%{http_code} speed=%{speed_download} B/s\n' \
  'https://www.modelscope.cn/api/v1/models/Qwen/Qwen-Image-2.1/repo?Revision=master&FilePath=transformer/diffusion_pytorch_model-00001-of-00002.safetensors'
echo '-- hf-mirror (follow redirect) --'
curl -sL -m 20 -r 0-268435455 -o /dev/null -w 'code=%{http_code} speed=%{speed_download} B/s\n' \
  'https://hf-mirror.com/Qwen/Qwen-Image-2.1/resolve/main/transformer/diffusion_pytorch_model-00001-of-00002.safetensors'
echo '-- huggingface via turbo proxy --'
source /etc/network_turbo >/dev/null 2>&1
curl -sL -m 20 -r 0-268435455 -o /dev/null -w 'code=%{http_code} speed=%{speed_download} B/s\n' \
  'https://huggingface.co/Qwen/Qwen-Image-2.1/resolve/main/transformer/diffusion_pytorch_model-00001-of-00002.safetensors'
echo '=== aria2 available? ==='
which aria2c || (echo 'installing aria2'; apt-get install -y -q aria2 >/dev/null 2>&1 && which aria2c) || echo 'no aria2'
