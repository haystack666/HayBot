"""Optional local Android 12 ARM64 Google bundle build, never distributed with HayBot.
Downloads are pinned to upstream commit and SHA-256, with APK signature checks.
"""
from __future__ import annotations
import asyncio
import hashlib
import json
import os
import platform
import re
import tarfile
from pathlib import Path,PurePosixPath
from .engine import GuestCommand,RuntimeFailure


def validate_manifest(value):
    if value.get('upstream')!='https://gitlab.com/MindTheGapps/vendor_gapps' or not re.fullmatch('[0-9a-f]{40}',value.get('commit','')):raise ValueError('Google 配套来源必须固定到上游提交')
    if value.get('architecture')!='arm64' or value.get('android_version')!='12':raise ValueError('此清单仅适用于 Android 12 ARM64')
    if not re.fullmatch(r'redroid/redroid@sha256:[0-9a-f]{64}',value.get('base_image','')):raise ValueError('基础镜像必须固定到已验收的摘要')
    files=value.get('files',[])
    if not 3<=len(files)<=100:raise ValueError('Google 配套文件清单无效')
    for item in files:
        for key in ('source','target'):
            path=PurePosixPath(item.get(key,''))
            if not path.parts or path.is_absolute() or '..' in path.parts or not re.fullmatch(r'[A-Za-z0-9_./-]+',str(path)):raise ValueError('Google 配套文件路径无效')
        if not item['source'].startswith(('arm64/proprietary/','common/proprietary/')) or not item['target'].startswith(('product/','system_ext/')):raise ValueError('Google 配套文件分区无效')
        if not re.fullmatch('[0-9a-f]{64}',item.get('sha256','')):raise ValueError('Google 配套文件缺少 SHA-256')
    return value


def valid_file(path,digest):
    path=Path(path)
    if not path.is_file():return False
    sha=hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):sha.update(chunk)
    return sha.hexdigest()==digest


async def build(directory,command=None,proxy='',manifest=None):
    value=validate_manifest(manifest or json.loads((Path(__file__).parent/'gapps_manifest.json').read_text()))
    mode={'Darwin':'lima','Linux':'docker','Windows':'ssh'}.get(platform.system())
    command=command or GuestCommand(os.getenv('HAYBOT_ANDROID_BACKEND',mode),ssh_config=Path(directory)/'ssh_config')
    info=json.loads(await command('docker','info','--format','{{json .}}'))
    if info.get('Architecture') not in ('aarch64','arm64'):raise RuntimeFailure('此 Google 配套仅验收 ARM64；x86_64 需要独立的兼容清单，未修改任何手机')
    root=Path(directory)/'gapps-build';root.mkdir(parents=True,exist_ok=True)
    for item in value['files']:
        out=root/'rootfs'/item['target'];out.parent.mkdir(parents=True,exist_ok=True)
        if valid_file(out,item['sha256']):continue
        partial=out.with_suffix(out.suffix+'.part')
        url=value['upstream']+'/-/raw/'+value['commit']+'/'+item['source']
        args=['curl','--fail','--location','--proto','=https','--proto-redir','=https','--max-time','300','--max-filesize',str(200*1024*1024),'--silent','--show-error','--output',str(partial),url]
        if proxy:args[1:1]=['--proxy',proxy]
        process=await asyncio.create_subprocess_exec(*args,stdout=asyncio.subprocess.DEVNULL,stderr=asyncio.subprocess.PIPE)
        try:
            _,err=await process.communicate()
            if process.returncode or not valid_file(partial,item['sha256']):raise RuntimeFailure('上游下载失败或 SHA-256 不符：'+Path(item['target']).name)
            partial.replace(out)
        except BaseException:
            if process.returncode is None:process.kill();await process.communicate()
            partial.unlink(missing_ok=True);raise
    (root/'Dockerfile').write_text('FROM '+value['base_image']+'\nCOPY rootfs/product /system/product\nCOPY rootfs/system_ext /system/system_ext\nENTRYPOINT ["/init","qemu=1","androidboot.hardware=redroid","ro.setupwizard.mode=DISABLED"]\n')
    archive=root/'context.tar'
    with tarfile.open(archive,'w') as bundle:
        bundle.add(root/'Dockerfile',arcname='Dockerfile')
        # Only the verified manifest files enter the privileged image.
        for item in value['files']:bundle.add(root/'rootfs'/item['target'],arcname='rootfs/'+item['target'])
    remote='/tmp/haybot-gapps-'+value['commit'][:12]
    await command('mkdir','-p',remote);await command.copy(archive,remote+'/context.tar')
    await command('tar','-xf',remote+'/context.tar','-C',remote)
    for item in value['files']:
        if item['target'].endswith('.apk'):await command('apksigner','verify',remote+'/rootfs/'+item['target'],timeout=60)
    await command('docker','build','--pull=false','-t','haybot/redroid12-gapps:local',remote,timeout=600)
    image_info=json.loads(await command('docker','image','inspect','haybot/redroid12-gapps:local'))
    image_id=image_info[0]['Id']
    (root/'receipt.json').write_text(json.dumps({'base_image':value['base_image'],'image_id':image_id,'commit':value['commit'],'architecture':'arm64','image':'haybot/redroid12-gapps:local','files':len(value['files'])}))
    return {'image':'haybot/redroid12-gapps:local','upstream_commit':value['commit'],'architecture':'arm64','note':'只构建本地镜像；现有手机尚未切换，登录由 owner 完成'}
