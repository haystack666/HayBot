"""Separate model transport envelopes from visible chat before splitting bubbles."""
from dataclasses import dataclass
import json
import re


FIELDS = {'reply', 'schedule_update', 'meme_id'}
CONTROL_FIELDS = {'schedule_update', 'meme_id'}
KEY = re.compile(r'''["'](?:reply|schedule_update|meme_id)["']\s*:''')
FRAGMENT = re.compile(r'''(?:^|\n|,)\s*["'](?:schedule_update|meme_id)["']\s*:''')
FENCE = re.compile(r'\A```(?:json)?\s*([\s\S]*?)\s*```\Z', re.I)


@dataclass
class ReplyEnvelope:
    value: dict
    mixed: bool = False
    complete: bool = True
    suffix: str = ''


def is_envelope(value, expected):
    return isinstance(value, dict) and (bool(CONTROL_FIELDS.intersection(value)) or
        'reply' in value and (expected or set(value).issubset(FIELDS)))


def extract_envelope(raw, *, expected=False):
    text = raw.strip()
    if not KEY.search(text):
        return None
    fence = FENCE.fullmatch(text)
    if fence:
        text = fence[1].strip()
    try:
        value = json.loads(text)
    except ValueError:
        pass
    else:
        if is_envelope(value, expected):
            return ReplyEnvelope(value)
        if isinstance(value, (dict, list)) and any('"' + key + '"' in text for key in CONTROL_FIELDS):
            raise ValueError('回复包含不支持的嵌套传输结构')
        return None

    decoder = json.JSONDecoder()
    found, broken = [], []
    for count, match in enumerate(re.finditer(r'\{', text)):
        if count >= 64:
            raise ValueError('回复结构过于复杂，停止发送')
        start = match.start()
        if any(left <= start < right for left, right, _ in found):
            continue
        try:
            value, end = decoder.raw_decode(text, start)
        except ValueError:
            # An incomplete envelope must not be passed through as ordinary text.
            if KEY.search(text[start:start + 512]):
                broken.append(start)
        else:
            if is_envelope(value, expected):
                found.append((start, end, value))
    if len(found) == 1 and not broken:
        _, end, value = found[0]
        return ReplyEnvelope(value, mixed=True, suffix=text[end:].strip())
    if found:
        raise ValueError('回复包含多个或不完整的传输对象')
    fragment = FRAGMENT.search(text)
    if fragment:
        broken.append(fragment.start())
    if broken:
        prefix = text[:min(broken)].rstrip().removesuffix('```json').removesuffix('```').strip()
        if prefix:
            # Recover already complete public prose, but never act on partial metadata.
            return ReplyEnvelope({'reply': prefix}, mixed=True, complete=False)
        raise ValueError('回复结构不完整')
    return None


def public_reply(raw, *, history=False, depth=0):
    parsed = extract_envelope(raw)
    if parsed is None:
        return raw.strip()
    reply = parsed.value.get('reply')
    if not isinstance(reply, str) or not reply.strip() or depth >= 3:
        raise ValueError('回复没有有效正文')
    # Some models put a second envelope inside the reply string itself.
    result = public_reply(reply, history=history, depth=depth + 1)
    if history and parsed.suffix.startswith('[发送表情包：'):
        result += '\n' + parsed.suffix
    return result
