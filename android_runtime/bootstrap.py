"""Host bootstrap: Lima on Mac, native Linux, a dedicated QEMU guest on Windows."""
from __future__ import annotations
import json
import os
import platform
import secrets
import shutil
import subprocess
import sys
import urllib.request
import hashlib
from pathlib import Path

VM_NAME = 'haybot-android'
PORT = 17321
GUEST_INSTALL = '''export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y docker.io adb python3-venv linux-modules-extra-$(uname -r)
python3 -m venv /opt/haybot-u2
/opt/haybot-u2/bin/pip install 'uiautomator2==3.7.1'
mkdir -p /etc/modules-load.d /etc/modprobe.d
echo binder_linux >/etc/modules-load.d/haybot-android.conf
echo 'options binder_linux devices=binder,hwbinder,vndbinder' >/etc/modprobe.d/haybot-android.conf
modprobe binder_linux devices=binder,hwbinder,vndbinder
systemctl enable --now docker
'''


def qemu_arguments(directory, system=None, machine=None):
    system = system or platform.system(); machine = (machine or platform.machine()).lower()
    if system != 'Windows' or machine not in ('amd64', 'x86_64'):
        raise ValueError('专用 QEMU 底座当前仅支持 Windows x64；其他平台使用 Lima 或原生 Linux')
    directory = Path(directory)
    return ['qemu-system-x86_64', '-accel', 'whpx', '-machine', 'q35', '-smp', '4', '-m', '6144',
            '-drive', f'file={directory / "guest.qcow2"},format=qcow2,if=virtio',
            '-drive', f'file={directory / "seed.iso"},media=cdrom,readonly=on',
            '-netdev', 'user,id=net0,hostfwd=tcp:127.0.0.1:17322-:22', '-device', 'virtio-net-pci,netdev=net0',
            '-display', 'none', '-serial', f'file:{directory / "guest-serial.log"}']


def cloud_config(public_key):
    if '\n' in public_key or not public_key.startswith(('ssh-ed25519 ', 'ssh-rsa ')):
        raise ValueError('SSH 公钥无效')
    return '#cloud-config\n' + json.dumps({
        'hostname': VM_NAME, 'users': [{'name': 'haybot', 'groups': ['sudo'], 'sudo': 'ALL=(ALL) NOPASSWD:ALL', 'shell': '/bin/bash', 'lock_passwd': True, 'ssh_authorized_keys': [public_key]}],
        'ssh_pwauth': False, 'disable_root': True,
        'runcmd': [['bash', '-ceu', GUEST_INSTALL]],
    })


def write_environment(directory, backend):
    directory = Path(directory); directory.mkdir(parents=True, exist_ok=True)
    key = directory / 'token'
    token = key.read_text().strip() if key.exists() else secrets.token_urlsafe(48)
    if len(token) < 32: raise ValueError('运行时 Token 无效')
    key.write_text(token); key.chmod(0o600)
    path = directory / 'haybot.env'
    path.write_text(f'ANDROID_RUNTIME_URL=http://host.docker.internal:{PORT}\nANDROID_RUNTIME_TOKEN={token}\n')
    path.chmod(0o600)
    return token


def download(url, destination, digest):
    destination = Path(destination)
    if destination.exists() and hashlib.sha256(destination.read_bytes()).hexdigest() == digest: return
    tmp = destination.with_suffix('.download')
    print('下载项目运行时镜像：', url, flush=True)
    urllib.request.urlretrieve(url, tmp)
    if hashlib.sha256(tmp.read_bytes()).hexdigest() != digest:
        tmp.unlink(); raise RuntimeError('镜像校验和不匹配')
    tmp.replace(destination)


def setup_windows(directory):
    directory = Path(directory)
    for program in ['qemu-system-x86_64', 'qemu-img', 'ssh', 'ssh-keygen']:
        if not shutil.which(program): raise RuntimeError(f'请先安装并加入 PATH：{program}；同时启用 Windows Hypervisor Platform')
    # Fixed Ubuntu LTS cloud image and SHA256, not an arbitrary user URL.
    base = directory / 'ubuntu-24.04-amd64.img'
    download('https://cloud-images.ubuntu.com/releases/noble/release-20260926/ubuntu-24.04-server-cloudimg-amd64.img', base, '6a81c37564db9b1ee84e141922625e1d7c5b389b99bb3c572e0243607d5bb4d2')
    disk = directory / 'guest.qcow2'
    if not disk.exists(): subprocess.run(['qemu-img', 'create', '-f', 'qcow2', '-F', 'qcow2', '-b', str(base), str(disk), '40G'], check=True)
    key = directory / 'id_ed25519'
    if not key.exists(): subprocess.run(['ssh-keygen', '-t', 'ed25519', '-N', '', '-f', str(key)], check=True)
    from io import BytesIO
    import pycdlib
    iso = pycdlib.PyCdlib(); iso.new(interchange_level=3, joliet=3, vol_ident='cidata')
    data = {'user-data': cloud_config(key.with_suffix('.pub').read_text().strip()), 'meta-data': json.dumps({'instance-id': 'haybot-android-v1', 'local-hostname': VM_NAME})}
    for name, value in data.items():
        content = value.encode(); iso.add_fp(BytesIO(content), len(content), iso_path='/' + name.replace('-', '_').upper() + ';1', joliet_path='/' + name)
    iso.write(str(directory / 'seed.iso')); iso.close()
    config = f'Host haybot-android\n HostName 127.0.0.1\n Port 17322\n User haybot\n IdentityFile "{key.as_posix()}"\n IdentitiesOnly yes\n StrictHostKeyChecking accept-new\n UserKnownHostsFile "{(directory / "known_hosts").as_posix()}"\n ConnectTimeout 10\n'
    (directory / 'ssh_config').write_text(config)


