import pytest
from app.android_decisions import parse_decision, DecisionFormatError

@pytest.mark.parametrize('raw', [
    '{"action":{"kind":"tap","x":12,"y":34},"reason":"open"}',
    '```json\n{"done":true,"result":"visible"}\n```',
    '<think>analysis</think>\n{"blocked":true,"result":"captcha"}',
    '下一步：\n{"action":{"kind":"key","key":"home"}}',
])
def test_valid_decisions_and_unambiguous_wrappers(raw):
    assert isinstance(parse_decision(raw),dict)

@pytest.mark.parametrize('raw', ['', 'I cannot provide JSON', '{"action":',
    '{"action":{"kind":"swipe","x":1,"y":2,"x2":3}}',
    '{"action":{"kind":"tap","x":1}}',
    '{"action":{"kind":"shell","text":"id"}}',
    '{"done":true,"result":"ok","action":{"kind":"key","key":"home"}}',
    '{}', '{"done":true,"result":"a"} {"done":true,"result":"b"}',
    '<think>unfinished {"done":true,"result":"fake"}',
])
def test_invalid_or_ambiguous_decisions_do_not_become_actions(raw):
    with pytest.raises(DecisionFormatError):parse_decision(raw)

@pytest.mark.parametrize('raw',['{"wrapper":{"action":{"kind":"key","key":"home"}}','[{"action":{"kind":"key","key":"home"}}]'])
def test_truncated_outer_object_and_array_never_execute_nested_decision(raw):
    with pytest.raises(DecisionFormatError):parse_decision(raw)
