export PATH=/root/miniconda3/bin:$PATH
echo '=== public datasets (qwen) ==='
ls /autodl-pub/data 2>/dev/null | head -20
find /autodl-pub -maxdepth 3 -iname '*Qwen*Image*' 2>/dev/null | head -20
echo '=== kill slow ms download ==='
pkill -f snapshot_download 2>/dev/null && echo killed || echo 'no proc'
echo '=== speed probe: hf-mirror / hf-proxy / ms direct ==='
# 1) hf-mirror.com (no proxy)
curl -s -m 20 -o /dev/null -w 'hfmirror:%{http_code} speed=%{speed_download}B/s\n' \
  https://hf-mirror.com/Qwen/Qwen-Image-2.1/resolve/main/model_index.json
# 2) huggingface via turbo proxy
source /etc/network_turbo >/dev/null 2>&1
curl -s -m 20 -o /dev/null -w 'hf_proxy:%{http_code} speed=%{speed_download}B/s\n' \
  https://huggingface.co/Qwen/Qwen-Image-2.1/resolve/main/model_index.json
unset http_proxy https_proxy
# 3) modelscope direct file
curl -sL -m 20 -o /dev/null -w 'ms_direct:%{http_code} speed=%{speed_download}B/s\n' \
  'https://www.modelscope.cn/api/v1/models/Qwen/Qwen-Image-2.1/repo?Revision=master&FilePath=model_index.json'
echo '=== big-file probe (1 GiB range, hf-mirror) ==='
curl -s -m 25 -r 0-268435456 -o /dev/null -w 'hfmirror_1G:%{http_code} speed=%{speed_download}B/s\n' \
  'https://hf-mirror.com/Qwen/Qwen-Image-2.1/resolve/main/transformer/diffusion_pytorch_model-00001-of-00004.safetensors' 2>&1 | tail -2
echo '=== big-file probe (1 GiB range, ms) ==='
curl -sL -m 25 -r 0-268435456 -o /dev/null -w 'ms_1G:%{http_code} speed=%{speed_download}B/s\n' \
  'https://www.modelscope.cn/api/v1/models/Qwen/Qwen-Image-2.1/repo?Revision=master&FilePath=transformer/diffusion_pytorch_model-00001-of-00004.safetensors' 2>&1 | tail -2
