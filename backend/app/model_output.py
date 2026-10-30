"""Shared model-output sanitation and duplicate JSON field detection."""
import re


def public_body(raw):
    if not isinstance(raw,str):return ''
    if '<think>' in raw and '</think>' not in raw:return '[未闭合的思考块，内容已隐藏]'
    return re.sub(r'<think>.*?</think>','',raw,flags=re.S).strip()


def unique_object(pairs):
    result={}
    for key,value in pairs:
        if key in result:raise ValueError('JSON字段重复：'+key[:40])
        result[key]=value
    return result
