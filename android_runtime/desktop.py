"""Reversible Via-only workspace for the bundled AOSP Launcher3."""
from __future__ import annotations
import asyncio
import hashlib
import json
import re
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path
from .engine import RuntimeFailure
from .provisioning import save

OVERLAY = 'com.android.shell:HayBotMinimalHome'


async def arrange(engine, bot_id, device_id, automatic=False):
    async with engine.lock(device_id):
        engine.get(bot_id, device_id); engine.check_lease(device_id, ''); engine.require_automation(device_id)
        prior = engine.db.execute('SELECT state FROM provisioned WHERE device_id=? AND app=?', (device_id, 'desktop')).fetchone()
        if automatic and prior and prior['state'] == 'installed':
            return {'state': 'existing', 'detail': '已整理过桌面，保留后续手动调整'}
        receipt = uuid.uuid4().hex; backed_up = False; original_overlay = False; stopped = False
        serial = await engine.serial(device_id)
        async def shell(*args):
            return await engine.command('adb', '-s', serial, 'shell', *args)
        try:
            home = (await shell('cmd','package','resolve-activity','--brief','-a','android.intent.action.MAIN','-c','android.intent.category.HOME')).decode()
            if 'com.android.launcher3/' not in home: raise RuntimeFailure('当前桌面不是系统 Launcher3，未修改布局')
            raw = (await shell('cmd','package','resolve-activity','--brief','mark.via')).decode()
            component = next((line.strip() for line in raw.splitlines() if re.fullmatch(r'mark\.via/[A-Za-z0-9_.$]+',line.strip())), '')
            if not component: raise RuntimeFailure('请先安装 Via 浏览器再整理桌面')
            helper = Path(__file__).parent/'assets'/'haybot-wallpaper.apk'
            digest = hashlib.sha256(helper.read_bytes()).hexdigest()
            remote = '/tmp/haybot-android-assets/'+digest+'.apk'
            await engine.command('mkdir','-p','/tmp/haybot-android-assets')
            await engine.command.copy(helper, remote)
            actual = (await engine.command('sha256sum',remote)).decode().split()[0]
            if actual != digest: raise RuntimeFailure('桌面工具传输校验失败')
            # Execute the local helper without installing an additional app.
            await engine.command('adb','-s',serial,'push',remote,'/data/local/tmp/haybot-desktop.apk')
            async def helper_call(mode, *args):
                return (await shell('su','0','/system/bin/app_process','-Djava.class.path=/data/local/tmp/haybot-desktop.apk','/system/bin','cn.haybot.wallpaper.Desktop',mode,*args)).decode()
            probe = await helper_call('probe')
            ids = json.loads(probe.split('HAYBOT_DESKTOP ',1)[1].strip())
            if not all(type(ids.get(key)) is int and ids[key] > 0 for key in ('workspace','empty')): raise RuntimeFailure('无法确认系统桌面资源，未修改布局')
            overlays = (await shell('cmd','overlay','list','--user','0','com.android.launcher3')).decode()
            original_overlay = '[x] '+OVERLAY in overlays
            engine.check_lease(device_id,'');engine.require_automation(device_id)
            save(engine,device_id,'desktop','installing','正在备份并整理桌面')
            await shell('am','force-stop','com.android.launcher3'); stopped = True
            engine.check_lease(device_id,'');engine.require_automation(device_id)
            result = await helper_call('apply', receipt, component)
            backed_up = 'HAYBOT_DESKTOP_APPLIED ' in result
            if not backed_up: raise RuntimeFailure('桌面布局写入未返回确认')
            engine.check_lease(device_id,'');engine.require_automation(device_id)
            await shell('su','0','cmd','overlay','fabricate','--target','com.android.launcher3','--name','HayBotMinimalHome','com.android.launcher3:layout/search_container_workspace','0x01',hex(ids['empty']))
            engine.check_lease(device_id,'');engine.require_automation(device_id)
            await shell('cmd','overlay','enable','--user','0',OVERLAY)
            lookup = (await shell('cmd','overlay','lookup','--user','0','com.android.launcher3','com.android.launcher3:layout/search_container_workspace')).decode()
            if 'search_container_hotseat.xml' not in lookup: raise RuntimeFailure('固定搜索栏未隐藏')
            await shell('input','keyevent','3')
            for _ in range(8):
                engine.check_lease(device_id,'');engine.require_automation(device_id)
                tree = ET.fromstring(await engine.u2(serial,{'kind':'hierarchy'}))
                nodes = [n for n in tree.iter('node') if n.get('package')=='com.android.launcher3']
                icons = [n for n in nodes if n.get('text')]
                if len(icons)==1 and icons[0].get('text')=='Via' and not any(n.get('resource-id','').endswith('/qsb_widget') for n in nodes):
                    return save(engine,device_id,'desktop','installed','桌面仅保留 Via，固定搜索栏、其他图标和小组件已移除；上滑仍可打开应用列表',{'backup': '/data/local/tmp/haybot-desktop-backups/'+receipt, 'receipt': receipt})
                await asyncio.sleep(.4)
            raise RuntimeFailure('桌面显示未通过核对')
        except Exception as exc:
            detail = str(exc)[:300]
            if stopped and not engine.login_active(device_id):
                try:
                    await shell('am','force-stop','com.android.launcher3')
                    # apply may have failed after its backup was written.
                    await helper_call('restore',receipt)
                    if not original_overlay: await shell('cmd','overlay','disable','--user','0',OVERLAY)
                    await shell('input','keyevent','3')
                    detail += '；已恢复原桌面布局'
                except Exception:
                    await shell('input','keyevent','3')
                    detail += '；请检查桌面，原布局备份保留在手机中'
            save(engine,device_id,'desktop','failed',detail,{'receipt':receipt})
            raise RuntimeFailure(detail) from None


def status(engine, bot_id, device_id):
    engine.get(bot_id,device_id)
    row = engine.db.execute('SELECT data FROM provisioned WHERE device_id=? AND app=?',(device_id,'desktop')).fetchone()
    return json.loads(row['data']) if row else {'state':'not_checked','detail':'可移除桌面图标和小组件，仅保留 Via；会先备份当前布局'}
