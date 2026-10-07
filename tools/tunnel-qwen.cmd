@echo off
rem 本地 SSH 隧道：把远端 Qwen-Image WebUI(6006) / 备用口(6008) 映射到本机。
rem   16006 -> 远端 127.0.0.1:6006   WebUI / API
rem   16008 -> 远端 127.0.0.1:6008   备用端口
rem
rem 用法：双击运行，窗口保持不关即可；关掉窗口隧道即断。
rem 端口若被占（旧隧道没清干净），先删掉本机 16006/16008 上的监听再跑。
rem
rem 密码不写在文件里：优先取环境变量 QWEN_SSH_PASS，没设才用下面的默认值。
rem 目标实例与 tools/deploy_autostart.py 的 DEFAULT_HOST 保持一致。
set SSH_HOST=connect.westd.seetacloud.com
set SSH_PORT=26791
set SSH_USER=root
if "%QWEN_SSH_PASS%"=="" set QWEN_SSH_PASS=xzkx5EgMwhvy

rem 用 askpass 喂密码，避免交互提示卡住无人值守的窗口
set SSH_ASKPASS=%~dp0askpass.cmd
set SSH_ASKPASS_REQUIRE=force
set DISPLAY=localhost:0

ssh -N -p %SSH_PORT% ^
  -o StrictHostKeyChecking=no -o UserKnownHostsFile=NUL ^
  -o PreferredAuthentications=password -o NumberOfPasswordPrompts=1 ^
  -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 -o ServerAliveCountMax=3 ^
  -L 16006:127.0.0.1:6006 -L 16008:127.0.0.1:6008 ^
  %SSH_USER%@%SSH_HOST%
