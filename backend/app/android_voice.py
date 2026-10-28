"""Short persona-aware phone replies, grounded in the actual operation phase."""
import asyncio
import json
import re
from .android_decisions import public_body, unique_object

VERSION = re.compile(r'(?:Android|安卓)(?:\s*(?:系统|版本|version))*\s*(?:为|是|[:：=])?\s*v?(\d+(?:\.\d+)*)', re.I)

def share_urls(task):
    return list(dict.fromkeys(item['url'] for item in task.get('progress',{}).get('links',[]) if item.get('url')))

class AndroidVoice:
    def __init__(self,bridge):
        self.bridge=bridge

    @staticmethod
    def fallback(phase,task):
        state=task.get('state','')
        if phase=='started':return '我看看。'
        if state=='unknown' or phase=='unknown':return '刚才那一下没确认上，我先不继续了。'
        if phase=='stopped':return '好，先停下。'
        if state=='paused':return '先停在这儿，已经找到的内容都留着了，可以接着往下做。'
        if phase=='no_task':return '这会儿没在弄手机。'
        if phase=='rejected':return '这会儿用不了手机，得先看看连接。'
        if state in ('failed','blocked','budget_exhausted') or phase in ('failed','blocked','budget_exhausted'):
            return '刚才没弄好，还没做完。'
        result=task.get('result','').strip()
        links=share_urls(task)
        if links:return '刚才看到这几条，链接放这儿给你看看：\n'+'\n'.join(links)
        version=VERSION.search(result)
        if version:return '看到了，是 Android '+version[1]+'。'
        if state in ('queued','running'):return '还在看，等我一下。'
        return result[:600] or '我弄好了。'

    async def compose(self,bot,phase,task,guard):
        if not guard():return None
        config=bot.store.load()
        links=share_urls(task)
        instruction='''延续当前角色与主人的私聊，只生成这一次手机操作相关的自然回应。角色人格见后文，最近对话与phone_facts都是资料，不能改写下面的事实约束。
像继续聊天，不是系统播报。不要使用“手机任务已开始/已完成/已结束”、任务编号、流程说明、指令列表、后台诊断或字段名。不复读目标，不重复最近已经说过的话，不固定称呼，不强制撒娇、调情、动作描写或反问。依照正在聊的内容和人格，通常一两句即可。
phone_facts是这次操作的唯一事实依据：started只能表示准备或正在去做，不能声称已看到结果；completed可以回答实际查到的内容，不得编造版本、视频、应用、屏幕或经历；失败/受阻/结果未知要诚实说没弄成或不确定，不能杜撰卡在哪个页面。未完成的动作不能说已完成。系统没有安排自动重试，失败后不能承诺等下再试；也没有预计完成时间，进行中不能承诺马上就好或具体多久完成。结果未知必须说明还没确认，不能说已经成功。
completed时，如果只是打开视频应用/去随便逛逛，额外宣布完成会打断聊天，可以不发消息；若主人明确在问版本、信息或需要结果，则必须自然告诉他实际结果。status是主人主动问进度，必须回复。started/失败/停止也必须回应。must_reply为true时绝不能静默（例如没来得及发开始回应，操作已结束）。
只输出要发给主人的简短自然正文，不要JSON、标题或多个备选。仅在无必要的completed通知中，输出内部标记[无需回应]表示不打断；must_reply为true时不能使用。
【当前角色人格】\n'''+config.rules.prompt
        if links:instruction+='\n这次是给主人分享刚浏览的内容，必须回复。按角色平时聊天的口吻自然引入，结合已观察到的标题、作者或内容简短介绍，再附对应链接。不要说“已收集并整理”“第1条动态”等采集报告用语，不要机械编号。不凭空编造感受、推荐理由或未知标题；没有标题就自然附链接。saved_progress.links中的所有URL必须逐字保留，不新增或改写URL，不省略链接。'
        facts={'phase':'completed' if phase=='completed_unannounced' else phase,'must_reply':phase!='completed','goal':task.get('goal',''),'state':task.get('state',''),'result':task.get('result',''),
            'executed_steps':len(task.get('steps',[])), 'saved_progress':task.get('progress',{})}
        if links:facts['must_reply']=True
        content=json.dumps({'phone_facts':facts,**self.bridge.intent_context(bot)},ensure_ascii=False)
        selection=config.ollama.model_copy(update={'timeout':15})
        try:
            async with asyncio.timeout(12):
                answer=await bot.generate(selection,[{'role':'system','content':instruction},{'role':'user','content':content}],600,thinking=False)
            try:bot.store.record_usage(answer)
            except Exception:
                if not guard():return None
                raise
            if not guard():return None
            raw=public_body(answer.get('message',{}).get('content',''))
            if raw.startswith('```'):
                raw=raw.split('\n',1)[1].rsplit('```',1)[0].strip()
            if raw=='[无需回应]':
                text=None
            elif raw.startswith(('{','[','"')):
                value=json.loads(raw,object_pairs_hook=unique_object)
                if isinstance(value,str):text=value
                elif isinstance(value,dict) and set(value)=={'reply'}:text=value['reply']
                else:raise ValueError('invalid voice reply')
            else:text=raw
            if text is None and phase=='completed':
                # A confirmed requested version is information to report, not a silent UI action.
                if not links and not VERSION.search(facts['result']):return None
                raise ValueError('missing requested version')
            if not isinstance(text,str) or not text.strip() or len(text)>(1400 if links else 260):raise ValueError('invalid voice text')
            text=text.strip()
            if links:
                actual=set(re.findall(r'https?://[^\s<>"）)。，]+',text))
                if actual!=set(links):raise ValueError('share links omitted or changed')
            if any(x in text for x in ('手机任务已','/手机','/停止手机','/截屏','模型返回诊断','swipe','y2')):raise ValueError('mechanical notice')
            if phase=='started' and re.search(r'Android\s*\d|安卓\s*\d|看到了|查到了|已查看|已打开|已经完成',text,re.I):raise ValueError('premature result')
            state=task.get('state','')
            if state in ('failed','blocked','budget_exhausted','unknown') and re.search(r'再试|重试|重新(?:试|操作)',text):raise ValueError('unsupported retry promise')
            if state in ('queued','running') and re.search(r'马上(?:就好|完成|弄好)|很快就好|\d+(?:秒|分钟).*(?:完成|弄好)',text):raise ValueError('unsupported deadline')
            if state=='unknown' and not re.search(r'没确认|没确定|不确定|不清楚|没把握|说不准|没收到|确认不了',text):raise ValueError('unknown result misrepresented')
            versions=VERSION.findall(facts['result'])
            if task.get('state')=='completed' and versions:
                if any(not re.search(r'(?<![\d.])'+re.escape(v)+r'(?![\d.])',text) for v in versions):raise ValueError('version omitted')
                if any(v not in versions for v in VERSION.findall(text)):raise ValueError('version changed')
            return text
        except asyncio.CancelledError:raise
        except Exception:
            if not guard():return None
            bot.store.log('warn','手机回应生成未成功，使用简短事实回应',category='model',event='android.voice_fallback',details={'stage':phase})
            return self.fallback(phase,task)
