"""Approved companion apps; downloads never accept model-provided URLs or packages."""
from __future__ import annotations
import asyncio
import hashlib
import json
import os
import re
from pathlib import Path
from .engine import RuntimeFailure

APPS = {
    'defaults': {'name':'中国大陆系统默认设置','package':'cn.haybot.wallpaper','url':'','page':''},
    'wallpaper': {'name':'HayBot 默认壁纸','package':'cn.haybot.wallpaper','url':'','page':''},
    'coolapk': {'name':'酷安','package':'com.coolapk.market','url':'https://dl.coolapk.com/down?pn=com.coolapk.market&id=NDU5OQ&h=46bb9d98&from=from-web','page':'https://www.coolapk.com/'},
    'douyin': {'name':'抖音','package':'com.ss.android.ugc.aweme','packages':['com.ss.android.ugc.aweme','com.ss.android.ugc.aweme.mobile'],'url':'https://lf-douyin-pc-web.douyinstatic.com/obj/douyin-pc-web/android-32.2.6/douyin.apk','page':'https://www.douyin.com/downloadpage/app'},
    'bilibili': {'name':'bilibili','package':'tv.danmaku.bili','url':'https://dl.hdslb.com/mobile/latest/android64/iBiliPlayer-bili.apk','page':'https://app.bilibili.com/'},
    'xiaohongshu': {'name':'小红书','package':'com.xingin.xhs','url':'','page':'https://oia.xiaohongshu.com/oia'},
    'chrome': {'name':'Chrome','package':'com.android.chrome','url':'','page':'https://play.google.com/store/apps/details?id=com.android.chrome'},
    'playstore': {'name':'Google Play Store','package':'com.android.vending','url':'','page':'https://support.google.com/googleplay/answer/1727131'},
}
GMS = ('com.google.android.gsf','com.google.android.gms','com.android.vending')


def parse_badging(text, app, abi):
    expected = APPS[app]['package']
    found = re.search(r"^package: name='([^']+)'[^\n]*versionName='([^']*)'", text, re.M)
    if not found or found[1] not in APPS[app].get('packages',[expected]): raise RuntimeFailure('安装包包名不匹配，未安装')
    native = re.search(r'^native-code:\s*(.*)',text,re.M)
    abis = re.findall(r"'([^']+)'",native[1]) if native else []
    if abis and abi not in abis: raise RuntimeFailure('安装包不支持当前设备架构 '+abi)
    return {'package':found[1], 'version':found[2], 'abis':abis}


