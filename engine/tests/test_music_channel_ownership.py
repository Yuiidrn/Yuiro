"""权益只描述当前通道；指定版本与播放归属不得静默替换。"""
import json
import base64
from unittest.mock import AsyncMock, Mock

import pytest

from yuiro.native import ops
from yuiro.native.backend import NativeBackend
from yuiro.netease import api, player
from yuiro.netease.availability import song_availability
from yuiro.tools import netease_tool as tools


@pytest.mark.parametrize('song,state,playable', [
    ({}, 'unknown', None),
    ({'playFlag': False}, 'api_unavailable', False),
    ({'playFlag': True}, 'api_available', True),
    ({'playFlag': True, 'visible': False}, 'api_unavailable', False),
    ({'playFlag': True, 'freeTrailFlag': True}, 'api_preview', True),
])
def test_channel_state_does_not_infer_membership(song, state, playable):
    r = song_availability(song)
    assert r['availability'] == state
    assert r['playable'] is playable
    assert r['playback_backend'] == 'builtin'


def test_detail_and_safe_flags():
    r = song_availability({'playFlag': True, 'vipFlag': True, 'playUrl': '',
                           'accessToken': 'secret'}, detail=True)
    assert r['availability'] == 'api_unavailable'
    assert 'secret' not in json.dumps(r)
    assert '未开会员' not in r['availability_note']
    assert song_availability({'playFlag': False, 'playUrl': 'https://audio'}, detail=True)['playable'] is False


@pytest.mark.asyncio
async def test_unavailable_original_is_not_replaced_by_remix(monkeypatch):
    original = {'name': 'Monody', 'originalId': 1, 'id': 'orig', 'playFlag': False}
    remix = {'name': 'Monody (Remix)', 'originalId': 2, 'id': 'mix', 'playFlag': True}
    monkeypatch.setattr(api, 'search_song', AsyncMock(return_value=[original, remix]))
    best, choices = await tools._pick_best('Monody')
    assert best is None
    assert choices[0]['encrypted_id'] == 'orig'
    assert choices[0]['availability'] == 'api_unavailable'


@pytest.mark.asyncio
async def test_search_order_and_rights_are_preserved(monkeypatch):
    rows = [{'name': 'original', 'originalId': 1, 'playFlag': False, 'vipFlag': True},
            {'name': 'remix', 'originalId': 2, 'playFlag': True}]
    monkeypatch.setattr(api, 'search_song', AsyncMock(return_value=rows))
    r = json.loads(await tools.NeteaseSearchTool().run({'keyword': 'x'}, 'test'))
    assert r['items'][0]['song_id'] == 1
    assert r['items'][0]['rights_flags']['vipFlag'] is True


@pytest.mark.asyncio
async def test_missing_url_does_not_claim_copyright_or_play(monkeypatch):
    monkeypatch.setattr(api, 'song_detail', AsyncMock(return_value={'name': 'Monody', 'playFlag': False}))
    play = AsyncMock()
    monkeypatch.setattr(player, 'play_urls', play)
    r = json.loads(await tools.NeteasePlayTool().run({'encrypted_id': 'orig'}, 'test'))
    assert r['status'] == 'error'
    assert '未替换版本' in r['message']
    assert '可能无版权或需会员' not in r['message']
    play.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize('returned_id', [None, 2])
async def test_selected_id_must_be_confirmed_by_detail(monkeypatch, returned_id):
    monkeypatch.setattr(api, 'song_detail', AsyncMock(return_value={
        'name': 'Monody', 'originalId': returned_id, 'playFlag': True, 'playUrl': 'https://audio'}))
    play = AsyncMock()
    monkeypatch.setattr(player, 'play_urls', play)
    r = json.loads(await tools.NeteasePlayTool().run({'encrypted_id': 'orig', 'song_id': '1'}, 'test'))
    assert r['status'] == 'error'
    play.assert_not_awaited()


def test_app_denial_is_not_reported_as_login_expiry():
    r = json.loads(tools._err(api.MusicApiError(403, '应用未授权')))
    assert r['status'] == 'error'
    assert json.loads(tools._err(api.MusicApiError(401, '未登录')))['status'] == 'need_login'


@pytest.mark.asyncio
async def test_app_denial_does_not_refresh_login(monkeypatch):
    token = AsyncMock(return_value='local-test-token')
    monkeypatch.setattr(api, 'ensure_token', token)
    monkeypatch.setattr(api, '_build_url', lambda *a: 'https://example.invalid')
    monkeypatch.setattr(api, '_http_get', lambda *a: {'code': 403, 'message': '应用未授权'})
    with pytest.raises(api.MusicApiError) as exc:
        await api.call_api('/test', {})
    assert exc.value.code == 403
    token.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_queue_needs_version_choice_instead_of_first_option(monkeypatch):
    monkeypatch.setattr(tools, '_pick_best', AsyncMock(return_value=(None, [{'name': 'Monody', 'id': 'a'}])))
    enqueue = AsyncMock()
    monkeypatch.setattr(player, 'enqueue', enqueue)
    r = json.loads(await tools.NeteaseControlTool().run({'action': 'queue', 'keyword': 'Monody'}, 'test'))
    assert r['status'] == 'need_choice'
    enqueue.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize('tool', [tools.NeteasePlayTool, tools.NeteaseControlTool])
