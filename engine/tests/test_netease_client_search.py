import asyncio
import json
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock
import pytest
from yuiro.native import netease_client as native
from yuiro.netease import official_client as client
from yuiro.tools.netease_client_search import NeteaseClientSearchTool


@pytest.mark.asyncio
async def test_client_search_confirms_query_and_stable_ids(monkeypatch):
    @asynccontextmanager
    async def connection():
        yield object()
    calls=[]
    snapshots=iter([{'keyword':'previous','items':[{'song_id':'999'}]},
                    {'keyword':'Monody','items':[{'song_id':'36308916','name':'Monody','artist':'TheFatRat'}]},
                    {'keyword':'Monody','items':[{'song_id':'36308916','name':'Monody','artist':'TheFatRat'}]}])
    async def rpc(ws,method,params,request_id=1):
        calls.append((method,params))
        if params.get('expression')==native._SEARCH_ROWS:
            return {'result':{'value':next(snapshots)}}
        return {}
    monkeypatch.setattr(native,'_connection',connection)
    monkeypatch.setattr(native,'_rpc',rpc)
    monkeypatch.setattr(native,'_search_lock',asyncio.Lock())
    monkeypatch.setattr(native.asyncio,'sleep',AsyncMock())
    result=await native.search('Monody',1)
    assert result['source']=='netease_client_ui'
    assert result['items'][0]['song_id']=='36308916'
    assert ('Input.insertText',{'text':'Monody'}) in calls


@pytest.mark.asyncio
@pytest.mark.parametrize('keyword',['','x'*101,'a\nb'])
async def test_invalid_query_never_opens_client(monkeypatch,keyword):
    opened=AsyncMock()
    monkeypatch.setattr(native,'_connection',opened)
    with pytest.raises(ValueError):
        await native.search(keyword)
    opened.assert_not_called()


@pytest.mark.asyncio
async def test_search_epoch_and_tool_identity_discard_old_results(monkeypatch):
    monkeypatch.setattr(client,'_epoch',0)
    monkeypatch.setattr(client,'_query_gate',asyncio.Lock())
    async def changed(*a,**kw):
        client.invalidate()
        return {'status':'ok','items':[{'song_id':'36308916'}]}
    monkeypatch.setattr(client,'_call',changed)
    tool=NeteaseClientSearchTool(lambda sid:('hiyori',1,sid))
    result=json.loads(await tool.run({'keyword':'Monody'},'s1'))
    assert result['status']=='error' and result['fallback'] is False
    assert 'items' not in result
    assert tool.requires_env is None


@pytest.mark.asyncio
async def test_cancellation_propagates_without_api_fallback(monkeypatch):
    async def cancelled(*a,**kw):
        raise asyncio.CancelledError()
    monkeypatch.setattr(client,'search',cancelled)
    tool=NeteaseClientSearchTool(lambda sid:('hotaru',2,sid))
    with pytest.raises(asyncio.CancelledError):
        await tool.run({'keyword':'Monody'},'s2')


@pytest.mark.asyncio
async def test_search_launches_only_closed_client_and_never_forces_running_client(monkeypatch):
    monkeypatch.setattr(client,'_epoch',0)
    monkeypatch.setattr(client,'_query_gate',asyncio.Lock())
    call=AsyncMock(side_effect=[{'source':'client_closed'},{},{'source':'client_store'},
                               {'status':'ok','items':[]}])
    monkeypatch.setattr(client,'_call',call)
    await client.search('Monody',('hiyori',1,'s1'))
    call.assert_any_await('client_launch')
    call.reset_mock(side_effect=True)
    call.side_effect=RuntimeError('running client has no verified connection')
    with pytest.raises(RuntimeError):
        await client.search('Monody',('hiyori',1,'s1'))
    assert call.await_count==1


@pytest.mark.asyncio
async def test_direct_search_rejects_old_identity_and_stale_generation(monkeypatch):
    from types import SimpleNamespace
    import yuiro.main as main
    identity=('hiyori',4,'live-session')
    session=SimpleNamespace(generation=0)
    def advance():
        session.generation+=1
        return session.generation
    session.next_generation=advance
    monkeypatch.setattr(main,'_client_search_identity',lambda sid:identity)
    monkeypatch.setattr(main.app.state,'sessions',SimpleNamespace(get=lambda sid:session))
    monkeypatch.setattr(main.app.state,'app_config',SimpleNamespace(netease=SimpleNamespace(enabled=True)))
    search=AsyncMock(return_value={'items':[{'song_id':'36308916','source':'netease_client_ui'}]})
    monkeypatch.setattr(client,'search',search)
    ws=SimpleNamespace(send_json=AsyncMock())
    payload={'type':'media:search','backend':'netease_client','keyword':'Monody','request_id':7,
             'character_id':identity[0],'character_revision':identity[1],'session_id':identity[2]}
    await main._reply_client_search(ws,{**payload,'character_id':'hotaru'},identity[2])
    search.assert_not_awaited();assert ws.send_json.call_args.args[0]['status']=='error'
    ws.send_json.reset_mock()
    async def stale(*args,**kwargs):
        advance()
        return {'items':[{'song_id':'36308916'}]}
    search.side_effect=stale
    await main._reply_client_search(ws,payload,identity[2])
    ws.send_json.assert_not_awaited()
