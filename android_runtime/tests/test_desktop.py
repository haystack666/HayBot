import json
import pytest
from android_runtime.engine import AndroidEngine, DeviceCreate, RuntimeFailure
from android_runtime.desktop import arrange
from android_runtime.provisioning import save
from test_engine import Guest


@pytest.mark.asyncio
async def test_desktop_respects_bot_scope_owner_login_and_task_lease(tmp_path):
    guest=Guest();e=AndroidEngine(tmp_path,guest);d=await e.create('a',DeviceCreate(name='phone'))
    try:
        with pytest.raises(RuntimeFailure):await arrange(e,'other',d['id'])
        await e.login('a',d['id'],True)
        with pytest.raises(RuntimeFailure):await arrange(e,'a',d['id'])
        await e.login('a',d['id'],False)
        e.leases[d['id']]='task'
        with pytest.raises(RuntimeFailure):await arrange(e,'a',d['id'])
        assert guest.calls==[]
    finally:e.close()


@pytest.mark.asyncio
async def test_automatic_desktop_does_not_reset_later_user_customization(tmp_path):
    guest=Guest();e=AndroidEngine(tmp_path,guest);d=await e.create('a',DeviceCreate(name='phone'))
    save(e,d['id'],'desktop','installed','already arranged')
    try:
        assert (await arrange(e,'a',d['id'],automatic=True))['state']=='existing'
        assert guest.calls==[]
    finally:e.close()


@pytest.mark.asyncio
async def test_failed_search_bar_overlay_restores_backed_up_layout(tmp_path):
    class Files(Guest):
        async def copy(self,*args):pass
        async def __call__(self,*args,**kw):
            self.calls.append(args)
            if args[0]=='sha256sum':
                from pathlib import Path
                import hashlib
                digest=hashlib.sha256(Path('android_runtime/assets/haybot-wallpaper.apk').read_bytes()).hexdigest()
                return (digest+' file').encode()
            if 'resolve-activity' in args:
                return b'com.android.launcher3/.Launcher' if 'android.intent.category.HOME' in args else b'mark.via/.Shell'
            if 'probe' in args:return b'HAYBOT_DESKTOP '+json.dumps({'workspace':123,'empty':456}).encode()
            if 'apply' in args:return b'HAYBOT_DESKTOP_APPLIED /backup'
            if 'fabricate' in args:raise RuntimeFailure('unsupported overlay')
            if 'restore' in args:return b'HAYBOT_DESKTOP_RESTORED'
            return b''
    guest=Files();e=AndroidEngine(tmp_path,guest);d=await e.create('a',DeviceCreate(name='phone'))
    async def serial(_):return 'test-serial'
    e.serial=serial
    try:
        with pytest.raises(RuntimeFailure,match='已恢复原桌面布局'):await arrange(e,'a',d['id'])
        assert any('restore' in args for args in guest.calls)
        assert not any('uninstall' in args or ('pm' in args and 'clear' in args) for args in guest.calls)
        assert e.db.execute("SELECT state FROM provisioned WHERE app='desktop'").fetchone()['state']=='failed'
    finally:e.close()
