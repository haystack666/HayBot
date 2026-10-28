import asyncio
import json

import pytest

from android_runtime.engine import AndroidEngine, DeviceCreate, Action, RuntimeFailure


class Guest:
    def __init__(self):
        self.calls = []
        self.containers = {}
        self.volumes = {}

    async def __call__(self, *args, **kwargs):
        self.calls.append(args)
        if args[:3] == ('docker','image','inspect'):
            return json.dumps([{'Id':'sha256:'+'a'*64}]).encode()
        if args[:2] == ('docker', 'ps'):
            return '\n'.join(self.containers).encode()
        if args[:3] == ('docker','volume','ls'):
            return '\n'.join(self.volumes).encode()
        if args[:3] == ('docker','volume','inspect'):
            if args[-1] not in self.volumes: raise RuntimeFailure('volume missing')
            return json.dumps([self.volumes[args[-1]]]).encode()
        if args[:3] == ('docker','volume','create'):
            self.volumes[args[-1]]={'Labels': {'io.haybot.android': args[args.index('--label')+1].split('=',1)[1]}}
        if args[:3] == ('docker','volume','rm'):
            if args[-1] not in self.volumes:raise RuntimeFailure('volume missing')
            del self.volumes[args[-1]]
        if args[:2] == ('docker', 'inspect'):
            name = args[-1]
            if name not in self.containers:
                raise RuntimeFailure('not found')
            return json.dumps([self.containers[name]]).encode()
        if args[:2] == ('docker', 'run'):
            name = args[args.index('--name') + 1]
            self.containers[name] = {'Config': {'Labels': {'io.haybot.android': name.removeprefix('haybot-android-')}}, 'State': {'Running': True}, 'NetworkSettings': {'Ports': {'5555/tcp': [{'HostIp': '127.0.0.1', 'HostPort': '41321'}]}}}
            return b'container-id'
        if args[:2] == ('docker', 'stop'):
            self.containers[args[-1]]['State']['Running'] = False
        if args[:2] == ('docker', 'rm'):
            self.containers.pop(args[-1], None)
        if 'getprop' in args:
            return b'1\n'
        return b'ok'

@pytest.mark.asyncio
async def test_clipboard_returns_only_public_share_links_and_requires_lease(tmp_path):
    e=AndroidEngine(tmp_path,Guest());d=await e.create('a',DeviceCreate(name='phone'));await e.start('a',d['id'])
    lease=await e.claim('a',d['id'])
    async def clipboard(*args):return json.dumps('private text https://www.coolapk.com/feed/74612141?share=1 https://example.com/secret').encode()
    e.u2=clipboard
    try:
        assert await e.clipboard('a',d['id'],lease)=={'links':['https://www.coolapk.com/feed/74612141']}
        with pytest.raises(RuntimeFailure):await e.clipboard('a',d['id'],'wrong')
    finally:e.close()


@pytest.mark.asyncio
async def test_observation_preserves_large_xml_and_tail_security_nodes(tmp_path):
    import xml.etree.ElementTree as ET
    from app.android_companion import login_screen, target_text
    tree='<hierarchy>'+''.join('<node text="酷安内容" content-desc="'+'x'*500+'"/>' for _ in range(160))+'<node class="android.widget.EditText" password="true"/><node text="发布" bounds="[0,0][200,200]"/></hierarchy>'
    assert len(tree)>80000
    class ScreenGuest(Guest):
        async def __call__(self,*args,**kwargs):
            if 'screencap' in args:return b'\x89PNG\r\n\x1a\nimage'
            return await super().__call__(*args,**kwargs)
    e=AndroidEngine(tmp_path,ScreenGuest());d=await e.create('a',DeviceCreate(name='phone'));await e.start('a',d['id'])
    async def hierarchy(*args):return tree.encode()
    e.u2=hierarchy
    try:
        observed=await e.observe('a',d['id'])
        assert observed['hierarchy']==tree
        ET.fromstring(observed['hierarchy'])
        assert login_screen(observed['hierarchy'])
        assert target_text(observed['hierarchy'],10,10)=='发布  '
    finally:e.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('raw',[b'<hierarchy><node',b'x'*(1024*1024+1)],ids=['incomplete','oversized'])
async def test_invalid_or_oversized_tree_is_reported_without_silent_truncation(tmp_path,raw):
    class ScreenGuest(Guest):
        async def __call__(self,*args,**kwargs):
            if 'screencap' in args:return b'\x89PNG\r\n\x1a\nimage'
            return await super().__call__(*args,**kwargs)
    e=AndroidEngine(tmp_path,ScreenGuest());d=await e.create('a',DeviceCreate(name='phone'));await e.start('a',d['id'])
    async def hierarchy(*args):return raw
    e.u2=hierarchy
    try:
        with pytest.raises(RuntimeFailure,match='页面结构'):
            await e.observe('a',d['id'])
    finally:e.close()


