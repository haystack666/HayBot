import pytest
from android_runtime.engine import AndroidEngine, DeviceCreate, RuntimeFailure
from android_runtime.provisioning import APPS, INITIAL_APPS, GMS, parse_badging, status
from test_engine import Guest


def test_apk_identity_abi_and_wrong_package():
    data="package: name='tv.danmaku.bili' versionCode='123' versionName='8.0'\nnative-code: 'arm64-v8a'\n"
    assert parse_badging(data,'bilibili','arm64-v8a')['version']=='8.0'
    with pytest.raises(RuntimeFailure):parse_badging(data,'douyin','arm64-v8a')
    with pytest.raises(RuntimeFailure):parse_badging(data,'bilibili','x86_64')
    assert INITIAL_APPS == ('via','playstore')
    assert APPS['via']['package']=='mark.via'
    assert parse_badging("package: name='mark.via' versionName='7.3.4'",'via','arm64-v8a')['version']=='7.3.4'

@pytest.mark.asyncio
async def test_provision_scopes_and_preserves_installed_app(tmp_path):
    class Installed(Guest):
        async def __call__(self,*args,**kwargs):
            if 'pm' in args and 'list' in args:return b'package:mark.via\n'
            return await super().__call__(*args,**kwargs)
    engine=AndroidEngine(tmp_path,Installed());d=await engine.create('a',DeviceCreate(name='phone'))
    await engine.start('a',d['id'])
    with pytest.raises(RuntimeFailure):await engine.provision('other',d['id'],'via')
    for app in ('bilibili','douyin','coolapk','chrome','xiaohongshu','wallpaper','defaults'):
        with pytest.raises(RuntimeFailure):await engine.provision('a',d['id'],app)
    result=await engine.provision('a',d['id'],'via')
    assert result['state']=='existing'
    await engine.login('a',d['id'],True)
    with pytest.raises(RuntimeFailure):await engine.provision('a',d['id'],'via')
    engine.close()


@pytest.mark.asyncio
async def test_app_status_only_lists_via_and_complete_google_suite(tmp_path):
    class Installed(Guest):
        async def __call__(self,*args,**kwargs):
            if 'pm' in args and 'list' in args:
                return ('\n'.join('package:'+p for p in ['mark.via','com.coolapk.market',*GMS])).encode()
            return await super().__call__(*args,**kwargs)
    e=AndroidEngine(tmp_path,Installed());d=await e.create('a',DeviceCreate(name='phone'));await e.start('a',d['id'])
    try:
        result=await status(e,'a',d['id'])
        assert [app['id'] for app in result['apps']]==['via','playstore']
        assert all(app['state']=='installed' for app in result['apps'])
        assert result['apps'][1]['missing_services']==[]
        result=await status(e,'a',d['id'],refresh=False)
        assert result['apps'][1]['state']=='not_checked'
    finally:e.close()


@pytest.mark.asyncio
async def test_automatic_initialization_never_installs_legacy_apps(tmp_path,monkeypatch):
    from unittest.mock import AsyncMock
    import android_runtime.desktop
    e=AndroidEngine(tmp_path,Guest());d=await e.create('a',DeviceCreate(name='phone',initialize=True))
    e.provision=AsyncMock()
    desktop=AsyncMock();monkeypatch.setattr(android_runtime.desktop,'arrange',desktop)
    try:
        await e.start('a',d['id'])
        assert [call.args[2] for call in e.provision.await_args_list]==['via']
        desktop.assert_awaited_once_with(e,'a',d['id'],automatic=True)
    finally:e.close()
