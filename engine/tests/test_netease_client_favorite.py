import asyncio
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock
import pytest
from yuiro.native import netease_client as native
from yuiro.netease import official_client as client
from yuiro.tools.netease_client_search import NeteaseClientRecommendTool, NeteaseClientFavoriteTool


@pytest.mark.asyncio
async def test_favorite_is_target_state_idempotent_and_checks_id(monkeypatch):
    monkeypatch.setattr(native,'_search_lock',asyncio.Lock())
    monkeypatch.setattr(native,'state',AsyncMock(return_value={'song_id':'36308916','liked':False}))
    connection=AsyncMock()
    monkeypatch.setattr(native,'_connection',connection)
    assert (await native.favorite('36308916',False))['liked'] is False
    with pytest.raises(RuntimeError):await native.favorite('999',True)
    with pytest.raises(ValueError):await native.favorite('36308916','false')
    connection.assert_not_called()


@pytest.mark.asyncio
async def test_favorite_one_write_waits_delayed_readback(monkeypatch):
    @asynccontextmanager
    async def connection():yield object()
    snapshots=[{'song_id':'36308916','liked':v} for v in [False,False,False,True,True]]
    monkeypatch.setattr(native,'_search_lock',asyncio.Lock())
    monkeypatch.setattr(native,'state',AsyncMock(side_effect=snapshots))
    monkeypatch.setattr(native,'_connection',connection)
    rpc=AsyncMock();monkeypatch.setattr(native,'_rpc',rpc)
    monkeypatch.setattr(native.asyncio,'sleep',AsyncMock())
    assert (await native.favorite('36308916',True))['liked'] is True
    assert rpc.await_count==1
    assert 'changed track' in rpc.call_args.args[2]['expression']


@pytest.mark.asyncio
async def test_favorite_aborts_after_manual_track_change(monkeypatch):
    @asynccontextmanager
    async def connection():yield object()
    monkeypatch.setattr(native,'_search_lock',asyncio.Lock())
    monkeypatch.setattr(native,'state',AsyncMock(side_effect=[{'song_id':'36308916','liked':False},{'song_id':'999','liked':True}]))
    monkeypatch.setattr(native,'_connection',connection)
    rpc=AsyncMock();monkeypatch.setattr(native,'_rpc',rpc)
    monkeypatch.setattr(native.asyncio,'sleep',AsyncMock())
    with pytest.raises(RuntimeError,match='歌曲已变化'):await native.favorite('36308916',True)
    assert rpc.await_count==1


@pytest.mark.asyncio
async def test_daily_reads_only_stable_song_candidates(monkeypatch):
    @asynccontextmanager
    async def connection():yield object()
    items=[{'song_id':str(i),'name':'song','artist':'artist','source':'netease_client_daily'} for i in range(1,12)]
    rpc=AsyncMock(side_effect=[{}, {'result':{'value':True}}, {'result':{'value':items}}, {'result':{'value':items}}])
    monkeypatch.setattr(native,'_search_lock',asyncio.Lock())
    monkeypatch.setattr(native,'_connection',connection);monkeypatch.setattr(native,'_rpc',rpc)
    monkeypatch.setattr(native.asyncio,'sleep',AsyncMock())
    result=await native.recommend(3)
    assert len(result['items'])==3 and result['played'] is False
    assert all(it in items for it in result['items'])
    assert all(call.args[1]=='Runtime.evaluate' for call in rpc.call_args_list)


@pytest.mark.asyncio
async def test_favorite_requires_owner_and_same_character(monkeypatch):
    monkeypatch.setattr(client,'_owner',{'song_id':'36308916','identity':('hiyori',1,'s'),'epoch':0,'playback_id':'p'})
    monkeypatch.setattr(client,'_epoch',0)
    call=AsyncMock();monkeypatch.setattr(client,'_call',call)
    with pytest.raises(RuntimeError):await client.favorite_owned('36308916',True,('hotaru',1,'s'))
    with pytest.raises(RuntimeError):await client.favorite_owned('999',True,('hiyori',1,'s'))
    call.assert_not_called()


