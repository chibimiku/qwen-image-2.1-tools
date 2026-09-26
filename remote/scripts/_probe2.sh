echo '--- PATH ---'; echo $PATH
echo '--- network_turbo content ---'; cat /etc/network_turbo
echo '--- find python ---'
ls -la /root/miniconda3/bin/python* 2>&1 | head
ls -la /usr/bin/python* 2>&1 | head
command -v python3; python3 -V 2>&1
echo '--- conda envs ---'
ls -la /root/miniconda3/envs 2>&1 | head
echo '--- autodl-tmp perms ---'
df -h /root/autodl-tmp; touch /root/autodl-tmp/.wtest && echo 'autodl-tmp writable' || echo 'autodl-tmp NOT writable'
echo '--- autodl-fs ---'
touch /autodl-fs/data/.wtest && echo 'autodl-fs writable' || echo 'autodl-fs NOT writable'
ls -la /autodl-fs/data 2>&1 | head
echo '--- pub cache ---'
ls /autodl-pub 2>&1 | head
echo '--- image marker ---'
cat /root/.bashrc 2>/dev/null | tail -20
echo '--- init dir ---'
ls -la /init 2>&1 | head