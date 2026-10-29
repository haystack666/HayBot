"""Beijing off-peak browsing with durable daily video counts and operator holds."""
import asyncio
import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from pydantic import Field, model_validator

from .config import StrictModel

BEIJING = ZoneInfo('Asia/Shanghai')
# 国办发明电〔2025〕7号. Weekends stay idle even on makeup workdays,
# as explicitly requested. Store announced dates, never guess lunar holidays.
HOLIDAY_SOURCE = 'https://www.beijing.gov.cn/cs/gncs/zcwj/202603/t20260327_4568275.html'
HOLIDAYS = {2026: [('01-01','01-03'), ('02-15','02-23'), ('04-04','04-06'),
                   ('05-01','05-05'), ('06-19','06-21'), ('09-25','09-27'), ('10-01','10-07')]}


class BrowseWindow(StrictModel):
    start: str = Field(pattern=r'^(?:[01][0-9]|2[0-3]):[0-5][0-9]$')
    end: str = Field(pattern=r'^(?:[01][0-9]|2[0-3]):[0-5][0-9]$')

    @model_validator(mode='after')
    def nonempty(self):
        if self.start==self.end:raise ValueError('开始和结束不能相同；全天可关闭自定义时段')
        return self


class AutoBrowseConfig(StrictModel):
    enabled: bool = False
    daily_video_limit: int = Field(default=30, ge=1, le=1000, strict=True)
    only_off_peak: bool = Field(default=True,strict=True)
    custom_hours: bool = Field(default=False,strict=True)
    time_windows: list[BrowseWindow] = Field(default_factory=lambda:[BrowseWindow(start='08:30',end='08:59'),BrowseWindow(start='19:00',end='22:30')],max_length=20)

    @model_validator(mode='after')
    def windows_required(self):
        if self.custom_hours and not self.time_windows:raise ValueError('请至少添加一个允许浏览的时段')
        return self


def beijing_now():
    return datetime.now(BEIJING)


def period(now):
    now = now.astimezone(BEIJING)
    known = now.year in HOLIDAYS
    holiday = any(start <= now.strftime('%m-%d') <= end for start,end in HOLIDAYS.get(now.year, []))
    minute = now.hour*60 + now.minute
    peak = now.weekday()<5 and not holiday and (540<=minute<720 or 840<=minute<1080)
    return {'peak': peak, 'holiday': holiday, 'calendar_known': known,
            'calendar_warning': '' if known else f'{now.year} 年节假日表尚未更新，暂按周一至周五的高峰时段保守执行'}


def next_idle(now):
    now = now.astimezone(BEIJING)
    if not period(now)['peak']:
        return now
    return now.replace(hour=12 if now.hour<12 else 18, minute=0, second=0, microsecond=0)


def within_windows(now, config):
    if not config.custom_hours:return True
    local=now.astimezone(BEIJING);minute=local.hour*60+local.minute
    for window in config.time_windows:
        start,end=[int(value[:2])*60+int(value[3:]) for value in (window.start,window.end)]
        if (start<=minute<end if start<end else minute>=start or minute<end):return True
    return False


def allowed_at(now,config):
    return within_windows(now,config) and (not config.only_off_peak or not period(now)['peak'])


def next_allowed(now,config):
    now=now.astimezone(BEIJING)
    if allowed_at(now,config):return now
    candidates=[]
    for day in range(9):
        base=(now+timedelta(days=day)).replace(hour=0,minute=0,second=0,microsecond=0)
        boundaries={'00:00','09:00','12:00','14:00','18:00'}
        if config.custom_hours:
            boundaries.update(w.start for w in config.time_windows)
            boundaries.update(w.end for w in config.time_windows)
        for boundary in boundaries:
            hour,minute=map(int,boundary.split(':'));candidate=base.replace(hour=hour,minute=minute)
            if candidate>=now and allowed_at(candidate,config):candidates.append(candidate)
    return min(candidates) if candidates else None


