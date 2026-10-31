"""Keep the macOS browser runtime running while this project's app container runs."""
import argparse
import os
from pathlib import Path
import plistlib
import shutil
import signal
import subprocess
import sys
import time

from browser_runtime import ROOT, node_status, running

LABEL = 'local.haybot.browser-runtime'


def app_running(docker):
    result = subprocess.run(
        [docker, 'ps', '-q', '--filter', 'label=com.docker.compose.service=app',
         '--filter', 'label=com.docker.compose.project.working_dir=' + str(ROOT)],
        capture_output=True, text=True, timeout=10,
    )
    # A Docker connection failure is unknown, rather than a confirmed container stop.
    if result.returncode:
        raise OSError('Docker 暂不可用')
    return bool(result.stdout.strip())


def stop_child(child):
    if child is None or child.poll() is not None:
        return
    child.terminate()
    try:
        child.wait(timeout=20)
    except subprocess.TimeoutExpired:
        child.kill()
        child.wait()


def supervise(docker, node):
    stopping = False
    child = None

    def stop(_signal, _frame):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        while not stopping:
            try:
                active = app_running(docker)
            except (OSError, subprocess.TimeoutExpired):
                active = None
            if child is not None and child.poll() is not None:
                print('浏览器运行时已退出，将在容器运行时重新启动。', flush=True)
                child = None
            if active is True and child is None and not running(ROOT / '.browser-runtime'):
                print('应用容器正在运行，启动宿主浏览器服务。', flush=True)
                child = subprocess.Popen([node, 'src/server.mjs'], cwd=ROOT / 'browser_runtime')
            elif active is False and child is not None:
                print('应用容器已停止，关闭宿主浏览器服务。', flush=True)
                stop_child(child)
                child = None
            for _ in range(5):
                if stopping:
                    break
                time.sleep(1)
    finally:
        stop_child(child)


def install():
    if sys.platform != 'darwin':
        raise SystemExit('自动启动服务仅支持 macOS。')
    docker = shutil.which('docker') or str(Path.home() / '.docker/bin/docker')
    node, _ = node_status()
    if not Path(docker).is_file() or not node:
        raise SystemExit('请先安装 Docker Desktop 和 Node.js 22 或更新版本。')
    for dependency in ('playwright', 'ws'):
        if not (ROOT / 'browser_runtime/node_modules' / dependency / 'package.json').exists():
            raise SystemExit('请先运行 npm --prefix browser_runtime ci --ignore-scripts')
    directory = ROOT / '.browser-runtime'
    directory.mkdir(mode=0o700, exist_ok=True)
    agents = Path.home() / 'Library/LaunchAgents'
    agents.mkdir(parents=True, exist_ok=True)
    target = agents / (LABEL + '.plist')
    logs = Path.home() / 'Library/Logs/HayBot'
    logs.mkdir(parents=True, exist_ok=True)
    config = {
        'Label': LABEL,
        'ProgramArguments': [sys.executable, str(Path(__file__).resolve()),
                             '--docker', docker, '--node', node],
        'WorkingDirectory': str(Path.home()),
        'RunAtLoad': True,
        'KeepAlive': True,
        'ThrottleInterval': 10,
        'StandardOutPath': str(logs / 'browser-runtime.log'),
        'StandardErrorPath': str(logs / 'browser-runtime-error.log'),
    }
    domain = 'gui/' + str(os.getuid())
    subprocess.run(['launchctl', 'bootout', domain + '/' + LABEL], capture_output=True)
    with target.open('wb') as stream:
        plistlib.dump(config, stream)
    target.chmod(0o600)
    subprocess.run(['launchctl', 'bootstrap', domain, str(target)], check=True)
    print('已安装宿主守护程序：' + str(target))
    print('登录 macOS 后自动运行，每 5 秒检测本项目应用容器并跟随启停。')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--install', action='store_true')
    parser.add_argument('--docker')
    parser.add_argument('--node')
    args = parser.parse_args()
    if args.install:
        install()
    elif args.docker and args.node:
        supervise(args.docker, args.node)
    else:
        parser.error('使用 --install 安装，或指定 --docker 和 --node 运行')
