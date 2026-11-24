import asyncio
from types import SimpleNamespace

import pytest

from yuiro.audio.bilingual import PairParser, experiment_allowed, generate_pairs
from yuiro.runtime.trace import TraceContext


def test_gate_default_off_and_respects_existing_role_language():
    assert not experiment_allowed('ja_first', None, 'ja')
    assert not experiment_allowed('ja_first', '1', 'zh')
    assert not experiment_allowed('unknown', '1', 'ja')
    assert experiment_allowed('ja_first', '1', 'ja')
    assert experiment_allowed('baseline', '1', 'zh')


@pytest.mark.parametrize('order,line', [
    ('ja_first', '{"ja":"疲れたね。ひと休みしよう。","zh":"累了吧，休息一下。"}'),
    ('zh_first', '{"zh":"累了吧，休息一下。","ja":"疲れたね。ひと休みしよう。"}')])
def test_every_token_boundary_and_escaped_quotes_pair_safety(order, line):
    for split in range(len(line)+1):
        parser = PairParser(order)
        pairs = parser.feed(line[:split]) + parser.feed(line[split:], final=True)
        assert len(pairs) == 1
        assert pairs[0]['zh'] == '累了吧，休息一下。'
    parser = PairParser(order)
    assert len([p for char in line+'\n'+line+'\n' for p in parser.feed(char)]) == 2


@pytest.mark.parametrize('line', [
    '{"ja":"こんにちは。","ja":"さようなら。","zh":"你好。"}',
    '{"ja":"<emotion>こんにちは。","zh":"你好。"}',
    '{"ja":"[motion:happy]こんにちは。","zh":"你好。"}',
    '{"ja":"tool:こんにちは。","zh":"你好。"}',
    '{"ja":"JA:こんにちは。","zh":"你好。"}',
    '{"ja":"tool_call:こんにちは。","zh":"你好。"}',
    '{"ja":1,"zh":"你好。"}', '{"ja":"你好。","zh":"你好。"}',
    '{"ja":"こんにちは","zh":"你好。"}',
    '```json', '{"zh":"你好。","ja":"こんにちは。"}',
    '{"ja":"こんにちは。","zh":"你好。","tool":"delete"}',
    '{"ja":"こんにちは。","zh":"你好。"',
])
def test_fail_closed_formats(line):
    with pytest.raises(ValueError):
        PairParser('ja_first').feed(line, final=True)


def test_ready_japanese_is_observed_but_never_delivered_without_pair():
    parser = PairParser('ja_first')
    assert parser.feed('{"ja":"こんにちは。",') == []
    assert parser.ja_ready
    assert parser.feed('"zh":"你好。"}\n') == [{'ja':'こんにちは。', 'zh':'你好。'}]
    with pytest.raises(ValueError):
        parser.feed('x'*4097)


def test_complete_pair_delivers_at_closing_brace_without_waiting_for_newline():
    parser = PairParser('ja_first')
    assert parser.feed('{"ja":"彼は\\"おはよう\\"と言ったね。","zh":"他说了\\"早上好\\"。"}') == [
        {'ja':'彼は"おはよう"と言ったね。', 'zh':'他说了"早上好"。'}]
    assert parser.feed('', final=True) == []


@pytest.mark.asyncio
async def test_cancel_closes_stream_no_pair_delivery_or_cross_turn_state():
    closed = asyncio.Event()
    release = asyncio.Event()
    delivered = []
    class LLM:
        async def stream_text(self, *args, **kwargs):
            try:
                yield SimpleNamespace(kind='token', content='{"ja":"こんにちは。",')
                await release.wait()
                yield SimpleNamespace(kind='token', content='"zh":"你好。"}\n')
            finally:
                closed.set()
    async def deliver(pair):
        delivered.append(pair)
    task = asyncio.create_task(generate_pairs(LLM(), '', '你好', 'ja_first', deliver,
        lambda:None, TraceContext(session_id='test', mode='chat'), {}))
    await asyncio.sleep(.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert closed.is_set() and not delivered


@pytest.mark.asyncio
@pytest.mark.parametrize('stale', [True, False])
async def test_stale_generation_or_tool_chunk_never_delivers(stale):
    delivered, closed = [], []
    class LLM:
        async def stream_text(self, *args, **kwargs):
            try:
                yield SimpleNamespace(kind='tool_call', tool_name='delete')
            finally:
                closed.append(True)
    async def deliver(pair):
        delivered.append(pair)
    def check():
        if stale:
            raise asyncio.CancelledError('role switched')
    with pytest.raises(asyncio.CancelledError if stale else ValueError):
        await generate_pairs(LLM(), '', '', 'ja_first', deliver, check,
                             TraceContext(session_id='test', mode='chat'), {})
    assert closed and not delivered
