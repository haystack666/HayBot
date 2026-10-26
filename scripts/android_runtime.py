#!/usr/bin/env python3
"""Run from the deployment host, not from inside the HayBot app container."""
import argparse
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from android_runtime import bootstrap

parser = argparse.ArgumentParser(description='HayBot 项目专用安卓运行时')
parser.add_argument('command', choices=['setup', 'start', 'status', 'stop'])
parser.add_argument('--directory', default=str(ROOT / '.android-runtime'))
args = parser.parse_args(); directory = Path(args.directory).resolve(); directory.mkdir(parents=True, exist_ok=True)
try:
    if args.command == 'setup': bootstrap.setup(ROOT, directory)
    elif args.command == 'start': bootstrap.start(ROOT, directory)
    elif args.command == 'status':
        import urllib.request
        token = (directory / 'token').read_text().strip()
        bind = (directory / 'listen-host').read_text().strip() if (directory / 'listen-host').exists() else '127.0.0.1'
        request = urllib.request.Request(f'http://{bind}:{bootstrap.PORT}/health', headers={'Authorization': 'Bearer ' + token})
        with urllib.request.urlopen(request, timeout=20) as response: print(response.read().decode())
    elif args.command == 'stop':
        import signal
        pidfile = directory / 'manager.pid'
        if pidfile.exists(): os.kill(int(pidfile.read_text()), signal.SIGTERM); pidfile.unlink()
        print('管理器已停止，安卓设备和数据保留。虚拟机可通过 limactl stop haybot-android 停止。')
except Exception as exc:
    print('安卓运行时：' + str(exc), file=sys.stderr); sys.exit(1)
