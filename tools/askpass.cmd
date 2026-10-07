@echo off
rem ssh 的 askpass 回调：只负责把密码打到 stdout。
rem tools/tunnel-qwen.cmd 会设置 SSH_ASKPASS 指向本文件，
rem 免得密码硬编码在隧道命令行里、也免得弹出交互提示把无人值守的窗口卡住。
if "%QWEN_SSH_PASS%"=="" (
  echo 请先设置环境变量 QWEN_SSH_PASS 再启动隧道 >&2
  exit /b 1
)
echo %QWEN_SSH_PASS%
