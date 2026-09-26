export PATH=/root/miniconda3/bin:$PATH
cd /root/qwen-image-2.1
echo '=== pid file ==='; cat service.pid 2>/dev/null
echo '=== process ==='; pgrep -af 'service/server.py' | grep -v pgrep || echo 'not running'
echo '=== service.log tail ==='; tail -25 logs/service.log
echo '=== foreground import test ==='
python -c "
import sys; sys.argv=['x']
import importlib.util
spec = importlib.util.spec_from_file_location('srv','/root/qwen-image-2.1/service/server.py')
m = importlib.util.module_from_spec(spec)
try:
    spec.loader.exec_module(m)
    print('module import OK, DTYPE_KWARG=', m.DTYPE_KWARG, 'app=', type(m.app).__name__)
except Exception as e:
    import traceback; traceback.print_exc()
"
