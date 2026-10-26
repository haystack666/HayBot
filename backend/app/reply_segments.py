"""Natural boundaries only: retain URLs/code and never drop the remaining text."""
import math
import re


PROTECTED = re.compile(r'```[\s\S]*?(?:```|\Z)|~~~[\s\S]*?(?:~~~|\Z)|`[^`\n]+`|\[[^\]\n]*\]\([^\s]+\)|https?://[^\s<>]+')
BOUNDARY = re.compile(r'\n+|[。！？!?]+[”’」』）】\"]*|(?<=\.)\s+|…{2,}')


def split_reply(text, target=100, maximum=4):
    text = text.strip()
    if not text:
        return []
    if maximum <= 1 or len(text) <= target:
        return [text]
    protected = [match.span() for match in PROTECTED.finditer(text)]
    boundaries = [match.end() for match in BOUNDARY.finditer(text)
                  if not any(left < match.end() < right for left, right in protected)]
    boundaries = sorted(set([*boundaries, len(text)]))
    target = max(target, math.ceil(len(text) / maximum))
    parts, start = [], 0
    while start < len(text):
        if len(parts) == maximum - 1 or len(text) - start <= target:
            end = len(text)
        else:
            candidates = [end for end in boundaries if end > start and text[start:end].strip()]
            nearby = [end for end in candidates if .6 * target <= end - start <= 1.4 * target]
            paragraphs = [end for end in nearby if text[max(start, end-2):end] == '\n\n']
            end = min(paragraphs or nearby or candidates, key=lambda end: abs(end - start - target))
        part = text[start:end].strip()
        if part:
            parts.append(part)
        start = end
    return parts
