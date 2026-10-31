"""Bounded speech adapters and QQ media conversion. Audio never enters chat history."""
import asyncio
import base64
import hashlib
import hmac
import io
import json
import re
import time
import uuid
import wave
from dataclasses import dataclass
from email.utils import formatdate
from urllib.parse import urlsplit, urlunsplit, urlencode, urljoin
from xml.sax.saxutils import escape, quoteattr
import httpx
from websockets.asyncio.client import connect
from .providers import headers, endpoint, read_response, ProviderHTTPError

MAX_AUDIO=6*1024*1024
MAX_OUTPUT=12*1024*1024


class SpeechError(ValueError):pass


@dataclass
class SpeechAudio:
    data:bytes
    mime:str='audio/wav'


def audio_attachments(data):
    source=data.get('attachments') or []
    if isinstance(source,dict):source=[source]
    if not isinstance(source,list):return []
    return [a for a in source if isinstance(a,dict) and (str(a.get('content_type','')).lower().startswith('audio/') or a.get('content_type') in ('voice','audio'))][:3]


def chat_attachments(data):
    from .images import image_attachments
    return [*image_attachments(data),*audio_attachments(data)]


def voice_directive(text):
    """Classify an explicit output-channel request in the current message."""
    # Quoted examples and statements about a previous recording are not
    # requests. A current negative request always overrides every trigger.
    text=re.sub(r'[“「『"].*?[”」』"]','',text or '',flags=re.S)
    if re.search(r"(?:不要|不用|别|无需|don't|do not|no need to).{0,18}(?:语音|声音|voice|audio)",text,re.I):return 'denied'
    if re.search(r'^\s*/语音(?:\s|$)',text,re.I):return 'command'
    if re.search(
        r'(?:用|换成)语音(?:回复|回答|说|聊|读|讲|唱|告诉|念|跟我|和我|吧|嘛|吗|[？?]|$)'
        r'|(?:发|来|回)(?:个|一条|一段|条|段)?语音(?:[吧呗呀啊嘛吗？?！!。\s]|$)'
        r'|想听你.{0,4}(?:声音|说话)|(?:reply|respond).{0,12}(?:voice|audio)',text,re.I):return 'imperative'
    return ''


def wants_voice(text):
    return voice_directive(text) in ('command','imperative')


def split_voice_actions(text):
    """Extract balanced round-bracket actions without guessing at malformed text."""
    actions=[];spoken=[];stack=[];start=0;cursor=0
    for index,char in enumerate(text):
        if char in ('(', '（'):
            if not stack:
                spoken.append(text[cursor:index]);start=index
            stack.append(')' if char=='(' else '）')
        elif char in (')', '）'):
            if not stack or stack.pop()!=char:raise SpeechError('动作括号不完整，本轮使用文字回复')
            if not stack:
                actions.append(text[start:index+1]);cursor=index+1
    if stack:raise SpeechError('动作括号不完整，本轮使用文字回复')
    spoken.append(text[cursor:])
    return '\n'.join(actions), '\n'.join(part.strip() for part in spoken if part.strip())


def voice_reply_instruction(config):
    if config.separate_actions:
        return ('\n本轮采用动作文字与语音台词分离：可以自然描写动作，但所有动作描写必须放在成对的中文圆括号（…）或英文圆括号(...)内，'
                '括号内会原样作为文字发送，不会朗读；括号外只写实际说出口的台词，会合成为语音。'
                '不要为了使用此格式刻意添加动作；不要写Markdown或发语音的说明。')
    return '\n本轮将把你的回复正文合成为语音。直接说话，不写动作括号、Markdown或发语音的说明。'


@dataclass(frozen=True)
class VoiceDecision:
    enabled:bool
    reason:str


