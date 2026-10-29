"""Beijing off-peak browsing with durable daily video counts and operator holds."""
import asyncio
import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from pydantic import Field

from .config import StrictModel

BEIJING = ZoneInfo('Asia/Shanghai')
# 国办发明电〔2025〕7号. Weekends stay idle even on makeup workdays,
# as explicitly requested. Store announced dates, never guess lunar holidays.
HOLIDAY_SOURCE = 'https://www.beijing.gov.cn/cs/gncs/zcwj/202603/t20260327_4568275.html'
HOLIDAYS = {2026: [('01-01','01-03'), ('02-15','02-23'), ('04-04','04-06'),
                   ('05-01','05-05'), ('06-19','06-21'), ('09-25','09-27'), ('10-01','10-07')]}


class AutoBrowseConfig(StrictModel):
    enabled: bool = False
    daily_video_limit: int = Field(default=30, ge=1, le=1000, strict=True)


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
        due=next_idle(now)
        if count>=cfg.auto_browse.daily_video_limit or hold:
            due=next_idle((now+timedelta(days=1)).replace(hour=0,minute=0,second=0,microsecond=0))
        elif row and row['next_attempt']>due.timestamp():
            due=next_idle(datetime.fromtimestamp(row['next_attempt'],BEIJING))
        return {**period(now),'enabled':cfg.auto_browse.enabled,'today_watched':count,
            'daily_video_limit':cfg.auto_browse.daily_video_limit,'remaining':max(0,cfg.auto_browse.daily_video_limit-count),
            'hold_reason':hold,'next_run_at':due.isoformat() if cfg.enabled and cfg.auto_browse.enabled else None,
            'timezone':'Asia/Shanghai'}

    def stop_reason(self, task):
        if task['origin'].get('source')!='auto':
            return ''
        cfg=self.tasks.config(task['bot_id'])
        if not cfg.enabled or not cfg.auto_browse.enabled:
            return '自动浏览已关闭，进度已保存'
        state=self.status(task['bot_id'])
        if state['hold_reason']:
            return state['hold_reason']
        if state['peak']:
            return '已进入北京时间高峰时段，当前操作结束后暂停，空闲时段继续'
        if state['remaining']<=0:
            return '今日视频数量已达到上限，明天空闲时段继续'
        return ''

    async def tick(self):
        tasks=self.tasks
        for bot in tasks.manager.registry.list():
            bid=bot['id']
            cfg=tasks.config(bid)
            if not cfg.enabled or not cfg.auto_browse.enabled or tasks.busy(bid):
                continue
            state=self.status(bid)
            if state['peak'] or not state['remaining'] or state['hold_reason']:
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
                if not latest.enabled or not latest.auto_browse.enabled or tasks.busy(bid) or self.status(bid)['hold_reason'] or period(self.clock())['peak']:
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
