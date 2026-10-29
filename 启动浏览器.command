#!/bin/zsh
cd -- "${0:A:h}" || exit 1
if ! command -v python3 >/dev/null 2>&1; then
  print '需要先安装 Python 3。即将打开官方安装页面，安装完成后重新双击此入口。'
  open 'https://www.python.org/downloads/macos/'
else
  python3 scripts/browser_runtime.py
fi
print '\n按回车关闭窗口。'
read