@pytest.mark.asyncio
async def test_create_is_scoped_persistent_and_no_public_adb(tmp_path):
    guest = Guest()
    engine = AndroidEngine(tmp_path, guest)
    device = await engine.create('bot-a', DeviceCreate(name='Phone'))
    assert device['bot_id'] == 'bot-a'
    assert device['state'] == 'stopped'
    await engine.start('bot-a', device['id'])
    run = next(x for x in guest.calls if x[:2] == ('docker', 'run'))
    assert '127.0.0.1::5555' in run
    assert '--privileged' in run
    assert '--mount' in run and 'type=volume' in run[run.index('--mount') + 1]
    assert not any('/Users/' in x or 'docker.sock' in x for x in run)
    assert engine.list('bot-b') == []
    with pytest.raises(RuntimeFailure):
        await engine.stop('bot-b', device['id'])
    engine.close()
    reopened = AndroidEngine(tmp_path, guest)
    assert reopened.list('bot-a')[0]['id'] == device['id']
    reopened.close()


@pytest.mark.asyncio
async def test_retained_device_can_restart_and_destroy_requires_stopped(tmp_path):
    guest = Guest(); engine = AndroidEngine(tmp_path, guest)
    device = await engine.create('bot-a', DeviceCreate(name='Phone'))
    await engine.start('bot-a', device['id'])
    with pytest.raises(RuntimeFailure):
        await engine.delete('bot-a', device['id'], destroy_data=True)
    await engine.stop('bot-a', device['id'])
    await engine.remove_container('bot-a', device['id'])
    assert engine.list('bot-a')[0]['id'] == device['id']
    assert not any(x[:3] == ('docker', 'volume', 'rm') for x in guest.calls)
    await engine.start('bot-a', device['id'])
    await engine.stop('bot-a', device['id'])
    await engine.delete('bot-a', device['id'], destroy_data=True)
    assert engine.list('bot-a') == []
    assert any(x[:3] == ('docker', 'volume', 'rm') for x in guest.calls)
    engine.close()


@pytest.mark.asyncio
async def test_lease_blocks_manual_action_until_takeover_and_fences_old_task(tmp_path):
    guest = Guest(); engine = AndroidEngine(tmp_path, guest)
    d = await engine.create('a', DeviceCreate(name='Phone'))
    await engine.start('a', d['id'])
    lease = await engine.claim('a', d['id'])
    with pytest.raises(RuntimeFailure):
        await engine.action('a', d['id'], Action(kind='key', key='home'))
    await engine.takeover('a', d['id'])
    with pytest.raises(RuntimeFailure):
        await engine.action('a', d['id'], Action(kind='key', key='home'), lease=lease)
    await engine.action('a', d['id'], Action(kind='key', key='home'))
    engine.close()


@pytest.mark.asyncio
async def test_refuses_resource_not_owned_by_project(tmp_path):
    guest = Guest(); engine = AndroidEngine(tmp_path, guest)
    d = await engine.create('a', DeviceCreate(name='Phone'))
    guest.containers['haybot-android-' + d['id']] = {'Config': {'Labels': {}}, 'State': {'Running': True}}
    with pytest.raises(RuntimeFailure):
        await engine.start('a', d['id'])
    assert not any(x[:2] == ('docker', 'start') for x in guest.calls)
    engine.close()


def test_actions_reject_shell_and_escape_attempts():
    for payload in [{'kind': 'shell', 'text': 'id'}, {'kind': 'key', 'key': 'home;id'}, {'kind': 'tap', 'x': -1, 'y': 2}, {'kind': 'open', 'url': 'file:///etc/passwd'}, {'kind': 'text', 'text': 'a', 'command': 'sh'}]:
        with pytest.raises(ValueError):
            Action.model_validate(payload)

@pytest.mark.asyncio
async def test_health_accepts_loaded_binder_module_without_legacy_device_node(tmp_path):
    async def guest(*args, **kwargs):
        if args[:2] == ('docker', 'info'):
            return b'{"Architecture":"aarch64","KernelVersion":"6.8.0"}'
        if args == ('test', '-d', '/sys/module/binder_linux'):
            return b''
        raise RuntimeFailure('legacy binder device missing')
    engine=AndroidEngine(tmp_path,guest)
    assert (await engine.health())['ready'] is True
    engine.close()

