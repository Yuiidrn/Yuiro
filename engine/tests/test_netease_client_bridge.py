"""官方播放器严格 ID、归属、角色取消及固定本机状态连接的回归。"""
import asyncio
from unittest.mock import AsyncMock

import pytest

from yuiro.netease import official_client as client
from yuiro.native import netease_client as native

IDENTITY = ('hiyori', 3, 'session-a')
TRACK = {'song_id': '36308916', 'name': 'Monody', 'artist': 'TheFatRat',
         'status': 'playing', 'preview': False}


@pytest.mark.asyncio
async def test_short_control_respects_role_and_maps_stop_to_pause(monkeypatch):
    control = AsyncMock(return_value={**TRACK, 'status':'paused'})
    monkeypatch.setattr(client, 'control', control)
    monkeypatch.setattr(client, '_owner', {'identity':IDENTITY, 'playback_id':'p', 'epoch':0})
    assert '暂停' in await client.control_text('停止播放', IDENTITY)
    control.assert_awaited_once_with(IDENTITY, 'p', 'pause')
    control.reset_mock()
    assert '没有可控制' in await client.control_text('暂停', ('hotaru',4,'other'))
    assert '仅支持' in await client.control_text('下一首', IDENTITY)
    assert await client.control_text('这个故事先暂停讨论吧', IDENTITY) is None
    control.assert_not_awaited()


@pytest.fixture(autouse=True)
def clean_owner(monkeypatch):
    monkeypatch.setattr(client, '_owner', None)
    monkeypatch.setattr(client, '_epoch', 0)
    monkeypatch.setattr(client, '_lock', asyncio.Lock())


@pytest.mark.asyncio
async def test_exact_readback_creates_bound_owner(monkeypatch):
    call = AsyncMock(return_value={})
    monkeypatch.setattr(client, '_call', call)
    monkeypatch.setattr(client, '_read', AsyncMock(return_value=TRACK))
    state = await client.play('36308916', IDENTITY)
    assert state['song_id'] == '36308916' and state['backend'] == 'netease_client'
    assert state['can_stop'] is False and state['playback_id']
    call.assert_any_await('open_song', song_id='36308916')
    with pytest.raises(RuntimeError, match='归属'):
        await client.control(('hotaru', 4, 'other-session'), state['playback_id'], 'pause')


@pytest.mark.asyncio
@pytest.mark.parametrize('song_id', ['0', '-1', '1/?cmd=play', 'Monody', '1'*21])
async def test_bad_id_never_dispatches(monkeypatch, song_id):
    call = AsyncMock()
    monkeypatch.setattr(client, '_call', call)
    with pytest.raises(ValueError):
        await client.play(song_id, IDENTITY)
    call.assert_not_awaited()


@pytest.mark.asyncio
async def test_manual_track_change_releases_without_control(monkeypatch):
    monkeypatch.setattr(client, '_call', AsyncMock(return_value={}))
    monkeypatch.setattr(client, '_read', AsyncMock(return_value=TRACK))
    state = await client.play('36308916', IDENTITY)
    call = AsyncMock()
    monkeypatch.setattr(client, '_call', call)
    monkeypatch.setattr(client, '_read', AsyncMock(return_value={**TRACK, 'song_id': '999'}))
    assert await client.control(IDENTITY, state['playback_id'], 'pause') is None
    call.assert_not_awaited()
    assert client._owner is None


@pytest.mark.asyncio
async def test_role_invalidated_during_state_read_never_controls(monkeypatch):
    call = AsyncMock(return_value={})
    monkeypatch.setattr(client, '_call', call)
    monkeypatch.setattr(client, '_read', AsyncMock(return_value=TRACK))
    state = await client.play('36308916', IDENTITY)
    async def invalidating_read():
        client.invalidate()
        return TRACK
    call.reset_mock()
    monkeypatch.setattr(client, '_read', invalidating_read)
    with pytest.raises(RuntimeError, match='角色已切换'):
        await client.control(IDENTITY, state['playback_id'], 'pause')
    call.assert_not_awaited()


