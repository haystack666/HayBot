"""Durable task evidence and stage budgets; exhaustion pauses, never replays."""
import re
import xml.etree.ElementTree as ET
from urllib.parse import urlsplit
from pydantic import Field
from .config import StrictModel
from .android_intent import wants_links

LINK_COLLECTION_RULES = """分享链接收集：点击原应用分享面板的“复制链接”后，系统自动读取本次手机剪贴板中的公开链接并保存到task_progress.links，下一次决策直接复用。不需要Chrome、浏览器地址栏、打开网页验证或搜索ID。复制后应先查看task_progress.links，不要重复复制同一帖子；若未取得链接才说明具体失败。旧plan/checkpoint/previous_steps中“无法读取剪贴板”或浏览器读取验证方案均已过时，不得沿用。收集几条不同内容后整理标题与实际链接返回。"""

def requested_browsing_time(goal):
    """Expose an explicit browsing duration; never invent one for open browsing."""
    if not re.search(r'浏览|刷|逛|看|观看',goal) or re.search(r'不(?:限|限制|规定).{0,5}(?:时间|时长)',goal):return None
    number=r'[一二两三四五六七八九十百\d]+'
    match=re.search(r'('+number+r')(?:\s*(?:到|至|[-~～—])\s*('+number+r'))?\s*(分钟|小时)',goal)
    if not match:return None
    def value(text):
        if text.isdigit():return int(text)
        digits={'一':1,'二':2,'两':2,'三':3,'四':4,'五':5,'六':6,'七':7,'八':8,'九':9}
        if text in digits:return digits[text]
        if text=='十':return 10
        if text.count('十')==1:
            left,right=text.split('十')
            if (not left or left in digits) and (not right or right in digits):return digits.get(left,1)*10+digits.get(right,0)
        return None
    first,last,unit=match.groups()
    if last is None and first in ('两三','二三','三四','四五','五六','七八','八九'):first,last=first
    lo=value(first);hi=value(last or first)
    if not lo or not hi or lo>hi:return None
    scale=3600 if unit=='小时' else 60
    return {'min_seconds':lo*scale,'max_seconds':hi*scale}

def browser_detour(goal, decision):
    """Collection never implies permission to invent a browser verification step."""
    collection=bool(re.search(r'链接|分享|url|link',goal,re.I))
    requested=bool(re.search(r'(?:使用|用|通过|启动|打开).{0,8}(?:Chrome|浏览器)|(?:打开|访问|验证).{0,6}(?:网页|网址|链接)',goal,re.I))
    if not collection or requested:return False
    action=decision.get('action') or {}
    if action.get('kind')=='open' or (action.get('kind')=='launch' and action.get('app')=='chrome'):return True
    plan=decision.get('plan') or {}
    proposed=' '.join(plan.get('milestones',[]))+' '+decision.get('reason','')
    return bool(re.search(r'chrome|浏览器|地址栏',proposed,re.I))

class TaskPlan(StrictModel):
    milestones: list[str] = Field(min_length=1,max_length=20)
    estimated_steps: int = Field(default=40,ge=1,le=10000)
    estimated_minutes: int = Field(default=10,ge=1,le=1440)

class TaskCheckpoint(StrictModel):
    summary: str = Field(default='',max_length=4000)
    completed: list[str] = Field(default_factory=list,max_length=20)
    next_step: str = Field(default='',max_length=1000)

def estimate_plan(goal):
    """Fallback only when the controller skips its requested planning response."""
    collection=wants_links(goal) or bool(re.search(r'收集|整理|几条|多条|几个',goal))
    count=re.search(r'(\d{1,2})\s*(?:条|个)',goal)
    items=max(1,min(20,int(count[1]))) if count else 3
    complexity=len(re.findall(r'打开|查看|浏览|获取|整理|评论|发送|返回|搜索',goal))
    steps=12+items*12+complexity*3 if collection else max(4,complexity*5)
    return {'milestones':['确认当前页面','按目标逐项收集并保存结果' if collection else '完成目标操作','核对结果并结束'],'estimated_steps':steps,'estimated_minutes':max(2,(steps+3)//4)}

class TaskBudget:
    def __init__(self,plan,*,adaptive,max_steps,timeout_minutes,now):
        self.started=now
        self.steps=min(240,max(12,int(plan.get('estimated_steps',40))*2)) if adaptive else max_steps
        self.seconds=min(3600,max(180,int(plan.get('estimated_minutes',10))*90)) if adaptive else timeout_minutes*60
    def boundary(self,steps,now):return steps>=self.steps or now-self.started>=self.seconds

def progress_units(progress):
    milestones=set(progress.get('plan',{}).get('milestones',[]))
    completed=set(progress.get('checkpoint',{}).get('completed',[]))
    return len({x['url'] for x in progress.get('links',[])})+len(milestones & completed)


def record_browsing(progress,context,now):
    """Persist observed page visits; visible time is not complete playback evidence."""
    active=progress.get('browsing_active')
    progress['browsing_active']=None
    if not context:return
    records=progress.setdefault('browsing_history',[])
    record=next((r for r in records if r['content_id']==context['content_id'] or r.get('anchors')==context.get('anchors')),None)
    if record is None:
        if len(records)>=50:return
        record={**context,'visits':0,'observations':0,'visible_seconds':0,'first_seen':now}
        records.append(record)
    identities={record['content_id'],context['content_id'],*record.get('identity_aliases',[]),*context.get('identity_aliases',[])}
    continuing=bool(active and active['content_id'] in identities)
    if context.get('identity_source')=='platform_id' or record.get('identity_source')!='platform_id':record.update(context)
    record['identity_aliases']=sorted(identities)
    if continuing:record['visible_seconds']=round(record['visible_seconds']+max(0,min(120,now-active['at'])),1)
    else:record['visits']+=1
    record['observations']+=1;record['last_seen']=now
    progress['browsing_active']={'content_id':record['content_id'],'at':now}

def collect_links(progress,tree,step):
    result=dict(progress);links=list(result.get('links',[]));seen={x['url'] for x in links}
    try:nodes=ET.fromstring(tree).iter('node')
    except ET.ParseError:return result
    for n in nodes:
        for value in (n.get('text',''),n.get('content-desc','')):
            for raw in re.findall(r'https?://[^\s<>"\u3000]+',value):
                if len(raw)>2048:continue
                try:u=urlsplit(raw.rstrip('。，、；）)]'))
                except ValueError:continue
                if u.username or u.password:continue
                host=(u.hostname or '').lower();path=u.path
                valid=(host in ('www.coolapk.com','coolapk.com') and re.fullmatch(r'/feed/\d+/?',path)) or (host in ('www.bilibili.com','bilibili.com') and re.fullmatch(r'/video/(?:BV[A-Za-z0-9]+|av\d+)/?',path)) or (host=='b23.tv' and re.fullmatch(r'/[A-Za-z0-9]+/?',path))
                if not valid:continue
                url='https://'+host+path.rstrip('/')
                if url not in seen and len(links)<100:
                    links.append({'url':url,'source':'observed_ui','step':step});seen.add(url)
    result['links']=links
    return result

def legacy_candidates(steps):
    # Old versions stored only model reasons, not the observed UI. Recover these
    # references as unverified candidates, never promote them to observed evidence.
    root=ET.Element('hierarchy')
    for step in steps:ET.SubElement(root,'node',text=step.get('reason',''))
    links=collect_links({},ET.tostring(root,encoding='unicode'),0).get('links',[])
    return [{'url':item['url'],'source':'historical_model_report','verified':False} for item in links]
