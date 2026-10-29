"""Local launcher: diagnose Node before attempting to run a Node service."""
from pathlib import Path
import os
import re
import shutil
import subprocess
import sys
import urllib.request
import webbrowser

ROOT = Path(__file__).resolve().parent.parent
DOWNLOAD = 'https://nodejs.org/en/download'


def node_status():
    # Finder does not inherit a user's interactive PATH.
    candidates = [shutil.which('node'), '/usr/local/bin/node', '/opt/homebrew/bin/node']
    for candidate in dict.fromkeys(c for c in candidates if c):
        try:
            result = subprocess.run([candidate, '--version'], capture_output=True, text=True, timeout=10)
            match = re.fullmatch(r'v(\d+)\.\d+\.\d+\s*', result.stdout)
            if result.returncode == 0 and match and int(match[1]) >= 22:
                return candidate, result.stdout.strip()
        except (OSError, subprocess.TimeoutExpired):
            pass
    return None, None


def running(directory):
    try:
        token = (directory / 'token').read_text().strip()
        request = urllib.request.Request('http://127.0.0.1:17322/api/health', headers={'Authorization': 'Bearer ' + token})
        with urllib.request.urlopen(request, timeout=3) as response:
            return response.status == 200
    except (OSError, ValueError):
        return False


def main():
    if sys.platform != 'darwin':
        print('当前浏览器运行时只完成了 macOS 支持，暂不能在此系统启动。')
        return 1
    node, version = node_status()
    while not node:
        print('\n需要先安装 Node.js（22.x 或更新的 LTS）。')
        print('即将打开官方页面：选择 macOS 安装器 .pkg，双击安装并按提示完成。')
        print('安装完成后回到这个窗口，按回车重新检测；输入 q 可退出。')
        webbrowser.open(DOWNLOAD)
        if input('安装后按回车继续：').strip().lower() == 'q':
            return 0
        node, version = node_status()
    print(f'✓ Node.js {version}')
    directory = ROOT / '.browser-runtime'
    if running(directory):
        print('✓ 浏览器服务已经运行。返回后台，点击“重新检测”即可。')
        return 0
    env = dict(os.environ, PATH=str(Path(node).parent) + os.pathsep + os.environ.get('PATH', ''))
    runtime = ROOT / 'browser_runtime'
    if not (runtime / 'node_modules/playwright/package.json').exists() or not (runtime / 'node_modules/ws/package.json').exists():
        npm = shutil.which('npm', path=env['PATH'])
        if not npm:
            print('未找到 npm。请使用 Node.js 官方 .pkg 安装器重新安装（保留 npm 选项）。')
            webbrowser.open(DOWNLOAD)
            return 1
        print('正在准备浏览器依赖，首次启动需要联网，请稍候…')
        if subprocess.run([npm, 'ci', '--ignore-scripts'], cwd=runtime, env=env).returncode:
            print('依赖下载失败。请检查网络后重新打开启动入口。')
            return 1
    print('正在启动浏览器服务。请保留本窗口；按 Control+C 可以停止。')
    print('启动后返回后台点击“重新检测”。缺少 Chrome 时后台会提供安装入口。')
    try:
        return subprocess.call([node, 'src/server.mjs'], cwd=runtime, env=env)
    except KeyboardInterrupt:
        return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, EOFError) as error:
        print(f'启动未完成：{error}')
        raise SystemExit(1)