def decide_voice(config,text,*,has_audio=False,group=False,event_key='',last_auto_voice=0,now=None):
    """Choose the reply channel exactly once for one logical inbound turn."""
    now=time.time() if now is None else now
    if not config.enabled:return VoiceDecision(False,'disabled')
    if group and config.scope!='private_and_group':return VoiceDecision(False,'scope')
    directive=voice_directive(text)
    if directive=='denied':return VoiceDecision(False,'denied')
    if directive=='command' and config.command_trigger:return VoiceDecision(True,'command')
    if directive=='imperative' and config.imperative_trigger:return VoiceDecision(True,'imperative')
    if has_audio and config.voice_follow_trigger:return VoiceDecision(True,'incoming_voice')
    if not config.auto_probability:return VoiceDecision(False,'not_selected')
    if config.auto_cooldown_seconds and now-last_auto_voice<config.auto_cooldown_seconds:
        return VoiceDecision(False,'cooldown')
    seed=(event_key or text or 'speech').encode('utf-8','ignore')
    bucket=int.from_bytes(hashlib.sha256(seed).digest()[:8],'big')%100
    return VoiceDecision(bucket<config.auto_probability,'automatic' if bucket<config.auto_probability else 'probability')


def pcm_wav(raw,rate=24000):
    out=io.BytesIO()
    with wave.open(out,'wb') as w:w.setnchannels(1);w.setsampwidth(2);w.setframerate(rate);w.writeframes(raw)
    return out.getvalue()


