"""Select only the configured owner's private scope and already-started day facts."""
import hashlib
import json
import re
from datetime import datetime
from zoneinfo import ZoneInfo


class OwnerSource:
    def __init__(self,service):self.service=service;self.store=service.store

    def binding(self):
        c=self.store.load();policy,_=self.service.data.config(c.account_id)
        row=self.store.db.execute("SELECT * FROM user_scopes WHERE app_id=? AND kind='user' AND target=? AND sender_id=?",
            (c.account_id,policy.owner_id,policy.owner_id)).fetchone() if policy.owner_id else None
        return c,policy,dict(row) if row else None

    def stamp(self):
        c,p,owner=self.binding();day=self.service.bot.schedule.for_scope(owner['id']) if owner else None
        value=[c.account_id,p.owner_id,owner['id'] if owner else None,owner['epoch'] if owner else None,
            owner['source_floor'] if owner else None,list(day.stamp()) if day else None]
        return hashlib.sha256(json.dumps(value,sort_keys=True).encode()).hexdigest()

    def snapshot(self):
        _,p,owner=self.binding()
        return {'owner_id':p.owner_id,'available':bool(owner),'scope_id':owner['id'] if owner else ''}

    def collect(self):
        c,p,owner=self.binding();now=self.service.clock()
        result={'available':bool(owner),'messages':[],'day':{},'signature':'','latest_message_id':0,'stamp':self.stamp()}
        if not owner:return result
        rows=self.store.db.execute('''SELECT m.* FROM chat_messages m JOIN chat_conversations c ON c.id=m.conversation_id
            WHERE c.app_id=? AND c.kind='user' AND c.target_id=? AND m.id>? AND m.recorded_at>=? AND m.recorded_at<=?
            AND ((m.role='user' AND m.sender_id=? AND m.source='incoming') OR (m.role='assistant' AND m.source='reply' AND m.status='sent'))
            ORDER BY m.id DESC LIMIT 24''',(c.account_id,p.owner_id,owner['source_floor'],now-86400,now+60,p.owner_id)).fetchall()
        for row in reversed(rows):
            if not row['content'].strip() or row['content'].lstrip().startswith('/'):continue
            result['messages'].append({'role':'owner' if row['role']=='user' else 'character','text':row['content'][:600]})
            result['latest_message_id']=max(result['latest_message_id'],row['id'])
        if c.schedule.enabled:
            day=self.service.bot.schedule.for_scope(owner['id']);plan=day.saved(c)
            local=datetime.fromtimestamp(now,ZoneInfo(c.schedule.timezone));minute=local.strftime('%H:%M')
            if plan and plan.get('date')==local.date().isoformat() and (owner['epoch']==0 or plan.get('source_epoch')==owner['epoch']):
                past=[item for item in plan['activities'] if item['start']<=minute]
                result['day']={'activities':[{'start':i['start'],'activity':i['activity'],'outfit':i['outfit']} for i in past[-8:]],
                    'events':[e for e in plan['events'] if e['time']<=minute][-8:]}
        result['signature']=hashlib.sha256(json.dumps([result['latest_message_id'],result['day']],sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        return result

    def clean_output(self,text):
        _,p,_=self.binding()
        if p.owner_id:text=re.sub(r'(?<!\d)'+re.escape(p.owner_id)+r'(?!\d)','对方',text)
        text=re.sub(r'https?://\S+|[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}|(?<!\d)\d{6,}(?!\d)','[个人信息已隐去]',text)
        return text
