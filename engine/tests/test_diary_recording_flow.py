import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from yuiro.diary.session import DiarySession

@pytest.mark.asyncio
async def test_raw_save_does_not_deconstruct_and_resets_only_on_success():
 service=SimpleNamespace(submit=AsyncMock(side_effect=[{'ok':False},{'ok':True}]),deconstruct=AsyncMock())
 session=DiarySession(service=service);session.start();session.append('今天写完了')
 assert not (await session.save_raw())['ok']
 assert session.draft()=='今天写完了'
 assert (await session.save_raw())['ok']
 service.deconstruct.assert_not_called()
 service.submit.assert_awaited_with('今天写完了',privacy='local_only',quip_mode=False,data={})
 assert not session.active and not session.draft()

@pytest.mark.asyncio
async def test_stale_preview_does_not_replace_changed_draft():
 entered=asyncio.Event();finish=asyncio.Event()
 async def deconstruct(text):entered.set();await finish.wait();return {'polished_text':'old'}
 session=DiarySession(service=SimpleNamespace(deconstruct=deconstruct));session.start();session.append('before')
 task=asyncio.create_task(session.preview());await entered.wait();session.append('after');finish.set()
 assert not (await task)['ok'] and session._pending is None

@pytest.mark.asyncio
async def test_failed_confirm_retains_preview_for_retry():
 service=SimpleNamespace(deconstruct=AsyncMock(return_value={'polished_text':'整理'}),submit=AsyncMock(side_effect=[{'ok':False},{'ok':True}]))
 session=DiarySession(service=service);session.start();session.append('原文');await session.preview()
 assert not (await session.confirm())['ok']
 assert session._pending and session.draft()=='原文'
 assert (await session.confirm())['ok'] and session._pending is None

@pytest.mark.asyncio
async def test_duplicate_raw_submit_is_rejected_while_inflight():
 entered=asyncio.Event();finish=asyncio.Event()
 async def submit(*a,**k):entered.set();await finish.wait();return {'ok':True}
 session=DiarySession(service=SimpleNamespace(submit=submit));session.start();session.append('one')
 first=asyncio.create_task(session.save_raw());await entered.wait()
 assert not (await session.save_raw())['ok']
 with pytest.raises(RuntimeError):session.append('two')
 finish.set();assert (await first)['ok']

@pytest.mark.asyncio
async def test_literal_diary_text_and_reconnect_preserve_draft(monkeypatch):
 import yuiro.main as main
 session=DiarySession(service=SimpleNamespace(submit=AsyncMock(return_value={'ok':True})))
 monkeypatch.setattr(main.app.state,'diary_session',session,raising=False)
 monkeypatch.setattr(main,'app_config',SimpleNamespace(diary=SimpleNamespace(quip_default_on=False,review_enabled=True)))
 class Socket:
  def __init__(self):self.messages=[]
  async def send_json(self,msg):self.messages.append(msg)
 ws=Socket()
 await main._handle_diary_message(ws,'test',{'type':'diary:start'})
 await main._handle_diary_message(ws,'test',{'type':'diary:append','text':'写完了','literal':True})
 assert session.active and session.draft()=='写完了'
 await main._handle_diary_message(ws,'test',{'type':'diary:start'})
 assert session.draft()=='写完了'
 review=AsyncMock();monkeypatch.setattr(main,'_maybe_closing_review',review)
 await main._handle_diary_message(ws,'test',{'type':'diary:save_raw','privacy':'local_only'})
 assert ws.messages[-1]['type']=='diary:submitted' and ws.messages[-1]['ok']
 review.assert_not_called()