class DouyinScheduler:
    def __init__(self, tasks):
        self.tasks = tasks
        self.job = None
        self.clock = beijing_now
        tasks.db.executescript('''
          CREATE TABLE IF NOT EXISTS douyin_daily_views(
            bot_id TEXT NOT NULL,day TEXT NOT NULL,video_id TEXT NOT NULL,
            task_id TEXT NOT NULL,at REAL NOT NULL,PRIMARY KEY(bot_id,day,video_id));
          CREATE TABLE IF NOT EXISTS douyin_auto_state(
            bot_id TEXT PRIMARY KEY,hold_day TEXT NOT NULL DEFAULT '',hold_reason TEXT NOT NULL DEFAULT '',
            next_attempt REAL NOT NULL DEFAULT 0);
        ''')
        # Import prior evidence, including today's manual tasks, on upgrade.
        cutoff=(self.clock().replace(hour=0,minute=0,second=0,microsecond=0)-timedelta(days=1)).timestamp()
        with tasks.db:
            for row in tasks.db.execute('SELECT id,bot_id,steps FROM browser_tasks WHERE updated>=?',(cutoff,)).fetchall():
                for step in json.loads(row['steps']):
                    if (step.get('watch') or {}).get('advancedSeconds',0)>=1 and (step.get('current') or {}).get('id'):
                        when=datetime.fromtimestamp(step.get('at',cutoff),BEIJING)
                        tasks.db.execute('INSERT OR IGNORE INTO douyin_daily_views VALUES (?,?,?,?,?)',
                            (row['bot_id'],when.date().isoformat(),step['current']['id'],row['id'],when.timestamp()))

    def seen(self, bot_id):
        return [r[0] for r in self.tasks.db.execute('SELECT video_id FROM douyin_daily_views WHERE bot_id=? AND day=?',
            (bot_id,self.clock().date().isoformat()))]

    def start(self):
        if not self.job:
            self.job = asyncio.create_task(self.loop())

    async def close(self):
        if self.job:
            self.job.cancel()
            await asyncio.gather(self.job, return_exceptions=True)

    def count(self, bot_id, now=None):
        day=(now or self.clock()).astimezone(BEIJING).date().isoformat()
        return self.tasks.db.execute('SELECT count(*) FROM douyin_daily_views WHERE bot_id=? AND day=?',(bot_id,day)).fetchone()[0]

    def record(self, task, observation):
        watch,current=observation.get('watch') or {},observation.get('current') or {}
        if watch.get('advancedSeconds',0)<1 or not current.get('id'):
            return
        now=self.clock()
        with self.tasks.db:
            self.tasks.db.execute('INSERT OR IGNORE INTO douyin_daily_views VALUES (?,?,?,?,?)',
                (task['bot_id'],now.date().isoformat(),current['id'],task['id'],now.timestamp()))

    def hold(self, bot_id, reason):
        with self.tasks.db:
            self.tasks.db.execute('INSERT OR REPLACE INTO douyin_auto_state VALUES (?,?,?,0)',
                (bot_id,self.clock().date().isoformat(),reason))

    def resume(self, bot_id):
        with self.tasks.db:
            self.tasks.db.execute('DELETE FROM douyin_auto_state WHERE bot_id=?',(bot_id,))
        return self.status(bot_id)

    def status(self, bot_id):
        now=self.clock()
        cfg=self.tasks.config(bot_id)
        row=self.tasks.db.execute('SELECT * FROM douyin_auto_state WHERE bot_id=?',(bot_id,)).fetchone()
        hold=row['hold_reason'] if row and row['hold_day']==now.date().isoformat() else ''
        count=self.count(bot_id,now)
        due=next_allowed(now,cfg.auto_browse)
        if count>=cfg.auto_browse.daily_video_limit or hold:
            due=next_allowed((now+timedelta(days=1)).replace(hour=0,minute=0,second=0,microsecond=0),cfg.auto_browse)
        elif row and due and row['next_attempt']>due.timestamp():
            due=next_allowed(datetime.fromtimestamp(row['next_attempt'],BEIJING),cfg.auto_browse)
        return {**period(now),'enabled':cfg.auto_browse.enabled,'today_watched':count,
            'daily_video_limit':cfg.auto_browse.daily_video_limit,'remaining':max(0,cfg.auto_browse.daily_video_limit-count),
            'hold_reason':hold,'next_run_at':due.isoformat() if due and cfg.enabled and cfg.auto_browse.enabled else None,
            'timezone':'Asia/Shanghai','allowed_now':allowed_at(now,cfg.auto_browse),'within_custom_hours':within_windows(now,cfg.auto_browse),
            'only_off_peak':cfg.auto_browse.only_off_peak,'custom_hours':cfg.auto_browse.custom_hours,'time_windows':[w.model_dump() for w in cfg.auto_browse.time_windows]}

    def stop_reason(self, task):
        if task['origin'].get('source')!='auto':
            return ''
        cfg=self.tasks.config(task['bot_id'])
        if not cfg.enabled or not cfg.auto_browse.enabled:
            return '自动浏览已关闭，进度已保存'
        state=self.status(task['bot_id'])
        if state['hold_reason']:
            return state['hold_reason']
        if not state['within_custom_hours']:
            return '已离开自定义浏览时段，当前操作结束后暂停，下次允许时段继续'
        if cfg.auto_browse.only_off_peak and state['peak']:
            return '已进入北京时间高峰时段，当前操作结束后暂停，空闲时段继续'
        if state['remaining']<=0:
            return '今日视频数量已达到上限，明天允许的时段继续'
        return ''

    async def tick(self):
        tasks=self.tasks
        for bot in tasks.manager.registry.list():
            bid=bot['id']
            cfg=tasks.config(bid)
            if not cfg.enabled or not cfg.auto_browse.enabled or tasks.busy(bid):
                continue
            state=self.status(bid)
            if not state['allowed_now'] or not state['remaining'] or state['hold_reason']:
                continue
            row=tasks.db.execute('SELECT next_attempt FROM douyin_auto_state WHERE bot_id=?',(bid,)).fetchone()
            if row and row['next_attempt']>self.clock().timestamp():
                continue
            try:
                runtime=tasks.manager.get(bid)
                if runtime.closing:
                    continue
                browser=await tasks.browser.gateway.request('GET',tasks.browser.path(bid))
                if browser.get('owner_login') or browser.get('controller') or browser.get('lease'):
                    self.hold(bid,'主人正在接管或登录，自动浏览今日已暂停，可手动恢复')
                    continue
                if browser.get('automation'):
                    continue
                latest=tasks.config(bid)
                if not latest.enabled or not latest.auto_browse.enabled or tasks.busy(bid) or self.status(bid)['hold_reason'] or not allowed_at(self.clock(),latest.auto_browse):
                    continue
                tasks.submit(bid,'去抖音看你自己感兴趣的视频，自行选择浏览路线；按已有内容与互动设置执行。',
                    {'source':'auto','day':self.clock().date().isoformat()})
            except Exception:
                # A disconnected runtime/provider cannot create a tight retry loop.
                with tasks.db:
                    tasks.db.execute("INSERT INTO douyin_auto_state(bot_id,next_attempt) VALUES (?,?) ON CONFLICT(bot_id) DO UPDATE SET next_attempt=excluded.next_attempt",
                        (bid,self.clock().timestamp()+60))

    def finished(self, task):
        if task['origin'].get('source')!='auto':
            return
        if task['state'] in ('blocked','failed','unknown','cancelled','interrupted'):
            self.hold(task['bot_id'],'自动任务需检查：'+task['result'][:300])
        else:
            with self.tasks.db:
                self.tasks.db.execute("INSERT INTO douyin_auto_state(bot_id,next_attempt) VALUES (?,?) ON CONFLICT(bot_id) DO UPDATE SET next_attempt=excluded.next_attempt",
                    (task['bot_id'],self.clock().timestamp()+30))

    async def loop(self):
        while not self.tasks.closed:
            try:
                await self.tick()
            except Exception:
                pass
            await asyncio.sleep(5)
