"""A transport-independent view of dialogue, parenthetical actions and vocal style."""
from dataclasses import dataclass
from .speech import split_voice_actions, SpeechError


@dataclass(frozen=True)
class ReplyExpression:
    original: str
    dialogue: str
    actions: str
    style: dict | None
    balanced: bool

    @classmethod
    def parse(cls, text, style=None):
        try:
            actions, dialogue = split_voice_actions(text)
            return cls(text, dialogue, actions, style, True)
        except SpeechError:
            return cls(text, text, '', style, False)

    def public_metadata(self):
        return {'balanced_actions': self.balanced, 'has_actions': bool(self.actions),
                'style': self.style['name'] if self.style else '原有表达'}
