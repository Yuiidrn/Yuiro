import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from yuiro.diary.companion import DiaryCompanion


@pytest.mark.asyncio
async def test_companion_persona_memory_and_own_history_only():
    calls=[]
    class Provider:
        async def stream_text(self, messages, **kwargs):
            calls.append(messages)
            yield SimpleNamespace(kind='token', content='我听着呢。')
    memory=SimpleNamespace(retrieve=AsyncMock(return_value=[SimpleNamespace(text='用户喜欢猫')]))
    session=DiaryCompanion()
    for kind in ['short','paragraph']:
        assert await session.respond('今天见到了猫',kind=kind,llm=Provider(),persona='温柔角色',memory=memory)
    assert len(calls[0])==3
    assert '温柔角色' in calls[0][0]['content']
    assert '用户喜欢猫' in calls[0][1]['content']
    assert len(calls[1])==5
    assert len(session.history)==4


@pytest.mark.asyncio
async def test_cancelled_reply_never_enters_history():
    entered=asyncio.Event()
    class Provider:
        async def stream_text(self,*args,**kwargs):
            entered.set()
            yield SimpleNamespace(kind='token',content='半句')
            await asyncio.sleep(60)
    session=DiaryCompanion()
    task=asyncio.create_task(session.respond('正文',kind='short',llm=Provider(),persona='人设'))
    await entered.wait();task.cancel()
    with pytest.raises(asyncio.CancelledError):await task
    assert not session.history


@pytest.mark.asyncio
@pytest.mark.parametrize('tts', ['rejected','missing','ok'])
async def test_tts_failure_keeps_text_and_returns_specific_status(monkeypatch,tts):
    import yuiro.main as main
    from yuiro.diary.session import DiarySession
    class Provider:
        async def stream_text(self,*args,**kwargs):
            yield SimpleNamespace(kind='token',content='我听着呢。')
    session=DiarySession();session.start()
    synth=AsyncMock(side_effect=RuntimeError('Fish HTTP 403；请检查密钥、额度和音色权限')) if tts=='rejected' else AsyncMock(return_value=SimpleNamespace(wav=b'test'))
    monkeypatch.setattr(main.app.state,'diary_session',session,raising=False)
    monkeypatch.setattr(main.app.state,'agent_loop',SimpleNamespace(_llm=Provider()),raising=False)
    monkeypatch.setattr(main.app.state,'app_config',SimpleNamespace(persona=SimpleNamespace(persona_prompt='人设')),raising=False)
    monkeypatch.setattr(main.app.state,'memory',None,raising=False)
    monkeypatch.setattr(main.app.state,'voice_pipeline',SimpleNamespace(_tts=None if tts=='missing' else SimpleNamespace(synthesize_segment=synth)),raising=False)
    ws=SimpleNamespace(state=SimpleNamespace(),send_json=AsyncMock())
    await main._handle_diary_message(ws,'test',{'type':'diary:interact','request_id':1,'text':'今天的记录','tts':True})
    messages=[call.args[0] for call in ws.send_json.await_args_list]
    assert messages[0]['type']=='diary:response' and messages[0]['text']=='我听着呢。'
    assert messages[-1]['type']=='diary:response_end'
    if tts=='rejected':assert '403' in messages[-1]['note']
    elif tts=='missing':assert '尚未就绪' in messages[-1]['note']
    else:assert any(m['type']=='diary:audio' for m in messages)


@pytest.mark.asyncio
async def test_shared_speech_path_applies_configured_spoken_language(monkeypatch):
    import yuiro.main as main
    renderer=SimpleNamespace(render_speak=AsyncMock(return_value='こんにちは。'))
    provider=SimpleNamespace(synthesize_segment=AsyncMock(return_value=SimpleNamespace(wav=b'audio')))
    monkeypatch.setattr(main.app.state,'output_renderer',renderer,raising=False)
    result=await main._synthesize_reply_sentence(provider,'你好。')
    renderer.render_speak.assert_awaited_once_with('你好。')
    provider.synthesize_segment.assert_awaited_once_with('こんにちは。')
    assert result.wav==b'audio'
