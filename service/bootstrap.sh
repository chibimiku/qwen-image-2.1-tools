#!/bin/bash
# 一键环境恢复 / 首次开机初始化。
#   换机、重置系统、或用分享出去的镜像新建实例后，跑这一条就够：
#     bash /root/qwen-image-2.1/scripts/bootstrap.sh
set -u
export PATH=/root/miniconda3/bin:$PATH
R=/root/qwen-image-2.1
DIR=${QWEN_MODEL_DIR:-/root/autodl-tmp/Qwen-Image-2.1}
SKIP_START=${SKIP_START:-0}      # 1 = 只体检不起服务（排障用）
SKIP_DOWNLOAD=${SKIP_DOWNLOAD:-0} # 1 = 缺权重也只提示不下载
mkdir -p "$R"/{service,scripts,logs,outputs,inputs}

echo "==== 0/5 基本信息 ===="
echo "  实例 : $(hostname)"
echo "  区域 : $(grep -oP 'AutoDLRegion=\K\S+' /init/others/help 2>/dev/null || echo '?')"
echo "  Python: $(python -V 2>&1)"
python -c "import torch;print('  torch :', torch.__version__, '| CUDA 可用:', torch.cuda.is_available(),
  '|', torch.cuda.get_device_name(0) if torch.cuda.is_available() else '无 GPU')" 2>/dev/null || echo "  torch 不可用"
echo "  数据盘: $(df -h $DIR 2>/dev/null | tail -1 | awk '{print $4" 可用"}')"

echo
echo "==== 1/5 依赖 ===="
source /etc/network_turbo >/dev/null 2>&1
NEED_OK=1
for m in torch transformers diffusers accelerate safetensors fastapi uvicorn PIL; do
  V=$(python -c "import $m;print(getattr($m,'__version__','?'))" 2>/dev/null) || { echo "  $m 缺失"; NEED_OK=0; continue; }
  printf '  %-14s %s\n' "$m" "$V"
done
if [ "$NEED_OK" = "0" ]; then
  echo "  补装依赖（约 3~5 分钟）..."
  pip install -q -U "transformers>=5.17" accelerate safetensors hf_transfer sentencepiece \
      pillow fastapi "uvicorn[standard]" python-multipart requests modelscope 2>&1 | tail -2
  pip install -q "git+https://github.com/huggingface/diffusers.git" 2>&1 | tail -2
fi
python -c "from diffusers import QwenImage21Pipeline; print('  QwenImage21Pipeline 可用')" \
  || echo "  !! QwenImage21Pipeline 不可用，检查 diffusers 版本"

echo
echo "==== 2/5 权重（33 GB）===="
if [ -f "$DIR/model_index.json" ] && [ -z "$(find "$DIR" -name '*.incomplete' 2>/dev/null | head -1)" ]; then
  echo "  已就位：$(du -sh "$DIR" | cut -f1)"
  python - <<'PY'
import json, os, glob
d = os.environ.get("QWEN_MODEL_DIR", "/root/autodl-tmp/Qwen-Image-2.1")
shards = glob.glob(os.path.join(d, "**", "*.safetensors"), recursive=True)
total = sum(os.path.getsize(f) for f in shards)
print(f"  {len(shards)} 个分片，合计 {total/1e9:.2f} GB")
try:
    mi = json.load(open(os.path.join(d, "model_index.json")))
    print("  管线类 :", mi.get("_class_name"))
except Exception as e:
    print("  !! model_index.json 读取失败:", e)
PY
elif [ "$SKIP_DOWNLOAD" = "1" ]; then
  echo "  缺失或不完整（SKIP_DOWNLOAD=1，只提示不下载）"
  echo "  真要下载： bash $R/scripts/download_model.sh ms"
else
  echo "  缺失或不完整 —— 开始下载（ModelScope，约 12~35 MB/s，预计 20~40 分钟）"
  echo "  想挂后台： nohup bash $R/scripts/download_model.sh ms > /dev/null 2>&1 &"
  bash "$R/scripts/download_model.sh" ms
fi

echo
if [ "$SKIP_START" = "1" ]; then
  echo "==== 3/5 启动服务（SKIP_START=1，跳过）===="
  curl -s -m 5 localhost:6006/health | head -c 200; echo
else
  echo "==== 3/5 启动服务 ===="
  bash "$R/scripts/serve.sh" start
  for i in $(seq 1 60); do
    H=$(curl -s -m 5 localhost:6006/health 2>/dev/null)
    case "$H" in *'"loaded":true'*) echo "  服务就绪（等了 $((i*3))s）"; break;; esac
    sleep 3
  done
  curl -s -m 5 localhost:6006/health | head -c 320; echo
fi

echo
echo "==== 4/5 入口 ===="
bash "$R/scripts/show_url.sh" 2>/dev/null | head -18

echo
echo "==== 5/5 完成 ===="
cat <<'EOF'
  控制台    : <入口>/                     （API Key 自动填好，直接画）
  接口文档  : <入口>/docs?key=<你的KEY>         （可直接试调）
  笔记本    : JupyterLab 左侧进 qwen-image-2.1/service/ui/
              打开 Qwen-Image-2.1-console.ipynb（端口说明、API 速查都在里面）
  出图目录  : /root/qwen-image-2.1/outputs
  上传目录  : /root/qwen-image-2.1/inputs
EOF