@pytest.mark.asyncio
async def test_destroy_never_started_device_and_refuse_unowned_volume(tmp_path):
    guest=Guest(); engine=AndroidEngine(tmp_path,guest)
    d=await engine.create('a',DeviceCreate(name='unused'))
    await engine.delete('a',d['id'],destroy_data=True)
    assert engine.list('a')==[]
    d=await engine.create('a',DeviceCreate(name='unowned'))
    guest.volumes['haybot-android-data-'+d['id']]={'Labels':{}}
    with pytest.raises(RuntimeFailure):await engine.start('a',d['id'])
    with pytest.raises(RuntimeFailure):await engine.delete('a',d['id'],destroy_data=True)
    assert 'haybot-android-data-'+d['id'] in guest.volumes
    engine.close()

@pytest.mark.asyncio
async def test_revocation_fences_queued_action_and_late_claim(tmp_path):
    guest=Guest(); engine=AndroidEngine(tmp_path,guest)
    d=await engine.create('a',DeviceCreate(name='phone'))
    await engine.start('a',d['id'])
    lease='1'*32
    await engine.claim('a',d['id'],lease)
    lock=engine.lock(d['id']);await lock.acquire()
    action=asyncio.create_task(engine.action('a',d['id'],Action(kind='key',key='home'),lease=lease))
    await asyncio.sleep(0)
    await engine.revoke('a',d['id'],lease)
    lock.release()
    with pytest.raises(RuntimeFailure):await action
    with pytest.raises(RuntimeFailure):await engine.claim('a',d['id'],lease)
    engine.close()

@pytest.mark.asyncio
async def test_revocation_during_adb_preflight_prevents_input(tmp_path):
    guest=Guest();engine=AndroidEngine(tmp_path,guest)
    d=await engine.create('a',DeviceCreate(name='phone'));await engine.start('a',d['id'])
    lease=await engine.claim('a',d['id']);entered=asyncio.Event();resume=asyncio.Event()
    async def serial(_):entered.set();await resume.wait();return '127.0.0.1:40000'
    engine.serial=serial
    job=asyncio.create_task(engine.action('a',d['id'],Action(kind='key',key='home'),lease))
    await entered.wait();await engine.revoke('a',d['id'],lease);resume.set()
    with pytest.raises(RuntimeFailure):await job
    assert not any('keyevent' in call for call in guest.calls)
    engine.close()

@pytest.mark.asyncio
async def test_owner_login_is_durable_blocks_bot_but_allows_owner_control(tmp_path):
    guest = Guest(); engine = AndroidEngine(tmp_path, guest)
    d = await engine.create('owner', DeviceCreate(name='phone'))
    await engine.start('owner', d['id'])
    lease = await engine.claim('owner', d['id'])
    await engine.login('owner', d['id'], True)
    assert engine.get('owner', d['id'])['owner_login'] is True
    for op in (engine.claim('owner', d['id']), engine.observe('owner', d['id'], lease),
               engine.action('owner', d['id'], Action(kind='key'), lease)):
        with pytest.raises(RuntimeFailure): await op
    await engine.action('owner', d['id'], Action(kind='key'))
    engine.close()
    engine = AndroidEngine(tmp_path, guest)
    with pytest.raises(RuntimeFailure): await engine.claim('owner', d['id'])
    with pytest.raises(RuntimeFailure): await engine.login('other', d['id'], False)
    await engine.login('owner', d['id'], False)
    assert engine.get('owner', d['id'])['owner_login'] is False
    assert await engine.claim('owner', d['id'])
    engine.close()

@pytest.mark.asyncio
async def test_bot_observe_without_task_is_also_blocked_during_login(tmp_path):
    guest=Guest(); engine=AndroidEngine(tmp_path,guest)
    d=await engine.create('a',DeviceCreate(name='phone'));await engine.start('a',d['id'])
    await engine.login('a',d['id'],True)
    with pytest.raises(RuntimeFailure):await engine.observe('a',d['id'],automated=True)
    assert not any('screencap' in c for c in guest.calls)
    engine.close()

@pytest.mark.asyncio
async def test_launch_only_accepts_catalog_apps(tmp_path):
    from pydantic import ValidationError
    with pytest.raises(ValidationError):Action(kind='launch',app='shell;id')
    class Launcher(Guest):
        async def __call__(self,*args,**kwargs):
            if 'resolve-activity' in args:return b'com.coolapk.market/.view.main.MainActivity\n'
            if 'pm' in args and 'list' in args:return b'package:com.coolapk.market\n'
            return await super().__call__(*args,**kwargs)
    guest=Launcher();engine=AndroidEngine(tmp_path,guest);d=await engine.create('a',DeviceCreate(name='p'));await engine.start('a',d['id'])
    await engine.action('a',d['id'],Action(kind='launch',app='coolapk'))
    assert any('com.coolapk.market/.view.main.MainActivity' in c for c in guest.calls)
    engine.close()

