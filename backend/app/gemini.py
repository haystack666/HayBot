"""Gemini generateContent transport, including inline image inputs."""
from urllib.parse import quote
from .providers import headers


def model_url(provider, model):
    return provider.base_url+'/models/'+quote(model.removeprefix('models/'),safe='')+':generateContent'


async def generate_content(request, provider, selection, messages, max_tokens):
    system=[];contents=[]
    for message in messages:
        if message['role']=='system':system.append(message['content']);continue
        parts=[{'text':message['content']}]
        parts.extend({'inlineData':{'mimeType':'image/jpeg','data':image}} for image in message.get('images',[]))
        role='model' if message['role']=='assistant' else 'user'
        if contents and contents[-1]['role']==role:contents[-1]['parts'].extend(parts)
        else:contents.append({'role':role,'parts':parts})
    generation={'maxOutputTokens':max_tokens}
    if provider.send_temperature:generation['temperature']=selection.temperature
    body={'contents':contents,'generationConfig':generation}
    if system:body['systemInstruction']={'parts':[{'text':'\n'.join(system)}]}
    data=await request('POST',model_url(provider,selection.model),headers=headers(provider),timeout=selection.timeout,json=body)
    candidates=data.get('candidates') or []
    parts=(candidates[0].get('content') or {}).get('parts',[]) if candidates else []
    text='\n'.join(p['text'] for p in parts if isinstance(p,dict) and isinstance(p.get('text'),str) and not p.get('thought'))
    usage=data.get('usageMetadata') or {}
    return {'message':{'content':text},'prompt_eval_count':usage.get('promptTokenCount',0),'eval_count':usage.get('candidatesTokenCount',0)}
