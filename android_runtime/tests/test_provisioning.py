import pytest
from android_runtime.engine import AndroidEngine, DeviceCreate, RuntimeFailure
from android_runtime.provisioning import APPS, parse_badging
from test_engine import Guest


def test_apk_identity_abi_and_wrong_package():
    data="package: name='tv.danmaku.bili' versionCode='123' versionName='8.0'\nnative-code: 'arm64-v8a'\n"
    assert parse_badging(data,'bilibili','arm64-v8a')['version']=='8.0'
    with pytest.raises(RuntimeFailure):parse_badging(data,'douyin','arm64-v8a')
    with pytest.raises(RuntimeFailure):parse_badging(data,'bilibili','x86_64')
    assert set(APPS)=={'douyin','bilibili','xiaohongshu','chrome','wallpaper','coolapk','playstore','defaults'}

@pytest.mark.asyncio
async def test_provision_scopes_and_preserves_installed_app(tmp_path):
    class Installed(Guest):
        async def __call__(self,*args,**kwargs):
            if 'pm' in args and 'list' in args:return b'package:tv.danmaku.bili\n'
            return await super().__call__(*args,**kwargs)
    engine=AndroidEngine(tmp_path,Installed());d=await engine.create('a',DeviceCreate(name='phone'))
    await engine.start('a',d['id'])
    with pytest.raises(RuntimeFailure):await engine.provision('other',d['id'],'bilibili')
    result=await engine.provision('a',d['id'],'bilibili')
    assert result['state']=='existing'
    await engine.login('a',d['id'],True)
    with pytest.raises(RuntimeFailure):await engine.provision('a',d['id'],'douyin')
    engine.close()