async def provision(engine, bot_id, device_id, app):
    if app not in APPS: raise RuntimeFailure('未知应用')
    async with engine.lock(device_id):
        engine.get(bot_id,device_id);engine.check_lease(device_id,'');engine.require_automation(device_id)
        serial=await engine.serial(device_id)
        package=APPS[app]['package']
        installed=await engine.command('adb','-s',serial,'shell','pm','list','packages')
        prior=engine.db.execute('SELECT state FROM provisioned WHERE device_id=? AND app=?',(device_id,app)).fetchone()
        if any(('package:'+p) in installed.decode().splitlines() for p in APPS[app].get('packages',[package])) and (app not in ('wallpaper','defaults') or prior and prior['state']=='installed'):
            return save(engine,device_id,app,'existing','已安装，保留现有版本和数据')
        root=engine.root/'packages';root.mkdir(exist_ok=True)
        local=root/(app+'.apk')
        if app in ('wallpaper','defaults'): local=Path(__file__).parent/'assets'/'haybot-wallpaper.apk'
        if not local.exists():
            url=APPS[app]['url']
            if not url:
                detail='请通过酷安或 Play Store 安装；也可在宿主 packages 目录导入对应官方 APK'
                if app=='playstore':detail='当前系统未配套 GMS。需部署兼容的 GMS 系统镜像，再由 owner 登录；不自动拼装 Google 服务包'
                return save(engine,device_id,app,'needs_install',detail)
            save(engine,device_id,app,'downloading','正在下载官方安装包')
            partial=local.with_suffix('.part')
            args=['curl','--fail','--location','--proto','=https','--proto-redir','=https','--max-time','600','--max-filesize',str(600*1024*1024),'--output',str(partial),'--silent','--show-error','--user-agent','Mozilla/5.0 (Linux; Android 12)','--referer',APPS[app]['page'],url]
            proxy=os.getenv('HAYBOT_ANDROID_DOWNLOAD_PROXY','')
            if proxy:args[1:1]=['--proxy',proxy]
            proc=await asyncio.create_subprocess_exec(*args,stdout=asyncio.subprocess.DEVNULL,stderr=asyncio.subprocess.PIPE)
            try:
                _,err=await proc.communicate()
                if proc.returncode:raise RuntimeFailure('官方安装包下载失败，请检查网络或更新酷安下载入口')
                if not partial.exists() or partial.stat().st_size<1024:raise RuntimeFailure('下载内容不是有效安装包')
                partial.replace(local)
            except BaseException:
                if proc.returncode is None:proc.kill();await proc.communicate()
                partial.unlink(missing_ok=True);raise
        save(engine,device_id,app,'installing','正在核对包名、架构及签名')
        digest=hashlib.sha256(local.read_bytes()).hexdigest()
        remote='/tmp/haybot-android-assets/'+digest+'.apk'
        await engine.command('mkdir','-p','/tmp/haybot-android-assets')
        await engine.command.copy(local,remote)
        actual=(await engine.command('sha256sum',remote)).decode().split()[0]
        if actual!=digest:raise RuntimeFailure('安装包传输校验失败')
        signature=await engine.command('apksigner','verify',remote,timeout=60)
        abi=(await engine.command('adb','-s',serial,'shell','getprop','ro.product.cpu.abi')).decode().strip()
        metadata=parse_badging((await engine.command('aapt','dump','badging',remote)).decode(),app,abi)
        engine.require_automation(device_id);engine.check_lease(device_id,'')
        output=await engine.command('adb','-s',serial,'install','-r',remote,timeout=180)
        if b'Success' not in output:raise RuntimeFailure('Android 未确认安装成功；保留原应用数据')
        if app=='defaults':
            engine.require_automation(device_id)
            await engine.command('adb','-s',serial,'push',remote,'/data/local/tmp/haybot-defaults.apk')
            await engine.command('adb','-s',serial,'shell','settings','put','global','auto_time_zone','0')
            result=await engine.command('adb','-s',serial,'shell','su','0','/system/bin/app_process','-Djava.class.path=/data/local/tmp/haybot-defaults.apk','/system/bin','cn.haybot.wallpaper.Defaults')
            if b'HAYBOT_DEFAULTS_OK zh-CN CN Asia/Shanghai' not in result:raise RuntimeFailure('系统语言、地区或时区未通过核对')
            return save(engine,device_id,app,'installed','已核对：简体中文（中国大陆） · 中国 · 上海时区',metadata|{'locale':'zh-CN','region':'CN','timezone':'Asia/Shanghai'})
        if app=='wallpaper':
            engine.require_automation(device_id)
            import uuid
            receipt=uuid.uuid4().hex
            await engine.command('adb','-s',serial,'shell','am','start','-W','-n','cn.haybot.wallpaper/.MainActivity','--es','receipt',receipt)
            confirmed=(await engine.command('adb','-s',serial,'shell','cat','/sdcard/Android/data/cn.haybot.wallpaper/files/applied')).decode().strip()
            if confirmed!=receipt:raise RuntimeFailure('壁纸应用未返回成功确认，未标记已完成')
        return save(engine,device_id,app,'installed','已安装；账号登录由 owner 完成',metadata|{'sha256':digest})


def save(engine,device_id,app,state,detail,metadata=None):
    item={'app':app,'state':state,'detail':detail,'metadata':metadata or {}}
    with engine.db:engine.db.execute('INSERT OR REPLACE INTO provisioned VALUES (?,?,?,?)',(device_id,app,state,json.dumps(item,ensure_ascii=False)))
    return item


async def status(engine,bot_id,device_id,refresh=True):
    engine.get(bot_id,device_id)
    saved={r['app']:json.loads(r['data']) for r in engine.db.execute('SELECT * FROM provisioned WHERE device_id=?',(device_id,))}
    installed=set()
    try:
        if not refresh:raise RuntimeFailure('busy')
        async with engine.lock(device_id):
            serial=await engine.serial(device_id)
            raw=(await engine.command('adb','-s',serial,'shell','pm','list','packages')).decode()
            installed={line.removeprefix('package:').strip() for line in raw.splitlines()}
    except RuntimeFailure: pass
    items=[]
    for key,value in APPS.items():
        item={'id':key,**value,**saved.get(key,{'state':'not_checked','detail':'尚未安装或检查'})}
        if key not in ('defaults','wallpaper') and any(p in installed for p in value.get('packages',[value['package']])):
            item.update(state='installed',detail='已安装；登录由 owner 自行完成')
        if key=='playstore':
            missing=[p for p in GMS if p not in installed]
            item['missing_services']=missing
            if missing:item.update(state='needs_gms',detail='缺少配套 Google 服务；需兼容的 GMS 系统镜像，不能仅安装商店 APK')
        items.append(item)
    return {'apps':items}

