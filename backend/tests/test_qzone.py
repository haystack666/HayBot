import asyncio
import io
from unittest.mock import AsyncMock

import pytest
from PIL import Image
from pydantic import ValidationError

from app.bot import Bot
from app.store import Store
from test_napcat import configure
from test_providers import client,body


def qbot(tmp_path):
    from app.qzone import QzoneService
    s=Store(tmp_path);configure(s);b=Bot(s);b.state='connected';b.napcat.ready=True
    b.napcat.session=(s.load().account_id,s.load().napcat.ws_url)
    b.napcat.call=AsyncMock(return_value={'tid':'test-tid'})
    return s,b,QzoneService(s,b)


def test_qzone_visibility_config_validation():
    from app.qzone_store import QzoneConfig,PostWrite
    assert QzoneConfig().auto_enabled is False and PostWrite(content='测试').visibility==64
    for kwargs in ({'visibility':3},{'visibility':16},{'visibility':128,'targets':['not-qq']}):
        with pytest.raises(ValidationError):PostWrite(content='测试',**kwargs)
    for kwargs in ({'times':['25:00']},{'times':['12:00','12:00']},{'timezone':'bad-zone'}):
        with pytest.raises(ValidationError):QzoneConfig(**kwargs)


@pytest.mark.asyncio
async def test_qzone_publish_once_with_images_and_visibility(tmp_path):
    from app.qzone_store import PostWrite
    s,b,q=qbot(tmp_path);raw=io.BytesIO();Image.new('RGB',(20,20),'blue').save(raw,'PNG')
    image=q.data.add_image(s.load().account_id,raw.getvalue(),'test.png')
    post=q.data.create(s.load().account_id,PostWrite(content='测试动态',images=[image['id']],visibility=16,targets=['20002']))
    q.submit(post['id']);q.submit(post['id']);await q.drain()
    row=q.data.get(s.load().account_id,post['id'])
    assert row['status']=='sent' and row['tid']=='test-tid'
    assert b.napcat.call.await_count==1
    args=b.napcat.call.await_args;assert args.args[0]=='send_qzone_msg'
    assert args.args[1]['ugc_right']==16 and args.args[1]['target_uins']==['20002']
    assert args.args[1]['images'][0].startswith('base64://')
    q.submit(post['id']);await q.drain();assert b.napcat.call.await_count==1
    await q.close();await b.client.aclose();s.close()


@pytest.mark.asyncio
async def test_qzone_timeout_unknown_never_automatically_retries(tmp_path):
    from app.qzone_store import PostWrite
    s,b,q=qbot(tmp_path);b.napcat.call.side_effect=TimeoutError()
    post=q.data.create(s.load().account_id,PostWrite(content='测试动态'))
    q.submit(post['id']);await q.drain()
    assert q.data.get(s.load().account_id,post['id'])['status']=='unknown'
    q.submit(post['id']);await q.tick();await q.drain()
    assert b.napcat.call.await_count==1
    await q.close();await b.client.aclose();s.close()


def test_qzone_restart_and_account_isolation(tmp_path):
    from app.qzone_store import QzoneStore,PostWrite
    s=Store(tmp_path);q=QzoneStore(s);post=q.create('napcat:10001',PostWrite(content='私有草稿'))
    with s.db:s.db.execute("UPDATE qzone_posts SET status='sending' WHERE id=?",(post['id'],))
    q=QzoneStore(s);assert q.get('napcat:10001',post['id'])['status']=='unknown'
    assert q.list('napcat:99999')['total']==0
    with pytest.raises(ValueError):q.get('napcat:99999',post['id'])
    s.close()


@pytest.mark.asyncio
async def test_qzone_scheduler_disabled_and_legacy_fixed_times_no_longer_publish(tmp_path):
    from app.qzone_store import QzoneConfig
    s,b,q=qbot(tmp_path);q.clock=lambda:1792944000 # local midnight
    await q.tick();await q.drain();assert b.napcat.call.await_count==0
    q.data.save_config(s.load().account_id,QzoneConfig(auto_enabled=True,times=['00:00'],mode='fixed',content='夜深了，晚安。'))
    await q.tick();await q.drain();await q.tick();await q.drain()
    assert b.napcat.call.await_count==0
    q.data.save_config(s.load().account_id,QzoneConfig(auto_enabled=True,times=['00:00'],mode='fixed',content='新的文字'))
    await q.tick();await q.drain();assert b.napcat.call.await_count==0
    await q.close();await b.client.aclose();s.close()