async def to_wav(raw,seconds=120):
    if not raw or len(raw)>MAX_OUTPUT:raise SpeechError('音频为空或超过大小限制')
    if raw.startswith((b'\x02#!SILK_V3',b'#!SILK_V3')):
        try:
            import pilk_nogil as silk
            duration=await asyncio.to_thread(silk.get_duration,raw)
            if duration>seconds*1000:raise SpeechError('语音时长超过限制')
            pcm=await asyncio.to_thread(silk.decode,raw,None,pcm_rate=24000)
            raw=pcm_wav(pcm)
        except SpeechError:raise
        except Exception:raise SpeechError('语音解码失败，请发送较短的语音或常见音频格式') from None
    try:
        process=await asyncio.create_subprocess_exec('ffmpeg','-hide_banner','-loglevel','error','-protocol_whitelist','pipe',
            '-i','pipe:0','-t',str(seconds+1),'-vn','-ac','1','-ar','16000','-f','wav','pipe:1',
            stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
        try:
            async with asyncio.timeout(25):result,_=await process.communicate(raw)
        finally:
            if process.returncode is None:process.kill();await process.wait()
        if process.returncode or len(result)<128 or len(result)>int(16000*2*(seconds+0.5))+128:raise SpeechError('音频无法读取或时长超过限制')
        return result
    except SpeechError:raise
    except Exception:raise SpeechError('音频转换暂不可用，请检查 FFmpeg 安装') from None


async def to_silk(raw):
    wav=await to_wav(raw,120)
    try:
        with wave.open(io.BytesIO(wav)) as w:pcm=w.readframes(w.getnframes())
        import pilk_nogil as silk
        return await asyncio.to_thread(silk.encode,pcm,None,pcm_rate=16000,tencent=True)
    except Exception:raise SpeechError('QQ 语音编码失败') from None


async def bounded_response(client,method,url,**kwargs):
    async with client.stream(method,url,follow_redirects=False,**kwargs) as response:
        if not response.is_success:raise ProviderHTTPError(response.status_code)
        if response.headers.get('content-length','').isdigit() and int(response.headers['content-length'])>MAX_OUTPUT:raise SpeechError('语音服务返回的音频过大')
        result=bytearray()
        async for chunk in response.aiter_bytes(65536):
            result.extend(chunk)
            if len(result)>MAX_OUTPUT:raise SpeechError('语音服务返回的数据过大')
        return bytes(result),response.headers.get('content-type','')


async def json_request(client,method,url,**kwargs):
    raw,_=await bounded_response(client,method,url,**kwargs)
    try:data=json.loads(raw)
    except ValueError:raise SpeechError('语音服务返回了无效数据') from None
    if not isinstance(data,dict):raise SpeechError('语音服务返回格式无效')
    if data.get('base_resp') is not None and not isinstance(data['base_resp'],dict):raise SpeechError('语音服务返回格式无效')
    if data.get('error') or data.get('code',0) not in (0,20000000) or (data.get('base_resp') or {}).get('status_code',0):
        raise SpeechError('语音服务未成功处理请求，请检查模型、权限和参数')
    return data


async def fetch_audio(client,url,*,qq=False):
    # Remote media must never redirect to a private host or inherit API credentials.
    domains=('qq.com','qq.com.cn','qpic.cn','qlogo.cn') if qq else ('aliyuncs.com','aliyun.com')
    def allowed(value):
        if not isinstance(value,str) or not value or len(value)>8192:raise SpeechError('没有可读取的音频地址')
        if value.startswith('//'):value='https:'+value
        elif '://' not in value:value='https://'+value
        try:
            u=urlsplit(value);port=u.port
        except ValueError:raise SpeechError('音频地址无效') from None
        if u.scheme not in ('http','https') or not u.hostname or u.username or u.password or port not in (None,80,443) or not any(u.hostname==h or u.hostname.endswith('.'+h) for h in domains):
            raise SpeechError('音频地址不属于可信媒体服务')
        return urlunsplit(('https',u.netloc.removesuffix(':80'),u.path,u.query,''))
    url=allowed(url)
    try:
        for _ in range(4):
            async with client.stream('GET',url,timeout=20,follow_redirects=False) as r:
                if r.is_redirect:url=allowed(urljoin(url,r.headers.get('location','')));continue
                if not r.is_success:raise SpeechError('语音下载失败或地址已过期')
                if r.headers.get('content-length','').isdigit() and int(r.headers['content-length'])>MAX_AUDIO:raise SpeechError('语音文件超过 6 MB')
                body=bytearray()
                async for c in r.aiter_bytes(65536):
                    body.extend(c)
                    if len(body)>MAX_AUDIO:raise SpeechError('语音文件超过 6 MB')
                if not body:raise SpeechError('语音文件为空')
                return bytes(body)
    except SpeechError:raise
    except Exception:raise SpeechError('语音下载失败或地址已过期') from None
    raise SpeechError('语音地址重定向次数过多')


def decode_audio(value):
    if not isinstance(value,str) or len(value)>MAX_OUTPUT*2:raise SpeechError('语音服务没有返回有效音频')
    try:
        data=base64.b64decode(value,validate=True)
        if not data or len(data)>MAX_OUTPUT:raise ValueError
        return data
    except ValueError:raise SpeechError('语音服务返回的音频编码无效') from None


async def synthesize(client,provider,model,text,voice='',speed=None,instructions='',timeout=60):
    if provider.purpose!='tts':raise SpeechError('请选择 TTS 供应商')
    if not model.strip() or not text.strip() or len(text)>2000:raise SpeechError('请填写模型及 1–2000 字的合成文字')
    voice=voice or provider.default_voice;speed=speed or provider.speech_speed
    instructions=instructions or provider.speech_instructions
    if provider.type in ('xiaomi_tts','gemini_tts') and speed!=1:instructions+=f'\n语速约为正常的 {speed:g} 倍。'
    kind=provider.type;h=headers(provider);base=provider.base_url;mime='audio/wav'
    if kind=='openai_tts':
        body={'model':model,'input':text,'voice':voice or 'alloy','response_format':'wav','speed':speed}
        if instructions:body['instructions']=instructions
        raw,mime=await bounded_response(client,'POST',endpoint(provider,'audio/speech'),headers=h,json=body,timeout=timeout)
    elif kind=='xiaomi_tts':
        body={'model':model,'messages':([{'role':'user','content':instructions}] if instructions else [])+[{'role':'assistant','content':text}],
              'audio':{'format':'wav','voice':voice or 'mimo_default'},'stream':False}
        data=await json_request(client,'POST',endpoint(provider,'chat/completions'),headers=h,json=body,timeout=timeout)
        try:value=data['choices'][0]['message']['audio']['data']
        except (KeyError,IndexError,TypeError):raise SpeechError('MiMo 未返回有效音频') from None
        raw=decode_audio(value)
    elif kind=='minimax_tts':
        if not voice:raise SpeechError('请填写 MiniMax 音色 ID')
        body={'model':model,'text':text,'stream':False,'output_format':'hex','voice_setting':{'voice_id':voice,'speed':speed},'audio_setting':{'sample_rate':24000,'format':'mp3','channel':1}}
        data=await json_request(client,'POST',endpoint(provider,'t2a_v2'),headers=h,json=body,timeout=timeout)
        try:raw=bytes.fromhex(data['data']['audio'])
        except (KeyError,TypeError,ValueError):raise SpeechError('MiniMax 未返回有效音频') from None
        mime='audio/mpeg'
    elif kind=='dashscope_tts':
        if not voice:raise SpeechError('请填写百炼音色')
        newer=model.startswith('qwen-audio')
        suffix='/services/audio/tts/SpeechSynthesizer' if newer else '/services/aigc/multimodal-generation/generation'
        body={'model':model,'input':{'text':text,'voice':voice,**({'format':'wav','rate':speed} if newer else {'language_type':'Auto'})}}
        data=await json_request(client,'POST',base+suffix,headers=h,json=body,timeout=timeout)
        audio=(data.get('output') or {}).get('audio') or {}
        if audio.get('data'):raw=decode_audio(audio['data'])
        elif audio.get('url'):raw=await fetch_audio(client,audio['url'])
        else:raise SpeechError('百炼未返回音频')
    elif kind=='azure_tts':
        if not voice:raise SpeechError('请填写 Azure 音色名称')
        language=provider.language if provider.language!='auto' else '-'.join(voice.split('-')[:2]) or 'zh-CN'
        rate=f'{round((speed-1)*100):+d}%'
        ssml=f'<speak version="1.0" xml:lang={quoteattr(language)}><voice name={quoteattr(voice)}><prosody rate={quoteattr(rate)}>{escape(text)}</prosody></voice></speak>'
        h={'Ocp-Apim-Subscription-Key':provider.api_key,'Content-Type':'application/ssml+xml','X-Microsoft-OutputFormat':'riff-24khz-16bit-mono-pcm','User-Agent':'HayBot'}
        raw,mime=await bounded_response(client,'POST',base+'/cognitiveservices/v1',headers=h,content=ssml.encode(),timeout=timeout)
    elif kind=='gemini_tts':
        from .gemini import model_url
        config={'responseModalities':['AUDIO'],'speechConfig':{'voiceConfig':({'voice':voice or 'Kore'} if re.match(r'gemini-(?:3\.[8-9]|[4-9])',model) else {'prebuiltVoiceConfig':{'voiceName':voice or 'Kore'}})}}
        data=await json_request(client,'POST',model_url(provider,model),headers=h,json={'contents':[{'parts':[{'text':(instructions+'\n' if instructions else '')+text}]}],'generationConfig':config},timeout=timeout)
        try:parts=data['candidates'][0]['content']['parts'];audio=next(p.get('inlineData',p.get('inline_data')) for p in parts if p.get('inlineData') or p.get('inline_data'))
        except (KeyError,IndexError,StopIteration,TypeError):raise SpeechError('Gemini 未返回音频') from None
        raw=decode_audio(audio.get('data'));mime=audio.get('mimeType',audio.get('mime_type','audio/L16;rate=24000'))
        if 'l16' in mime.lower() or 'pcm' in mime.lower():raw=pcm_wav(raw,int(re.search(r'rate=(\d+)',mime).group(1)) if re.search(r'rate=(\d+)',mime) else 24000);mime='audio/wav'
    elif kind=='volcengine_tts':
        if not voice:raise SpeechError('请填写火山引擎音色 ID')
        h={'X-Api-Key':provider.api_key,'X-Api-Resource-Id':provider.resource_id or 'seed-tts-2.0','X-Api-Request-Id':uuid.uuid4().hex}
        if provider.app_id:h={'X-Api-App-Id':provider.app_id,'X-Api-Access-Key':provider.api_key,**{k:v for k,v in h.items() if k!='X-Api-Key'}}
        body={'user':{'uid':'haybot'},'req_params':{'text':text,'speaker':voice,'audio_params':{'format':'mp3','sample_rate':24000,'speech_rate':round((speed-1)*100)}}}
        raw_lines,_=await bounded_response(client,'POST',base+'/api/v3/tts/unidirectional',headers=h,json=body,timeout=timeout)
        chunks=[];complete=False
        try:
            for line in raw_lines.splitlines():
                if not line.strip():continue
                item=json.loads(line)
                if item.get('code',0) not in (0,20000000):raise SpeechError('火山引擎语音合成失败，请核对音色和资源 ID')
                if item.get('data'):chunks.append(decode_audio(item['data']))
                if item.get('code')==20000000:complete=True
        except (ValueError,TypeError):raise SpeechError('火山引擎语音返回格式无效') from None
        if not complete:raise SpeechError('火山引擎语音合成未完整结束')
        raw=b''.join(chunks);mime='audio/mpeg'
    else:raise SpeechError('不支持的语音合成类型')
    if not raw or len(raw)>MAX_OUTPUT:raise SpeechError('语音服务未返回有效音频')
    return SpeechAudio(raw,mime.split(';')[0])


async def transcribe(client,provider,model,audio,language='auto',timeout=90,max_seconds=120):
    if provider.purpose!='stt':raise SpeechError('请选择 STT 供应商')
    if provider.type=='xiaomi_stt' and language not in ('auto','zh','en'):raise SpeechError('MiMo 识别语言请填写 auto、zh 或 en')
    if provider.type=='xfyun_stt' and language not in ('auto','zh','zh_cn'):raise SpeechError('讯飞星火当前接口使用中文识别，语言请填写 auto 或 zh')
    if not model:raise SpeechError('请填写识别模型')
    wav=await to_wav(audio,min(max_seconds,60 if provider.type=='xfyun_stt' else 120))
    if provider.type=='xfyun_stt':return await xfyun_transcribe(provider,wav,timeout)
    if provider.type=='xiaomi_stt':
        body={'model':model,'messages':[{'role':'user','content':[{'type':'input_audio','input_audio':{'data':'data:audio/wav;base64,'+base64.b64encode(wav).decode()}}]}],
              'asr_options':{'language':language},'stream':False}
        data=await json_request(client,'POST',endpoint(provider,'chat/completions'),headers=headers(provider),json=body,timeout=timeout)
        try:text=data['choices'][0]['message']['content']
        except (KeyError,IndexError,TypeError):raise SpeechError('识别服务未返回转写文字') from None
    else:
        fields={'model':model,'response_format':'json'}
        if language!='auto':fields['language']=language
        data=await json_request(client,'POST',endpoint(provider,'audio/transcriptions'),headers=headers(provider),data=fields,files={'file':('speech.wav',wav,'audio/wav')},timeout=timeout)
        text=data.get('text')
    if not isinstance(text,str) or not text.strip() or len(text)>12000:raise SpeechError('语音未识别出有效文字')
    return text.strip()


async def xfyun_transcribe(provider,wav,timeout):
    if not provider.app_id or not provider.api_key or not provider.api_secret:raise SpeechError('讯飞识别需要 AppID、APIKey 和 APISecret')
    u=urlsplit(provider.base_url);date=formatdate(usegmt=True)
    signature=base64.b64encode(hmac.new(provider.api_secret.encode(),f'host: {u.netloc}\ndate: {date}\nGET {u.path} HTTP/1.1'.encode(),hashlib.sha256).digest()).decode()
    authorization=base64.b64encode(f'api_key="{provider.api_key}", algorithm="hmac-sha256", headers="host date request-line", signature="{signature}"'.encode()).decode()
    url=provider.base_url+'?'+urlencode({'host':u.netloc,'date':date,'authorization':authorization})
    with wave.open(io.BytesIO(wav)) as w:pcm=w.readframes(w.getnframes())
    async def send(ws):
        for seq,offset in enumerate(range(0,len(pcm),1280),1):
            status=0 if offset==0 else 1
            packet={'header':{'app_id':provider.app_id,'status':status},'payload':{'audio':{'encoding':'raw','sample_rate':16000,'channels':1,'bit_depth':16,'seq':seq,'status':status,'audio':base64.b64encode(pcm[offset:offset+1280]).decode()}}}
            if offset==0:packet['parameter']={'iat':{'domain':'spark_asr_v2','language':'zh_cn','accent':'mandarin','dwa':'wpgs','result':{'encoding':'utf8','compress':'raw','format':'json'}}}
            await ws.send(json.dumps(packet));await asyncio.sleep(.04)
        await ws.send(json.dumps({'header':{'app_id':provider.app_id,'status':2},'payload':{'audio':{'encoding':'raw','sample_rate':16000,'channels':1,'bit_depth':16,'seq':seq+1,'status':2,'audio':''}}}))
    try:
        async with asyncio.timeout(timeout),connect(url,proxy=None,open_timeout=10,max_size=2*1024*1024) as ws:
            sender=asyncio.create_task(send(ws));pieces={};completed=False
            try:
                async for raw in ws:
                    item=json.loads(raw);header=item.get('header') or {}
                    if header.get('code',0):raise SpeechError('讯飞语音识别失败，请检查鉴权与服务额度')
                    result=(item.get('payload') or {}).get('result') or {}
                    if result.get('text'):
                        decoded=json.loads(base64.b64decode(result['text'],validate=True))
                        if decoded.get('ret',0):raise SpeechError('讯飞未成功识别音频')
                        if result.get('pgs',decoded.get('pgs'))=='rpl':
                            rg=result.get('rg',decoded.get('rg',[]))
                            if len(rg)==2:pieces={k:v for k,v in pieces.items() if not rg[0]<=k<=rg[1]}
                        pieces[int(decoded.get('sn',result.get('seq',0)))]= ''.join((p.get('cw') or [{}])[0].get('w','') for p in decoded.get('ws',[]))
                    if header.get('status')==2:completed=True;break
                if not completed or not ''.join(pieces.values()).strip():raise SpeechError('讯飞未返回完整转写结果')
                return ''.join(pieces[k] for k in sorted(pieces))
            finally:sender.cancel();await asyncio.gather(sender,return_exceptions=True)
    except SpeechError:raise
    except Exception:raise SpeechError('讯飞语音识别未完成，请检查连接与凭证') from None


class SpeechService:
    def __init__(self,bot):
        import contextvars
        self.bot=bot;self.lock=asyncio.Lock()
        self.last_transcripts=contextvars.ContextVar('transcripts_'+str(id(self)),default=[])

    async def listen(self,attachments,config,group=False):
        selection=config.speech.stt
        if not selection.enabled or not selection.auto_transcribe or group and selection.scope!='private_and_group':
            raise SpeechError('这条语音我暂时听不了，发文字给我吧。')
        provider=self.bot.provider(selection);texts=[];self.last_transcripts.set([])
        try:
            async with self.lock:
                for attachment in attachments:
                    raw=await fetch_audio(self.bot.client,attachment.get('url',''),qq=True)
                    text=await transcribe(self.bot.client,provider,selection.model,raw,selection.language,max_seconds=selection.max_audio_seconds)
                    texts.append((attachment.get('_source_message_id',''),text))
        except (ProviderHTTPError,httpx.HTTPError):
            raise SpeechError('这条语音暂时没听清，发文字给我，或稍后再试吧。') from None
        self.last_transcripts.set(texts)
        return '\n'.join(text for _,text in texts)

    async def speak(self,text,config,*,style=None):
        selection=config.speech.tts
        if not selection.enabled or len(text)>selection.max_reply_chars:raise SpeechError('本轮使用文字回复')
        async with self.lock:
            provider=self.bot.provider(selection)
            speed=selection.speed
            instructions=provider.speech_instructions
            if style:
                speed=max(.5,min(2.,speed*style['speed_factor']))
                if provider.type in ('openai_tts','xiaomi_tts','gemini_tts'):
                    instructions+='\n'+style['delivery']
            try:
                result=await synthesize(self.bot.client,provider,selection.model,text,selection.voice,speed,instructions=instructions)
            except (SpeechError,ProviderHTTPError,httpx.HTTPError):
                if not style:raise
                self.bot.store.log('warn','情感语音风格不可用，尝试普通语音',category='message',event='emotion.voice_fallback')
                result=await synthesize(self.bot.client,provider,selection.model,text,selection.voice,selection.speed)
            return await to_silk(result.data)
