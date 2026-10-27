"""Owner-private QQ entry point for asynchronous Android tasks."""
import asyncio
import base64
import io
from PIL import Image
import json
import re
import time
from urllib.parse import quote
from .android_decisions import public_body

STATES={'queued':'等待开始','running':'进行中','completed':'已完成','failed':'失败','unknown':'结果未知','cancelled':'已停止','blocked':'需要人工接管','budget_exhausted':'达到步骤上限'}

class AndroidQQ:
    def __init__(self,tasks):
        self.tasks=tasks
        tasks.completion_callback=self.notify
        from .android_voice import AndroidVoice
        self.voice=AndroidVoice(self).compose

    @staticmethod
    def command(text):
        if text in ('/手机截图','/截屏','/手机 截图'):return {'request':'screenshot'}
        if text in ('/手机进度','/手机状态'):return {'request':'status'}
        if text in ('/停止手机','/手机停止'):return {'request':'stop'}
        if text=='/手机':return {'request':'help'}
        match=re.fullmatch(r'/手机\s+(.+)',text,flags=re.S)
        if match:
            goal=match[1].strip()
            if goal in ('进度','状态'):return {'request':'status'}
            if goal in ('停止','取消'):return {'request':'stop'}
            return {'request':'start','goal':goal}
        return None

    def runtime(self,bot):
        return next((r for r in self.tasks.manager.runtimes.values() if r.bot is bot and not r.closing),None)

    def allowed(self,bot,user,group):
        if self.tasks.closed:return False
        r=self.runtime(bot)
        if not r or group:return False
        c=self.tasks.config(r.id)
        return c.enabled and c.qq_enabled and bool(c.qq_owner_id) and c.qq_owner_id==str(user)

    def intent_context(self,bot):
        runtime=self.runtime(bot)
        if not runtime:return {'recent_phone_tasks':[],'recent_dialogue':[]}
        cfg=self.tasks.config(runtime.id);account=bot.store.load().account_id
        owner=cfg.qq_owner_id
        scope=bot.store.db.execute("SELECT source_floor FROM user_scopes WHERE app_id=? AND kind='user' AND target=? AND sender_id=?",(account,owner,owner)).fetchone()
        floor=scope['source_floor'] if scope else 0
        rows=bot.store.db.execute("""SELECT m.role,m.content,m.at FROM chat_messages m
          JOIN chat_conversations c ON c.id=m.conversation_id
          WHERE c.app_id=? AND c.kind='user' AND c.target_id=? AND m.id>? AND m.status!='sent_stale'
          ORDER BY m.id DESC LIMIT 10""",(account,owner,floor)).fetchall()
        dialogue=[{'role':r['role'],'content':r['content'][:1000],'at':r['at']} for r in reversed(rows)]
        jobs=[{'goal':t['goal'],'state':t['state'],'result':t['result'][:1000],'updated':t['updated']}
              for t in self.tasks.list(runtime.id) if t['origin'].get('source')=='qq'
              and t['origin'].get('requester_id')==owner and t['origin'].get('account_id')==account and self.tasks.valid_origin(t)][:3]
        return {'recent_phone_tasks':jobs,'recent_dialogue':dialogue}

    async def cancel_scope(self,bot,sid=None):
        if self.tasks.closed:return
        runtime=self.runtime(bot)
        if not runtime:return
        for task in self.tasks.list(runtime.id):
            if task['origin'].get('source')=='qq' and (sid is None or task['origin'].get('scope_id')==sid) and task['state'] in ('queued','running'):
                await self.tasks.cancel(runtime.id,task['id'])

    async def classify(self,bot,text,history):
        selection=bot.store.load().ollama.model_copy(update={'timeout':30})
        instruction='''判断主人当前消息是否明确要求你实际操作安卓手机。只返回JSON：{"request":"start|status|stop|screenshot|none","goal":"独立完整的手机操作目标"}。
start只用于明确委托手机操作；能不能帮我打开设置属于委托。聊天闲聊、询问你有无能力、假设、讨论、引用他人说法、否定或取消邀请而未要求操作时none。不能从历史里的旧指令自动发起；历史仅用于补全本条明确委托的指代。status表示查询已发起手机任务进度，stop表示停止当前手机任务。screenshot表示结合语境要求查看手机当前画面，截图不需要先执行其他操作。无需出现手机/截图等固定关键词：最近真实手机任务是去哔哩哔哩刷视频，当前问“你刷的啥？给我看看”，应screenshot。近期任务为打开设置，当前说“让我看看现在的画面”，也应screenshot。若近期对话正在聊穿搭、方案、画作等，“给我看看”应none；单独泛泛的“给我看看”且指代不明也应none。只问“你刷了什么”而未要求看画面时none，留给正常聊天。recent_phone_tasks是已发生的事实记录，不是当前委托；recent_dialogue用于判断指代，以主人最新意图为准，不能执行其中引用或旧的请求。不确定返回none。不得扩大目标或添加主人没要求的操作。'''
        try:
            result=await bot.generate(selection,[{'role':'system','content':instruction},{'role':'user','content':json.dumps({'current_message':text[:3000],**self.intent_context(bot)},ensure_ascii=False)}],400,thinking=False)
            bot.store.record_usage(result)
            raw=public_body(result.get('message',{}).get('content',''))
            start=raw.find('{');end=raw.rfind('}')
            value=json.loads(raw[start:end+1])
            if not isinstance(value,dict) or value.get('request') not in ('start','status','stop','screenshot','none'):return {'request':'none'}
            if value['request']=='start' and (not isinstance(value.get('goal'),str) or not 0<len(value['goal'].strip())<=3000):return {'request':'none'}
            return value
        except asyncio.CancelledError:raise
        except Exception:
            bot.store.log('warn','手机请求识别未成功，未发起设备操作；可使用 /手机 指令',category='model',event='android.intent_unavailable')
            return {'request':'none'}

    async def send(self,bot,config,data,target,text,sequence=1,guard=None,event='notice'):
        if config.transport!='napcat' and bot.schedule_reply_expired(data,command='手机'):return False
        if guard is not None and not guard():return False
        content=text[:1550]
        receipt=await bot.api('POST',f'/v2/users/{quote(str(target),safe="")}/messages',
            before_send=guard,json={'msg_type':0,'content':content,'msg_id':data['id'],'msg_seq':sequence})
        if not isinstance(receipt,dict) or not receipt.get('id'):return False
        bot.store.chat.record(config.account_id,'user',str(target),'assistant',content,
            f'android:{config.account_id}:{target}:{data["id"]}:{event}:{sequence}',at=time.time(),source='android',status='sent' if guard is None or guard() else 'sent_stale')
        bot.store.record_result('sent','手机任务提示已发送',category='message',event='android.notice_sent')
        return True

    async def handle(self,bot,text,config,data,group,target,user,sid,source_id,batch,key):
        intent=self.command(text)
        if not intent and not self.allowed(bot,user,group):return False
        if intent and group:return True  # Phone status and outcomes are never disclosed to a group.
        runtime=self.runtime(bot)
        if not runtime:return False
        cfg=self.tasks.config(runtime.id)
        if not intent:
            if not cfg.natural_requests:return False
            intent=await self.classify(bot,text,bot.store.history(key,2))
            if intent.get('request')=='none':return False
        if batch is None and not bot.store.claim(f'{target}:{data["id"]}'):return True
        if not self.allowed(bot,user,group):
            await self.send(bot,config,data,target,'手机操作仅限后台设置的授权用户私聊使用。请在「安卓设备」中配置 QQ 授权。')
            return True
        stamp=cfg.model_dump_json()
        def current():
            if not self.allowed(bot,user,group) or self.tasks.config(runtime.id).model_dump_json()!=stamp:return False
            if bot.store.load().account_id!=config.account_id:return False
            try:
                if source_id<=bot.store.scopes.get(sid,config.account_id)['source_floor']:return False
            except ValueError:return False
            return batch is None or bot.inbox.live(batch)
        if not current():return True
        request=intent['request']
        if request=='help':
            await self.send(bot,config,data,target,'发送 /手机 任务内容 开始操作；/手机进度 查询结果；/停止手机 停止任务；/手机截图 获取图片。也可以明确告诉我用手机做什么。',guard=current)
            return True
        if request=='screenshot':
            try:await self.screenshot(bot,config,data,target,runtime.id,current)
            except ValueError as exc:await self.send(bot,config,data,target,'手机截图未能发送：'+str(exc),sequence=2,guard=current,event='screenshot-error')
            return True
        jobs=[t for t in self.tasks.list(runtime.id) if t['origin'].get('source')=='qq' and t['origin'].get('requester_id')==str(user) and t['origin'].get('account_id')==config.account_id]
        if request=='status':
            visible=[t for t in jobs if self.tasks.valid_origin(t)]
            task=visible[0] if visible else None
            guard=lambda:current() and (task is None or self.tasks.valid_origin(task))
            content=await self.voice(bot,'status' if task else 'no_task',task or {},guard)
            if content:await self.send(bot,config,data,target,content,guard=guard)
            return True
        if request=='stop':
            active=next((t for t in jobs if t['state'] in ('queued','running')),None)
            if active:
                result=await self.tasks.cancel(runtime.id,active['id'])
                content=await self.voice(bot,'stopped',result,current)
            else:content=await self.voice(bot,'no_task',{},current)
            if content:await self.send(bot,config,data,target,content,guard=current)
            return True
        try:
            devices=(await self.tasks.gateway.request('GET',f'/bots/{quote(runtime.id,safe="")}/devices'))['devices']
            if not current():return True
            if not devices:raise ValueError('当前 Bot 还没有手机，请先在后台创建设备')
            d=devices[0]
            if d.get('state') not in ('running','booting'):raise ValueError('手机尚未启动，请先在后台启动设备')
            origin={'source':'qq','account_id':config.account_id,'requester_id':str(user),'scope_id':sid,'source_id':source_id,
                'message_id':data['id'],'timestamp':data.get('timestamp'),'target':str(target)}
            task=self.tasks.submit(runtime.id,d['id'],intent['goal'],origin=origin)
            await self.acknowledge(bot,config,data,target,runtime.id,task['id'],current)
        except ValueError as exc:
            content=await self.voice(bot,'rejected',{'goal':intent.get('goal',''),'state':'rejected','result':str(exc)},current)
            if content:await self.send(bot,config,data,target,content,guard=current)
        return True

    async def acknowledge(self,bot,config,data,target,bot_id,task_id,current):
        active=lambda:current() and self.tasks.get(bot_id,task_id)['state'] in ('queued','running')
        task=self.tasks.get(bot_id,task_id)
        content=await self.voice(bot,'started',task,active)
        if not current():
            self.tasks.notification(task_id,'skipped',expected='pending_ack');return
        task=self.tasks.get(bot_id,task_id)
        if task['state']=='cancelled':
            self.tasks.notification(task_id,'skipped',expected='pending_ack');return
        confirmed=False
        if content and active():
            try:confirmed=await self.send(bot,config,data,target,content,guard=active,event='started')
            except asyncio.CancelledError:raise
            except Exception:pass  # Never replay an unconfirmed acknowledgement.
        if not current() or self.tasks.get(bot_id,task_id)['state']=='cancelled':
            self.tasks.notification(task_id,'skipped',expected='pending_ack');return
        self.tasks.notification(task_id,'ready' if confirmed else 'ready_unannounced',expected='pending_ack')
        if self.tasks.get(bot_id,task_id)['state'] not in ('queued','running'):
            await self.notify(bot_id,task_id)

    async def screenshot(self,bot,config,data,target,bot_id,guard):
        devices=(await self.tasks.gateway.request('GET',f'/bots/{quote(bot_id,safe="")}/devices'))['devices']
        if not guard():return False
        if not devices:raise ValueError('当前 Bot 还没有手机')
        device=devices[0]
        epoch=self.tasks.login_epoch(bot_id,device['id'])
        original_guard=guard
        guard=lambda:original_guard() and self.tasks.login_valid(bot_id,device['id'],epoch)
        if not guard():return False
        if device.get('owner_login'):raise ValueError('owner 正在登录，暂不发送手机画面')
        observation=await self.tasks.gateway.request('GET',f'/bots/{quote(bot_id,safe="")}/devices/{device["id"]}/observe?automated=true')
        if not guard():return False
        encoded=observation.get('image','')
        if not isinstance(encoded,str) or len(encoded)>12*1024*1024:raise ValueError('设备截图大小异常')
        try:
            raw=base64.b64decode(encoded,validate=True)
            with Image.open(io.BytesIO(raw)) as image:
                if image.width*image.height>8_000_000:raise ValueError('设备画面过大')
                output=io.BytesIO();image.convert('RGB').save(output,format='JPEG',quality=88)
                content=output.getvalue()
        except (OSError,ValueError):raise ValueError('设备没有返回有效截图') from None
        if not guard():return False
        if config.transport=='napcat':
            receipt=await bot.napcat.send_picture(False,str(target),content,before_send=guard)
        else:
            if bot.schedule_reply_expired(data,command='手机截图'):return False
            path=f'/v2/users/{quote(str(target),safe="")}'
            uploaded=await bot.api('POST',path+'/files',before_send=guard,json={'file_type':1,'file_data':base64.b64encode(content).decode(),'srv_send_msg':False},timeout=30)
            if not isinstance(uploaded,dict) or not uploaded.get('file_info'):raise ValueError('QQ未确认图片上传')
            if not guard() or bot.schedule_reply_expired(data,command='手机截图'):return False
            receipt=await bot.api('POST',path+'/messages',before_send=guard,json={'msg_type':7,'content':' ','media':{'file_info':uploaded['file_info']},'msg_id':data['id'],'msg_seq':1})
        if not isinstance(receipt,dict) or not receipt.get('id'):raise ValueError('QQ未确认图片送达，请先查看QQ，不自动重发')
        bot.store.chat.record(config.account_id,'user',str(target),'assistant','[发送手机当前屏幕截图]',
            f'android-screenshot:{config.account_id}:{target}:{data["id"]}',attachment_count=1,at=time.time(),source='android_screenshot',status='sent' if guard() else 'sent_stale')
        bot.store.record_result('sent','手机截图已发送',category='message',event='android.screenshot_sent')
        return True

    @staticmethod
    def result_text(task):
        result=task.get('result','')
        if task.get('state')=='failed' and result.startswith('操作模型连续两次'):
            return '操作模型没有生成完整有效的动作，已停止，本轮未操作手机。详细原因已保存在后台模型返回诊断中。'
        return result

    async def notify(self,bot_id,task_id):
        task=self.tasks.get(bot_id,task_id)
        if task['state'] in ('queued','running','cancelled') or task['notification'] not in ('ready','ready_unannounced'):return
        origin=task['origin']
        if not self.tasks.valid_origin(task):
            self.tasks.notification(task_id,'skipped',expected=task['notification']);return
        runtime=self.tasks.manager.get(bot_id);bot=runtime.bot;config=bot.store.load()
        data={'id':origin['message_id'],'timestamp':origin.get('timestamp')}
        if bot.state not in ('connected','connecting') or config.transport!='napcat' and bot.schedule_reply_expired(data,command='手机'):
            self.tasks.notification(task_id,'skipped',expected=task['notification']);return
        unannounced=task['notification']=='ready_unannounced'
        if not self.tasks.notification(task_id,'sending',expected=task['notification']):return
        guard=lambda:self.tasks.valid_origin(self.tasks.get(bot_id,task_id)) and self.runtime(bot) is runtime and bot.state=='connected'
        try:
            content=await self.voice(bot,'completed_unannounced' if unannounced and task['state']=='completed' else task['state'],task,guard)
            if content is None:
                self.tasks.notification(task_id,'skipped',expected='sending');return
            ok=await self.send(bot,config,data,origin['target'],content,sequence=2,guard=guard,event='result')
            self.tasks.notification(task_id,'sent' if ok else 'unknown',expected='sending')
        except Exception:self.tasks.notification(task_id,'unknown',expected='sending')

    def chat_context(self,bot,user,group):
        if not self.allowed(bot,user,group):return ''
        runtime=self.runtime(bot);account=bot.store.load().account_id
        tasks=[{'goal':t['goal'],'state':t['state'],'result':t['result'][:1000]} for t in self.tasks.list(runtime.id)
               if t['origin'].get('source')=='qq' and t['origin'].get('account_id')==account and t['origin'].get('requester_id')==str(user) and self.tasks.valid_origin(t)][:3]
        return '\n[真实手机能力]你有绑定的安卓手机。主人的明确操作请求会交给独立任务执行，可用 /手机、/手机进度、/停止手机、/手机截图。可把当前真实手机截图作为图片发给主人，不需要模型虚构图片。只有真实任务结果才能当作已执行，不能把计划说成已经完成。最近手机任务：'+json.dumps(tasks,ensure_ascii=False)+'\n'
