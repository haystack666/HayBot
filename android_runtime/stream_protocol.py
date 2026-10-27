"""Small, pinned scrcpy3.3.4 wire subset. Also copied to the dedicated guest."""
import struct
MAX_FRAME=4*1024*1024
KEYS={'home':3,'back':4,'recent':187,'enter':66,'delete':67,'space':62,'tab':61,'left':21,'right':22,'up':19,'down':20}

def validate_input(value):
    if not isinstance(value,dict):raise ValueError('输入格式无效')
    kind=value.get('type')
    fields={'pointer':{'type','action','x','y','width','height'},'key':{'type','action','key'},'text':{'type','text'}}
    if kind not in fields or set(value)-fields[kind]:raise ValueError('不支持的控制消息')
    if kind=='pointer':
        if value.get('action') not in ('down','move','up','cancel'):raise ValueError('触摸动作无效')
        if any(type(value.get(k)) is not int for k in ('x','y','width','height')):raise ValueError('坐标必须为整数')
        if not (1<=value['width']<=2560 and 1<=value['height']<=2560 and 0<=value['x']<value['width'] and 0<=value['y']<value['height']):raise ValueError('触摸位置超出画面')
    elif kind=='key':
        if value.get('key') not in KEYS or value.get('action') not in ('down','up'):raise ValueError('按键无效')
    elif not isinstance(value.get('text'),str) or not 1<=len(value['text'])<=2000 or '\0' in value['text']:raise ValueError('输入文字长度无效')
    return dict(value)

def control_packet(value):
    value=validate_input(value)
    if value['type']=='pointer':
        action={'down':0,'up':1,'move':2,'cancel':3}[value['action']]
        return struct.pack('>BBqiiHHHii',2,action,-2,value['x'],value['y'],value['width'],value['height'],0 if action in (1,3) else 65535,0,0)
    if value['type']=='key':return struct.pack('>BBiii',0,int(value['action']=='up'),KEYS[value['key']],0,0)
    text=value['text'].encode('utf8')
    # SET_CLIPBOARD, sequence0, paste=true. Clipboard reads/autosync are disabled.
    return struct.pack('>BQB I',9,0,1,len(text))+text

def frame_info(raw):
    if len(raw)<12:raise ValueError('视频帧头不完整')
    flags,size=struct.unpack('>QI',raw[:12])
    if not 0<size<=MAX_FRAME or len(raw)!=12+size:raise ValueError('视频帧长度无效')
    return {'config':bool(flags&(1<<63)),'keyframe':bool(flags&(1<<62)),'pts':flags&((1<<62)-1),'size':size}
