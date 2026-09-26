export PATH=/root/miniconda3/bin:$PATH
echo '=== procs ==='
pgrep -af 'snapshot_download|python -' | grep -v pgrep | head -5
echo '=== disk usage ==='
du -sh /root/autodl-tmp/Qwen-Image-2.1 2>/dev/null
echo '=== fastest mirror, 8s sample each ==='
probe () {
  local name="$1" url="$2"
  local out
  out=$(curl -sL -m 8 -r 0-134217727 -o /dev/null -w '%{http_code} %{speed_download}' "$url" 2>/dev/null)
  echo "$name -> $out"
}
probe modelscope 'https://www.modelscope.cn/api/v1/models/Qwen/Qwen-Image-2.1/repo?Revision=master&FilePath=transformer/diffusion_pytorch_model-00001-of-00002.safetensors'
probe hfmirror  'https://hf-mirror.com/Qwen/Qwen-Image-2.1/resolve/main/transformer/diffusion_pytorch_model-00001-of-00002.safetensors'
source /etc/network_turbo >/dev/null 2>&1
probe hfproxy   'https://huggingface.co/Qwen/Qwen-Image-2.1/resolve/main/transformer/diffusion_pytorch_model-00001-of-00002.safetensors'