@pytest.mark.asyncio
async def test_preview_is_not_success_and_is_paused(monkeypatch):
    call = AsyncMock(return_value={})
    monkeypatch.setattr(client, '_call', call)
    monkeypatch.setattr(client, '_read', AsyncMock(side_effect=[
        {**TRACK, 'preview': True}, TRACK, {**TRACK, 'status': 'paused'}]))
    with pytest.raises(RuntimeError, match='试听'):
        await client.play('36308916', IDENTITY)
    call.assert_any_await('pause', expected_title='Monody')
    assert client._owner is None


@pytest.mark.asyncio
async def test_cancelled_dispatch_drains_then_pauses_own_track(monkeypatch):
    started, finish = asyncio.Event(), asyncio.Event()
    calls = []
    async def call(action, **kwargs):
        calls.append(action)
        if action == 'open_song':
            started.set()
            await finish.wait()
        return {}
    monkeypatch.setattr(client, '_call', call)
    monkeypatch.setattr(client, '_read', AsyncMock(side_effect=[TRACK, {**TRACK, 'status':'paused'}]))
    task = asyncio.create_task(client.play('36308916', IDENTITY))
    await started.wait()
    client.invalidate()
    task.cancel()
    finish.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert calls == ['client_state', 'open_song', 'pause']
    assert client._owner is None


@pytest.mark.asyncio
async def test_unreadable_owned_playback_blocks_release(monkeypatch):
    client._owner = {'identity': IDENTITY, 'song_id':'36308916', 'epoch':0, 'playback_id':'bound'}
    monkeypatch.setattr(client, '_read', AsyncMock(side_effect=RuntimeError('unavailable')))
    with pytest.raises(RuntimeError):
        await client.release()
    assert client._owner is not None


@pytest.mark.asyncio
async def test_closed_client_releases_without_controlling_any_player(monkeypatch):
    client._owner = {'identity': IDENTITY, 'song_id':'36308916', 'epoch':0, 'playback_id':'bound'}
    call = AsyncMock(return_value={'source':'client_closed', 'song_id':'', 'status':'closed'})
    monkeypatch.setattr(client, '_call', call)
    await client.release()
    call.assert_awaited_once_with('client_state')
    assert client._owner is None


@pytest.mark.asyncio
async def test_closed_client_is_launched_only_after_explicit_selection(monkeypatch):
    call = AsyncMock(side_effect=[{'source':'client_closed'}, {}, {'source':'client_store'}, {}])
    monkeypatch.setattr(client, '_call', call)
    monkeypatch.setattr(client, '_read', AsyncMock(return_value=TRACK))
    state = await client.play('36308916', IDENTITY)
    assert state['song_id']=='36308916'
    assert [x.args[0] for x in call.await_args_list] == ['client_state','client_launch','client_state','open_song']


@pytest.mark.asyncio
async def test_located_paused_original_is_started_without_changing_id(monkeypatch):
    call = AsyncMock(return_value={})
    monkeypatch.setattr(client, '_call', call)
    monkeypatch.setattr(client, '_read', AsyncMock(side_effect=[{**TRACK,'status':'paused'}, TRACK]))
    state = await client.play('36308916', IDENTITY)
    assert state['song_id']=='36308916' and state['status']=='playing'
    call.assert_any_await('play', expected_title='Monody')
    assert sum(x.args[0]=='open_song' for x in call.await_args_list)==1


@pytest.mark.parametrize('url', ['ws://example.com:9223/devtools/page/a', 'ws://127.0.0.1:9222/devtools/page/a',
                                 'ws://user@127.0.0.1:9223/devtools/page/a', 'wss://127.0.0.1:9223/devtools/page/a',
                                 'ws://127.0.0.1:9223/private', 'ws://127.0.0.1:9223/devtools/page/a?x=1'])
def test_state_socket_never_connects_elsewhere(url):
    with pytest.raises(RuntimeError):
        native._checked_socket(url)


def test_exact_local_state_socket():
    url='ws://127.0.0.1:9223/devtools/page/a'
    assert native._checked_socket(url) == url