def ensure_python(root, directory):
    directory = Path(directory)
    python = directory / 'venv' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    if not python.exists():
        subprocess.run([sys.executable, '-m', 'venv', str(directory / 'venv')], check=True)
        subprocess.run([str(python), '-m', 'pip', 'install', '-r', str(root / 'android_runtime/requirements.txt')], check=True)
    return python


def setup(root, directory):
    system = platform.system()
    if system == 'Darwin':
        if not shutil.which('limactl'): raise RuntimeError('请先安装 Lima：brew install lima')
        subprocess.run(['limactl', 'start', '--tty=false', '--name=' + VM_NAME, str(root / 'android_runtime/lima.yaml')], check=True)
        backend = 'lima'
    elif system == 'Linux':
        if not shutil.which('docker'): raise RuntimeError('请先安装 Docker')
        subprocess.run(['sudo', 'bash', '-ceu', GUEST_INSTALL], check=True)
        backend = 'docker'
    elif system == 'Windows':
        python = ensure_python(root, directory)
        env = dict(os.environ, PYTHONPATH=str(root))
        subprocess.run([str(python), '-c', 'import sys; from android_runtime.bootstrap import setup_windows; setup_windows(sys.argv[1])', str(directory)], env=env, check=True)
        backend = 'ssh'
    else: raise RuntimeError('仅支持 Linux、macOS 和 Windows x64')
    write_environment(directory, backend)
    print('运行底座已准备。Windows/Linux 尚需在对应实机验收；执行 start 启动管理器。')


def manager_bind(system=None):
    if (system or platform.system()) != 'Linux':
        return '127.0.0.1'
    import ipaddress
    raw = subprocess.check_output(['docker', 'network', 'inspect', 'bridge', '--format', '{{(index .IPAM.Config 0).Gateway}}']).decode().strip()
    address = ipaddress.ip_address(raw)
    if not address.is_private or address.is_unspecified or address.is_loopback:
        raise RuntimeError('Docker bridge 网关无效，拒绝监听公共接口')
    return str(address)


def start(root, directory):
    directory = Path(directory)
    backend = {'Darwin': 'lima', 'Linux': 'docker', 'Windows': 'ssh'}.get(platform.system())
    if not backend: raise RuntimeError('不支持的系统')
    token = write_environment(directory, backend)
    bind = manager_bind()
    (directory / 'listen-host').write_text(bind)
    # Refuse to create two managers against one inventory.
    try:
        req = urllib.request.Request(f'http://{bind}:{PORT}/health', headers={'Authorization': 'Bearer ' + token})
        with urllib.request.urlopen(req, timeout=3) as r:
            if r.status == 200: print('安卓管理器已在运行'); return
    except Exception: pass
    if backend == 'lima': subprocess.run(['limactl', 'start', '--tty=false', VM_NAME], check=True)
    if backend == 'ssh':
        pidfile = directory / 'guest.pid'
        running = False
        if pidfile.exists():
            try: os.kill(int(pidfile.read_text()), 0); running = True
            except (OSError, ValueError): pass
        if not running:
            proc = subprocess.Popen(qemu_arguments(directory), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=open(directory / 'guest.log', 'ab'), creationflags=getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0))
            pidfile.write_text(str(proc.pid))
    env = dict(os.environ, HAYBOT_ANDROID_TOKEN=token, HAYBOT_ANDROID_DATA=str(directory), HAYBOT_ANDROID_BACKEND=backend, HAYBOT_ANDROID_SSH_CONFIG=str(directory / 'ssh_config'))
    env['PYTHONPATH'] = str(root)
    log = open(directory / 'manager.log', 'ab')
    python = ensure_python(root, directory)
    proc = subprocess.Popen([str(python), '-m', 'uvicorn', 'android_runtime.service:app', '--host', bind, '--port', str(PORT)], cwd=str(root), env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=os.name != 'nt', creationflags=getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0))
    (directory / 'manager.pid').write_text(str(proc.pid))
    print('管理器启动中，日志：', directory / 'manager.log')
    print('在 HayBot .env 中加入以下文件中的连接配置，然后 docker compose up -d --no-deps app：', directory / 'haybot.env')