@pytest.mark.asyncio
async def test_daily_and_favorite_tools_propagate_cancellation(monkeypatch):
    monkeypatch.setattr(client,'search',AsyncMock(side_effect=asyncio.CancelledError()))
    monkeypatch.setattr(client,'favorite_owned',AsyncMock(side_effect=asyncio.CancelledError()))
    for tool,args in [(NeteaseClientRecommendTool(lambda s:('hiyori',1,s)),{}),(NeteaseClientFavoriteTool(lambda s:('hiyori',1,s)),{'song_id':'36308916','liked':True})]:
        with pytest.raises(asyncio.CancelledError):await tool.run(args,'s')


@pytest.mark.asyncio
async def test_role_change_waits_for_inflight_favorite_and_discards_old_result(monkeypatch):
    owner={'song_id':'36308916','identity':('hiyori',1,'s'),'epoch':0,'playback_id':'p'}
    monkeypatch.setattr(client,'_owner',owner);monkeypatch.setattr(client,'_epoch',0)
    monkeypatch.setattr(client,'_lock',asyncio.Lock())
    monkeypatch.setattr(client,'_read',AsyncMock(return_value={'song_id':'36308916','status':'paused','liked':True}))
    entered=asyncio.Event();finish=asyncio.Event()
    async def call(*args,**kwargs):entered.set();await finish.wait();return {}
    monkeypatch.setattr(client,'_call',call)
    task=asyncio.create_task(client.control(('hiyori',1,'s'),'p','like'))
    await entered.wait();client.invalidate()
    release=asyncio.create_task(client.release());await asyncio.sleep(0)
    assert not release.done()
    finish.set()
    with pytest.raises(RuntimeError,match='角色已切换'):await task
    await release
    assert client._owner is None


@pytest.mark.asyncio
async def test_cancelled_favorite_drains_write_before_unlock(monkeypatch):
    monkeypatch.setattr(client,'_owner',{'song_id':'36308916','identity':('hiyori',1,'s'),'epoch':0,'playback_id':'p'})
    monkeypatch.setattr(client,'_epoch',0);monkeypatch.setattr(client,'_lock',asyncio.Lock())
    monkeypatch.setattr(client,'_read',AsyncMock(return_value={'song_id':'36308916','status':'paused','liked':False}))
    entered=asyncio.Event();finish=asyncio.Event()
    async def call(*args,**kwargs):entered.set();await finish.wait();return {}
    monkeypatch.setattr(client,'_call',call)
    task=asyncio.create_task(client.control(('hiyori',1,'s'),'p','like'))
    await entered.wait();task.cancel();await asyncio.sleep(0)
    assert client._lock.locked() and not task.done()
    finish.set()
    with pytest.raises(asyncio.CancelledError):await task
    assert not client._lock.locked()


@pytest.mark.asyncio
async def test_natural_this_song_resolves_only_active_owner(monkeypatch):
    identity=('hiyori',1,'s')
    monkeypatch.setattr(client,'_owner',{'song_id':'36308916','identity':identity,'epoch':0,'playback_id':'p'})
    monkeypatch.setattr(client,'_epoch',0)
    control=AsyncMock(return_value={'song_id':'36308916','liked':True})
    monkeypatch.setattr(client,'control',control)
    result=await client.favorite_owned('',True,identity)
    assert result['song_id']=='36308916'
    control.assert_awaited_once_with(identity,'p','like')
    with pytest.raises(RuntimeError):await client.favorite_owned('',True,('hotaru',1,'s'))
    assert control.await_count==1
    assert NeteaseClientFavoriteTool().schema()['function']['parameters']['required']==['liked']
    monkeypatch.setattr(client,'_owner',None)
    with pytest.raises(RuntimeError):await client.favorite_owned('',True,identity)
