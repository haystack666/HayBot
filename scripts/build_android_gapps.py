#!/usr/bin/env python3
"""Build the optional Google Play system bundle on the dedicated Android host."""
import argparse,asyncio,json,os,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from android_runtime.gapps import build
parser=argparse.ArgumentParser(description='构建 Android 12 ARM64 的本地 Google Play 配套，不操作现有手机')
parser.add_argument('--directory',default=str(ROOT/'.android-runtime'))
parser.add_argument('--proxy',default=os.getenv('HAYBOT_ANDROID_DOWNLOAD_PROXY',''))
args=parser.parse_args()
try:print(json.dumps(asyncio.run(build(args.directory,proxy=args.proxy)),ensure_ascii=False))
except Exception as exc:print('Google 配套构建失败：'+str(exc),file=sys.stderr);sys.exit(1)