async def test_builtin_tools_reject_a_different_backend(tool):
    r = json.loads(await tool().run({'backend': 'netease_client', 'action': 'stop'}, 'test'))
    assert r['status'] == 'error'


@pytest.mark.asyncio
async def test_explicit_native_target_never_falls_back_to_media_keys(monkeypatch):
    monkeypatch.setattr(ops, '_smtc_control', lambda action, target: (False, 'NOSESSION'))
    key = Mock()
    monkeypatch.setattr(ops, '_send_key', key)
    assert ops.media_control('play', 'cloudmusic.exe')[0] == 'error'
    key.assert_not_called()


def test_state_query_never_reads_another_target(monkeypatch):
    monkeypatch.setattr(ops, '_smtc_sessions', lambda: [{'aumid': 'other.exe', 'title': 'other'}])
    status, out = ops.media_control('now_playing', 'cloudmusic.exe')
    assert status == 'error'
    assert 'other' not in json.loads(out).get('title', '')


def test_state_query_refuses_ambiguous_client_sessions(monkeypatch):
    monkeypatch.setattr(ops, '_smtc_sessions', lambda: [
        {'aumid': 'cloudmusic.exe', 'title': 'Monody'},
        {'aumid': 'cloudmusic.exe', 'title': 'other'},
    ])
    assert ops.media_control('now_playing', 'cloudmusic.exe')[0] == 'error'


def test_targeted_volume_cannot_become_global_volume(monkeypatch):
    key = Mock()
    monkeypatch.setattr(ops, '_send_key', key)
    assert ops.media_control('volume_up', 'cloudmusic.exe')[0] == 'error'
    key.assert_not_called()


def test_changed_client_track_is_rejected_without_global_key(monkeypatch):
    monkeypatch.setattr(ops, '_smtc_control', lambda action, target, title: (True, '目标曲目已变化，拒绝执行本次控制'))
    key = Mock()
    monkeypatch.setattr(ops, '_send_key', key)
    assert ops.media_control('stop', 'cloudmusic.exe', 'Monody')[0] == 'error'
    key.assert_not_called()


@pytest.mark.parametrize('output', ['UNSUPPORTED', 'UNCONFIRMED'])
def test_client_ack_is_not_execution_success(monkeypatch, output):
    monkeypatch.setattr(ops.subprocess, 'run', lambda *a, **k: Mock(stdout=output, stderr=''))
    key = Mock()
    monkeypatch.setattr(ops, '_send_key', key)
    assert ops.media_control('stop', 'cloudmusic.exe', 'Monody')[0] == 'error'
    key.assert_not_called()


@pytest.mark.asyncio
async def test_playlist_does_not_play_preview_or_mismatched_detail(monkeypatch):
    monkeypatch.setattr(api, 'song_detail', AsyncMock(side_effect=[
        {'originalId': 1, 'playFlag': True, 'playUrl': 'https://audio', 'freeTrailFlag': True},
        {'originalId': 3, 'playFlag': True, 'playUrl': 'https://audio'},
    ]))
    play = AsyncMock()
    monkeypatch.setattr(player, 'play_urls', play)
    played, _, _ = await tools._play_songs([{'id': 'a', 'originalId': 1}, {'id': 'b', 'originalId': 2}], 2)
    assert played is False
    play.assert_not_awaited()


@pytest.mark.asyncio
async def test_song_open_requires_exact_client_and_numeric_id(monkeypatch):
    run = Mock()
    monkeypatch.setattr(ops.subprocess, 'Popen', run)
    monkeypatch.setattr(ops, '_netease_executable', lambda: r'D:\app\cloudmusic.exe')
    b = NativeBackend(txn_enabled=False)
    assert (await b.call('media_control', {'action': 'open_song', 'target': 'other.exe', 'song_id': '36308916'})).status == 'denied'
    assert ops.open_netease_song('1; shutdown')[0] == 'denied'
    run.assert_not_called()
    assert (await b.call('media_control', {'action': 'open_song', 'target': 'cloudmusic.exe', 'song_id': '36308916'})).status == 'ok'
    argv = run.call_args.args[0]
    assert argv[0] == r'D:\app\cloudmusic.exe'
    assert json.loads(base64.b64decode(argv[1].removeprefix('--webcmd=orpheus://'))) == {
        'type': 'song', 'id': '36308916', 'cmd': 'play'}
