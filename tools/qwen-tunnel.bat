@echo off
chcp 65001 >nul
title SSH Tunnel - Qwen-Image-2.1 (close this window to stop)

REM ===========================================================================
REM  Double-click this file:
REM    1) opens an SSH tunnel  local:16006  ->  AutoDL instance -> remote:6006
REM    2) opens the browser at http://127.0.0.1:16006/
REM  Closing the window stops the tunnel.
REM
REM  Password login is used on purpose: Windows' bundled OpenSSH 9.5 fails the
REM  public-key signature handshake against the remote 8.9 server (key accepted,
REM  signature rejected). Do not share this file - it contains the password.
REM ===========================================================================

set INST_HOST=connect.west?.seetacloud.com
set INST_PORT=<你的端口>
set INST_USER=root
set INST_PASS=<你的实例密码>
set LOCAL_PORT=16006
set REMOTE_PORT=6006

set PY=C:\Program Files\Python310\python.exe
if not exist "%PY%" set PY=python

echo.
echo   =============================================================
echo     SSH tunnel  -^>  Qwen-Image-2.1
echo.
echo     Open in browser:  http://127.0.0.1:%LOCAL_PORT%/
echo     Remote target  :  %INST_HOST%:%INST_PORT%  -^>  127.0.0.1:%REMOTE_PORT%
echo.
echo     The console page fills the API key automatically.
echo     Close this window to stop the tunnel.
echo   =============================================================
echo.

netstat -ano | findstr /c:"127.0.0.1:%LOCAL_PORT%" | findstr "LISTENING" >nul 2>&1
if not errorlevel 1 (
    echo   [!] Local port %LOCAL_PORT% is already listening - tunnel seems up.
    echo       Opening http://127.0.0.1:%LOCAL_PORT%/
    timeout /t 5 >nul
    start "" "http://127.0.0.1:%LOCAL_PORT%/"
    exit /b 0
)

echo   Starting tunnel (about 2 seconds)...
start "" /min cmd /c "timeout /t 4 >nul & start http://127.0.0.1:%LOCAL_PORT%/"

"%PY%" -c "import paramiko" >nul 2>&1
if errorlevel 1 goto SSHFALLBACK

"%PY%" "%~dp0tunnel_serve.py" --host %INST_HOST% --port %INST_PORT% --user %INST_USER% --password "%INST_PASS%" --local-port %LOCAL_PORT% --remote-port %REMOTE_PORT%
goto END

:SSHFALLBACK
echo   [i] paramiko not found - falling back to ssh.exe (it will ask for the password)
echo.
"%SystemRoot%\System32\OpenSSH\ssh.exe" -p %INST_PORT% -o ServerAliveInterval=30 -o StrictHostKeyChecking=accept-new -L %LOCAL_PORT%:127.0.0.1:%REMOTE_PORT% %INST_USER%@%INST_HOST% -N

:END
echo.
echo   Tunnel closed.
pause
