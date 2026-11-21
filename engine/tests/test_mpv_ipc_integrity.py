"""mpv 事件/迟到响应不算确认；未知状态不能误判为停止。"""
import asyncio
import ctypes
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from ctypes import wintypes
from unittest.mock import AsyncMock

import pytest

from yuiro.netease import player
from yuiro.tools import netease_tool


def set_dword(pointer, value):
    ctypes.cast(pointer, ctypes.POINTER(wintypes.DWORD)).contents.value = value


class Pipe:
    def __init__(self):
        self.ids = []
        self.chunks = []
        self.late = None

    def WriteFile(self, handle, payload, size, written, overlapped):
        message = json.loads(payload)
        rid = message['request_id']
        self.ids.append(rid)
        set_dword(written, size)
        # 无关事件、旧响应、重复响应，以及被拆开的 UTF-8 响应。
        self.chunks.extend([b'{"event":"file-loaded"}\n',
                            b'{"request_id":-99,"error":"success","data":"old"}\n'])
        if self.late is not None:
            self.chunks.append(json.dumps({'request_id': self.late, 'error': 'success', 'data': 'late'}).encode()+b'\n')
        reply = json.dumps({'request_id': rid, 'error': 'success', 'data': '歌曲'}, ensure_ascii=False).encode()+b'\n'
        split = reply.index('歌曲'.encode())+1
        self.chunks.extend([reply[:split], reply[split:], reply])
        return 1

    def PeekNamedPipe(self, handle, buf, size, read, available, left):
        set_dword(available, len(self.chunks[0]) if self.chunks else 0)
        return 1

    def ReadFile(self, handle, buf, size, read, overlapped):
        chunk = self.chunks.pop(0)
        ctypes.memmove(buf, chunk, len(chunk))
        set_dword(read, len(chunk))
        return 1


def test_events_fragments_duplicates_and_late_replies(monkeypatch):
    pipe = Pipe()
    monkeypatch.setattr(player, '_kernel32', pipe)
    monkeypatch.setattr(player, '_open_ipc_handle', lambda: 42)
    monkeypatch.setattr(player, '_ipc_buffer', b'')
    first = player._send_ipc_sync([['get_property', 'media-title']], .2)
    assert first == [{'request_id': 0, 'error': 'success', 'data': '歌曲'}]
    pipe.late = pipe.ids[0]
    second = player._send_ipc_sync([['get_property', 'media-title'], ['get_property', 'media-title']], .2)
    assert len(second) == 2
    assert {r['request_id'] for r in second} == {0, 1}
    assert all(r['data'] == '歌曲' for r in second)
    assert len(set(pipe.ids)) == 3


def test_shared_pipe_transactions_are_serialized(monkeypatch):
    active = 0
    peak = 0

    def transaction(commands, timeout):
        nonlocal active, peak
        active += 1
        peak = max(active, peak)
        time.sleep(.02)
        active -= 1
        return []

    monkeypatch.setattr(player, '_send_ipc_locked', transaction)
    with ThreadPoolExecutor(2) as pool:
        list(pool.map(lambda _: player._send_ipc_sync([['get_property', 'pause']]), range(4)))
    assert peak == 1


def test_events_without_matching_reply_do_not_complete_command(monkeypatch):
    pipe = Pipe()

    def write(handle, payload, size, written, overlapped):
        set_dword(written, size)
        pipe.chunks.append(b'{"event":"idle"}\n')
        return 1

    pipe.WriteFile = write
    monkeypatch.setattr(player, '_kernel32', pipe)
    monkeypatch.setattr(player, '_open_ipc_handle', lambda: 42)
    monkeypatch.setattr(player, '_ipc_buffer', b'')
    assert player._send_ipc_sync([['stop']], .03) == []


@pytest.mark.asyncio
@pytest.mark.parametrize('values,status', [
    ({}, 'unknown'),
    ({'media-title': 'song', 'pause': False}, 'unknown'),
    ({'playlist-pos': 0}, 'unknown'),
    ({'playlist-pos': -1}, 'stopped'),
    ({'playlist-pos': 0, 'pause': False}, 'playing'),
    ({'playlist-pos': 0, 'pause': True}, 'paused'),
])
async def test_state_requires_confirmed_playlist_position(monkeypatch, values, status):
    monkeypatch.setattr(player, 'pipe_alive', lambda: True)

    async def ipc(commands, timeout_s=3):
        return [{'request_id': i, 'error': 'success', 'data': values[cmd[1]]}
                for i, cmd in enumerate(commands) if cmd[1] in values]

    monkeypatch.setattr(player, '_ipc', ipc)
    assert (await player.get_state())['status'] == status


@pytest.mark.asyncio
async def test_unknown_state_never_controls_external_player(monkeypatch):
    monkeypatch.setattr(player, 'get_state', AsyncMock(return_value={'status': 'unknown'}))
    external = AsyncMock()
    own = AsyncMock()
    monkeypatch.setattr(netease_tool, '_forward_to_system', external)
    monkeypatch.setattr(player, 'control', own)
    result = json.loads(await netease_tool.NeteaseControlTool().run({'action': 'stop'}, 'test'))
    assert result['status'] == 'error'
    external.assert_not_awaited()
    own.assert_not_awaited()


@pytest.mark.asyncio
async def test_confirmed_idle_no_longer_implicitly_controls_external_player(monkeypatch):
    monkeypatch.setattr(player, 'get_state', AsyncMock(return_value={'status': 'stopped'}))
    external = AsyncMock(return_value={'status': 'ok', 'forwarded': True})
    monkeypatch.setattr(netease_tool, '_forward_to_system', external)
    result = json.loads(await netease_tool.NeteaseControlTool().run({'action': 'stop'}, 'test'))
    assert result['backend'] == 'builtin'
    external.assert_not_awaited()


@pytest.mark.asyncio
async def test_control_without_ack_is_not_reported_as_success(monkeypatch):
    monkeypatch.setattr(player, 'ensure_mpv_async', AsyncMock(return_value=True))
    monkeypatch.setattr(player, '_ipc', AsyncMock(return_value=[]))
    monkeypatch.setattr(player, 'get_state', AsyncMock(return_value={'status': 'playing'}))
    assert (await player.control('stop'))['status'] == 'error'


@pytest.mark.asyncio
async def test_pipe_lock_wait_does_not_block_event_loop(monkeypatch):
    gate = threading.Event()

    def busy_pipe():
        gate.wait(.2)
        return False

    monkeypatch.setattr(player, 'pipe_alive', busy_pipe)
    start = time.monotonic()
    pending = asyncio.create_task(player.get_state())
    try:
        await asyncio.sleep(.01)
        assert time.monotonic()-start < .1
    finally:
        gate.set()
        await pending
