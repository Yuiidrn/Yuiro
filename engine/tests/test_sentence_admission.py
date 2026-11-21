"""实际流式首句闭包回归；避免导入main启动引擎。"""
import ast
import asyncio
import importlib.util
import json
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from yuiro.audio.speech_text import sentence_boundary

_SCRIPT = Path(__file__).resolve().parents[2] / 'scripts/diag/tts_sentence_admission.py'
_SPEC = importlib.util.spec_from_file_location('sentence_admission_diag', _SCRIPT)
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)


def drain():
    return _MODULE.production_drain(Path('yuiro/main.py'))


def test_short_prefix_does_not_block_later_sentence_until_eof():
    push = drain()
    assert push('嗯。') == []
    assert push('我正在帮你核对这件事情。') == ['嗯。我正在帮你核对这件事情。']
    assert push('后面的内容还没有生成完') == []
    assert push('', flush=True) == ['后面的内容还没有生成完']


def test_multiple_short_prefixes_merge_without_loss():
    push = drain()
    parts = ['嗯。', '好。', '我接着详细说明。']
    output = []
    for part in parts:
        output.extend(push(part))
    assert ''.join(output) == ''.join(parts)
    assert len(output) == 1
    assert not push('', flush=True)


def test_first_threshold_switches_inside_same_token_chunk():
    push = drain()
    assert push('我来看看吧。稍等一下。') == ['我来看看吧。']
    assert push('这一段是之后的解释。') == ['稍等一下。这一段是之后的解释。']


def test_default_boundary_behavior_and_url_protection_remain():
    text = '嗯。链接https://example.com/a?q=1;page=2 后续说明已经完成。'
    assert sentence_boundary(text) == 1
    assert sentence_boundary(text, min_len=6) == len(text) - 1
    push = drain()
    assert push(text) == [text]
    assert push('', flush=True) == []


def test_no_punctuation_does_not_cut_words_to_force_latency():
    push = drain()
    text = '一段尚未出现自然句界的完整内容'
    assert push(text) == []
    assert push('', flush=True) == [text]


@pytest.mark.asyncio
@pytest.mark.parametrize('cancel', [False, True])
async def test_actual_agent_reply_delivers_before_generation_finishes(monkeypatch, cancel):
    from yuiro.netease import official_client

    async def no_media(*args):
        return None

    monkeypatch.setattr(official_client, 'control_text', no_media)
    admitted, finish = asyncio.Event(), asyncio.Event()
    sentences = []

    class Loop:
        async def send(self, *args, **kwargs):
            yield SimpleNamespace(kind='token', content='嗯。')
            yield SimpleNamespace(kind='token', content='我正在帮你核对这件事情。')
            await finish.wait()
            yield SimpleNamespace(kind='token', content='接下来是补充说明。')

    async def receive(text):
        sentences.append(text)
        admitted.set()

    scope = {'TraceContext': object, 'app': SimpleNamespace(state=SimpleNamespace(agent_loop=Loop())),
             '_media_identity': lambda sid: {}, '_interaction_reward': no_media,
             'vlog': lambda *args: None, 'time': time, 'json': json}
    node = next(n for n in ast.parse(Path('yuiro/main.py').read_text(encoding='utf-8')).body
                if isinstance(n, ast.AsyncFunctionDef) and n.name == '_agent_reply')
    exec(compile(ast.Module(body=[node], type_ignores=[]), 'actual _agent_reply', 'exec'), scope)  # noqa: S102
    task = asyncio.create_task(scope['_agent_reply']('测试问题', 's', on_sentence=receive))
    try:
        await asyncio.wait_for(admitted.wait(), 1)
        assert sentences == ['嗯。我正在帮你核对这件事情。']
        assert not task.done(), '首句必须早于LLM完成交付'
        if cancel:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert len(sentences) == 1
        else:
            finish.set()
            reply = await asyncio.wait_for(task, 1)
            assert ''.join(sentences) == reply
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