@pytest.mark.asyncio
async def test_qzone_generation_does_not_use_private_chats_memory_or_day(tmp_path):
    s,b,q=qbot(tmp_path);c=s.load();c.schedule.premise='经管系大一学生，周末回家';s.save(c)
    b.generate=AsyncMock(return_value={'message':{'content':'天气不错，想去看看校园里的树。'},'prompt_eval_count':20,'eval_count':10})
    b.memory.context=AsyncMock(side_effect=AssertionError('private memory used'))
    b.schedule.context=AsyncMock(side_effect=AssertionError('private schedule used'))
    s.save_history('user:alice:alice',[{'role':'user','content':'private-secret-sentinel'}],6)
    result=await q.generate('写一条轻松的动态')
    assert result and 'private-secret-sentinel' not in str(b.generate.await_args)
    assert '经管系大一学生' in str(b.generate.await_args)
    assert 'thinking' not in b.generate.await_args.kwargs
    assert s.stats()['total_tokens']==30
    await q.close();await b.client.aclose();s.close()


def test_qzone_api_gates_official_and_validates_drafts(client):
    assert client.get('/api/bots/default/qzone').json()['supported'] is False
    assert client.post('/api/bots/default/qzone/posts',json={'content':'不该发布'}).status_code==400
    c=body(client);c['transport']='napcat';c['napcat'].update(self_id='10001',ws_url='ws://napcat.invalid');assert client.put('/api/bots/default/settings',json=c).status_code==200
    assert client.post('/api/bots/default/qzone/posts',json={'content':' ','visibility':1}).status_code==422
    r=client.post('/api/bots/default/qzone/posts',json={'content':'草稿','visibility':64});assert r.status_code==201
    assert r.json()['status']=='draft' and client.get('/api/bots/default/qzone/posts').json()['total']==1
    assert client.post('/api/bots/default/qzone/posts/'+r.json()['id']+'/publish').status_code==409


@pytest.mark.asyncio
async def test_qzone_delete_only_own_confirmed_tid_and_missed_schedule(tmp_path):
    from app.qzone_store import PostWrite
    s,b,q=qbot(tmp_path);account=s.load().account_id
    post=q.data.create(account,PostWrite(content='测试删除'))
    q.submit(post['id']);await q.drain();await q.remove(post['id'])
    assert b.napcat.call.await_args.args==('delete_qzone_msg',{'tid':'test-tid'})
    assert q.data.get(account,post['id'])['status']=='deleted'
    other=q.data.create('napcat:99999',PostWrite(content='另一账号动态'))
    with pytest.raises(ValueError):await q.remove(other['id'])
    assert b.napcat.call.await_count==2
    post=q.data.create(account,PostWrite(content='已错过的定时动态'))
    with s.db:s.db.execute("UPDATE qzone_posts SET status='scheduled',scheduled_at=1 WHERE id=?",(post['id'],))
    await q.tick();await q.drain();assert q.data.get(account,post['id'])['status']=='failed'
    assert b.napcat.call.await_count==2
    await q.close();await b.client.aclose();s.close()


def test_qzone_image_access_is_account_scoped(tmp_path):
    from app.qzone_store import QzoneStore
    s=Store(tmp_path);q=QzoneStore(s);raw=io.BytesIO();Image.new('RGB',(20,20),'red').save(raw,'PNG')
    image=q.add_image('napcat:10001',raw.getvalue(),'a.png')
    with pytest.raises(ValueError):q.image('napcat:99999',image['id'])
    with pytest.raises(ValueError):q.image('napcat:10001','../../secret.key')
    s.close()


@pytest.mark.asyncio
async def test_old_publish_callback_does_not_remove_replacement_task(tmp_path):
    s,b,q=qbot(tmp_path)
    old=asyncio.create_task(asyncio.sleep(0));new=asyncio.create_task(asyncio.sleep(.01))
    q.tasks['post']=new
    await old;q.finished('post',old)
    assert q.tasks['post'] is new
    await q.close();await b.client.aclose();s.close()


@pytest.mark.asyncio
async def test_cancel_queued_post_while_another_post_holds_network_lock(tmp_path):
    from app.qzone_store import PostWrite
    s,b,q=qbot(tmp_path);account=s.load().account_id
    post=q.data.create(account,PostWrite(content='等待取消'))
    await q.lock.acquire();q.submit(post['id'])
    await asyncio.wait_for(q.remove(post['id']),.1)
    assert q.data.get(account,post['id'])['status']=='canceled'
    q.lock.release();await q.drain();assert b.napcat.call.await_count==0
    await q.close();await b.client.aclose();s.close()


@pytest.mark.asyncio
async def test_expired_queued_publish_rechecks_deadline_after_lock(tmp_path):
    from app.qzone_store import PostWrite
    s,b,q=qbot(tmp_path);q.clock=lambda:100
    post=q.data.create(s.load().account_id,PostWrite(content='过期不应发'))
    await q.lock.acquire();q.submit(post['id'],deadline=101)
    q.clock=lambda:102;q.lock.release();await q.drain()
    assert b.napcat.call.await_count==0 and q.data.get(s.load().account_id,post['id'])['status']=='failed'
    await q.close();await b.client.aclose();s.close()