@pytest.mark.asyncio
async def test_google_profile_rebuild_preserves_volume_and_is_bot_scoped(tmp_path):
    guest=Guest();e=AndroidEngine(tmp_path,guest)
    d=await e.create('a',DeviceCreate(name='p'));await e.start('a',d['id'])
    volume='haybot-android-data-'+d['id']
    with pytest.raises(RuntimeFailure):await e.google_play('other',d['id'],True)
    await e.google_play('a',d['id'],True)
    assert volume in guest.volumes
    assert not any(c[:3]==('docker','volume','rm') for c in guest.calls)
    assert e.get('a',d['id'])['config']['google_play'] is True
    run=[c for c in guest.calls if c[:2]==('docker','run')][-1]
    assert 'sha256:'+'a'*64 in run
    e.close()

@pytest.mark.asyncio
async def test_gms_switch_cannot_stop_after_owner_login_acknowledged(tmp_path):
    entered=asyncio.Event();resume=asyncio.Event()
    class Paused(Guest):
        async def __call__(self,*args,**kwargs):
            if args[:3]==('docker','image','inspect'):
                entered.set();await resume.wait()
            return await super().__call__(*args,**kwargs)
    guest=Paused();e=AndroidEngine(tmp_path,guest);d=await e.create('a',DeviceCreate(name='p'));await e.start('a',d['id'])
    job=asyncio.create_task(e.google_play('a',d['id'],True));await entered.wait()
    await e.login('a',d['id'],True);resume.set()
    with pytest.raises(RuntimeFailure):await job
    assert not any(c[:2]==('docker','stop') for c in guest.calls)
    e.close()

@pytest.mark.asyncio
async def test_gms_launch_failure_restores_working_original_phone(tmp_path):
    class Broken(Guest):
        async def __call__(self,*args,**kwargs):
            if args[:2]==('docker','run') and any('sha256:' in a for a in args):raise RuntimeFailure('gms startup failed')
            return await super().__call__(*args,**kwargs)
    guest=Broken();e=AndroidEngine(tmp_path,guest);d=await e.create('a',DeviceCreate(name='p'));await e.start('a',d['id'])
    result=await e.google_play('a',d['id'],True)
    assert not result['config'].get('google_play')
    assert result['state']=='running' and '恢复' in result['error']
    assert guest.containers['haybot-android-'+d['id']]['State']['Running']
    e.close()

@pytest.mark.asyncio
async def test_new_google_phone_pins_image_for_future_rebuild(tmp_path):
    class Images(Guest):
        digest='a'*64
        async def __call__(self,*args,**kwargs):
            if args[:3]==('docker','image','inspect'):return json.dumps([{'Id':'sha256:'+self.digest}]).encode()
            return await super().__call__(*args,**kwargs)
    guest=Images();e=AndroidEngine(tmp_path,guest);d=await e.create('a',DeviceCreate(name='p',google_play=True))
    await e.start('a',d['id'])
    assert e.get('a',d['id'])['config']['google_play_image_id']=='sha256:'+'a'*64
    guest.digest='b'*64
    await e.stop('a',d['id']);await e.remove_container('a',d['id']);await e.start('a',d['id'])
    assert 'sha256:'+'a'*64 in [c for c in guest.calls if c[:2]==('docker','run')][-1]
    e.close()

@pytest.mark.asyncio
@pytest.mark.parametrize('remaining',[False,True])
@pytest.mark.parametrize('clear_button',[False,True])
async def test_cleanup_verifies_home_and_stopped_processes(tmp_path,remaining,clear_button):
    guest=Guest();e=AndroidEngine(tmp_path,guest)
    d=await e.create('a',DeviceCreate(name='phone'));await e.start('a',d['id']);lease=await e.claim('a',d['id'])
    async def command(*args,**kwargs):
        if args[-3:]==('pm','list','packages'):return b'package:tv.danmaku.bili\n'
        if args[-3:]==('dumpsys','activity','recents'):return b'ACTIVITY MANAGER RECENT TASKS\n  * Recent #0: Task{#1 type=home}\n'
        if 'resolve-activity' in args:return b'com.android.launcher3/.Launcher\n'
        if args[-2:]==('ps','-A'):return b'USER PID NAME\nu0 1 tv.danmaku.bili:player\n' if remaining else b'USER PID NAME\nshell 2 uiautomator\n'
        return await guest(*args,**kwargs)
    async def u2(*args):return json.dumps({'package':'com.android.launcher3','recents_cleared':clear_button}).encode()
    e.command=command;e.u2=u2
    try:
        result=await e.cleanup('a',d['id'],lease)
        assert result['home'] is True
        assert result['background_cleared'] is (not remaining)
        with pytest.raises(RuntimeFailure):await e.cleanup('a',d['id'],'wrong')
    finally:e.close()
