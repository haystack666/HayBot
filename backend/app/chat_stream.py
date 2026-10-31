"""QQ official C2C typewriter: replace one bubble with validated public text.

Protocol: tencent-connect/qqbot-nodejs src/streaming.ts. Generation stays
buffered so schedule/meme envelopes are validated before anything is visible.
"""
import asyncio
from urllib.parse import quote

from .schedule import ScheduleChanged


def supports_stream(config,group):
    return config.transport=='qq_official' and not group


async def send_typewriter(api,target,message_id,text,*,before_send,on_confirmed,complete):
    stream_id=None;index=0
    # Bounded frame count: up to eight interim frames, then one completion.
    step=max(20,(len(text)+7)//8)
    for end in range(step,len(text),step):
        if not before_send():raise ScheduleChanged('会话已变化，停止流式回复')
        body={'input_mode':'replace','input_state':1,'content_type':'markdown',
              'content_raw':text[:end],'event_id':message_id,'msg_id':message_id,'msg_seq':1,'index':index}
        if stream_id:body['stream_msg_id']=stream_id
        receipt=await api('POST',f'/v2/users/{quote(target,safe="")}/stream_messages',before_send=before_send,json=body)
        if not isinstance(receipt,dict) or not receipt.get('id'):return None
        stream_id=stream_id or receipt['id']
        on_confirmed(text[:end],receipt)
        index+=1
        await asyncio.sleep(.5)
    async def finish():
        if not before_send():raise ScheduleChanged('会话已变化，停止流式回复')
        body={'input_mode':'replace','input_state':10,'content_type':'markdown','content_raw':text,
              'event_id':message_id,'msg_id':message_id,'msg_seq':1,'index':index}
        if stream_id:body['stream_msg_id']=stream_id
        receipt=await api('POST',f'/v2/users/{quote(target,safe="")}/stream_messages',before_send=before_send,json=body)
        if isinstance(receipt,dict) and receipt.get('id'):on_confirmed(text,receipt)
        return receipt if isinstance(receipt,dict) and receipt.get('id') else None
    return await complete(finish)
