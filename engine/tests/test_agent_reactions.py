"""真实工具结果驱动互动；边界测试不启动引擎/不调用供应商。"""
import ast
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_s39_feedback import _Registry, _ScriptLLM

from yuiro import approval
from yuiro.agent import AgentLoop
from yuiro.agent.activity import activity_outcome
from yuiro.runtime.events import AgentEvent, EventBus


@pytest.mark.parametrize(('statuses', 'expected'), [
    (['ok', 'success'], 'success'), (['ok', 'error'], 'error'),
    (['need_choice', 'ok'], 'waiting'), (['pending'], 'waiting'),
    (['done'], 'unknown'), ([], 'unknown'), (['mystery'], 'unknown'),
])
def test_result_classification_is_conservative(statuses, expected):
    assert activity_outcome([json.dumps({'status': s}) for s in statuses]) == expected
    assert activity_outcome(['not json', '[]']) == 'unknown'


@pytest.mark.asyncio
@pytest.mark.parametrize('status', ['ok', 'error', 'need_choice'])
async def test_real_agent_emits_paired_actual_result(status):
    class Registry(_Registry):
        async def execute(self, *args, **kwargs):
            return json.dumps({'status': status})

    events = EventBus()
    seen = []

    async def observe(event):
        seen.append(event)

    events.subscribe('agent.activity', observe)
    loop = AgentLoop(llm=_ScriptLLM([{'tool': 'web_search'}, {'token': '处理结果。'}]),
                     tools_registry=Registry(), memory_retriever=None, events=events, history_inject=False)
    async for _ in loop.send('s', '查询一下'):
        pass
    assert [e.payload['stage'] for e in seen] == ['tool', 'tool_result']
    assert seen[0].payload['activity_id'] == seen[1].payload['activity_id']
    assert seen[1].payload['outcome'] == {'ok': 'success', 'error': 'error', 'need_choice': 'waiting'}[status]


@pytest.mark.asyncio
async def test_activity_bridge_rejects_old_generation_and_switching(monkeypatch):
    sent = []

    async def broadcast(message):
        sent.append(message)

    monkeypatch.setattr(approval, 'broadcast_control', broadcast)
    session = SimpleNamespace(generation=4)
    service = SimpleNamespace(switching=False, revision=8)
    state = SimpleNamespace(sessions=SimpleNamespace(get=lambda sid: session), characters=service,
                            app_config=SimpleNamespace(_character_id='hotaru'))
    node = next(n for n in ast.parse(Path('yuiro/main.py').read_text(encoding='utf-8')).body
                if isinstance(n, ast.AsyncFunctionDef) and n.name == '_push_agent_activity')
    scope = {'app': SimpleNamespace(state=state)}
    exec(compile(ast.Module(body=[node], type_ignores=[]), 'production activity bridge', 'exec'), scope)  # noqa: S102
    event = AgentEvent(type='agent.activity', source='test', session_id='s', generation=3,
                       payload={'activity_id': 'a', 'stage': 'tool_result', 'outcome': 'success'})
    await scope['_push_agent_activity'](event)
    assert not sent
    event.generation = 4
    service.switching = True
    await scope['_push_agent_activity'](event)
    assert not sent
    service.switching = False
    await scope['_push_agent_activity'](event)
    assert sent[0]['character_id'] == 'hotaru' and sent[0]['generation'] == 4
    assert sent[0]['session_id'] == 's' and sent[0]['character_revision'] == 8
