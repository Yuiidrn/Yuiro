"""官方客户端适配与短生命周期归属，复用现有 NativeBackend/角色取消边界。"""
from __future__ import annotations

import asyncio
import json
import re
import uuid
from yuiro.logger import vlog

from yuiro.native.backend import NativeBackend

_lock = asyncio.Lock()
_epoch = 0
_owner: dict | None = None
_query_gate = asyncio.Lock()


async def search(keyword: str, identity: tuple, limit: int = 6, *, daily: bool = False) -> dict:
    stamp = _epoch
    if not identity[0] or not identity[2]:
        raise RuntimeError('当前角色会话未就绪，未搜索')
    async with _query_gate:
        if stamp != _epoch:
            raise RuntimeError('角色已切换，旧搜索未执行')
        ready = await _call('client_state')
        if ready.get('source') == 'client_closed':
            await _call('client_launch')
            async with asyncio.timeout(12):
                while True:
                    ready = await _call('client_state')
                    if ready.get('source') != 'client_closed':
                        break
                    await asyncio.sleep(.3)
        if stamp != _epoch:
            raise RuntimeError('角色已切换，旧搜索未执行')
        result = await _call('client_recommend', limit=limit) if daily else await _call('client_search', keyword=keyword, limit=limit)
        if stamp != _epoch:
            raise RuntimeError('角色已切换，旧搜索结果已丢弃')
    return result


async def control_text(text: str, identity: tuple) -> str | None:
    """仅明确的短控制句走已有归属；不触碰用户自己播放的曲目。"""
    action = {
        '暂停': 'pause', '暂停播放': 'pause', '停止播放': 'pause', '别放了': 'pause',
        '继续播放': 'resume', '继续放': 'resume', '接着放': 'resume',
        '下一首': 'unsupported', '上一首': 'unsupported', '随机播放': 'unsupported',
    }.get(text.strip().rstrip('。！!'))
    if action is None:
        return None
    if action == 'unsupported':
        return '当前网易云桥接仅支持指定歌曲、暂停和继续；请在官方客户端进行切歌或随机播放。'
    if not _owner or not _same(identity, _owner['playback_id']):
        return '当前角色没有可控制的网易云播放记录，未控制其他播放器。'
    try:
        state = await control(identity, _owner['playback_id'], action)
    except RuntimeError as exc:
        return str(exc)
    if not state:
        return '网易云曲目已由你更换，已解除桌宠归属，未控制新曲目。'
    expected = 'paused' if action == 'pause' else 'playing'
    if state.get('status') != expected:
        return '网易云客户端尚未确认目标播放状态，请查看客户端；未切换其他播放器。'
    return '网易云客户端已暂停（不支持 Stop）。' if action == 'pause' else '网易云客户端已继续播放。'


async def _call(action: str, **args) -> dict:
    result = await NativeBackend(txn_enabled=False).call(
        'media_control', {'action': action, 'target': 'cloudmusic.exe', **args})
    # 固定字段的诊断记录；不记录完整客户端状态、账号、URL 或凭证。
    vlog('media', f'[client-bridge] action={action} status={result.status}')
    if result.status != 'ok':
        raise RuntimeError(result.stdout)
    try:
        return json.loads(result.stdout)
    except ValueError:
        return {}


async def _read() -> dict:
    track = await _call('client_state')
    if track.get('source') == 'client_closed':
        return track
    smtc = await _call('now_playing')
    vlog('media', f"[client-bridge] current_id={track.get('song_id')} status={smtc.get('status')} name_match={smtc.get('title') == track.get('name')}")
    if smtc.get('title') != track.get('name') or smtc.get('status') not in ('Playing', 'Paused'):
        raise RuntimeError('网易云当前曲目或播放状态未同步，未控制其他曲目')
    return {**track, 'status': smtc['status'].lower(), 'can_stop': False}


def invalidate() -> None:
    global _epoch
    _epoch += 1


def _same(identity: tuple, playback_id: str) -> bool:
    return bool(_owner and _owner['identity'] == identity and _owner['playback_id'] == playback_id
                and _owner['epoch'] == _epoch)


def _view(state: dict) -> dict:
    return {**{k: state.get(k) for k in ('song_id', 'name', 'artist', 'status', 'liked')},
            'backend': 'netease_client', 'playback_id': _owner['playback_id'], 'can_stop': False}


async def _pause_owned() -> None:
    if not _owner:
        return
    current = await _read()
    if current.get('song_id') != _owner['song_id']:
        return  # 用户已另选歌曲；不把他的歌曲当作桌宠所有物。
    if current['status'] == 'playing':
        await _call('pause', expected_title=current['name'])
        final = await _read()
        if final.get('song_id') == _owner['song_id'] and final['status'] != 'paused':
            raise RuntimeError('旧角色的网易云歌曲尚未确认暂停，暂不切换角色')


async def release() -> None:
    global _owner
    async with _lock:
        await _pause_owned()
        _owner = None


async def play(song_id: str, identity: tuple) -> dict:
    global _owner
    if not re.fullmatch(r'[1-9][0-9]{0,19}', song_id):
        raise ValueError('官方客户端需要明确的数字歌曲 ID，不进行模糊搜索或版本替换')
    stamp = _epoch
    async with _lock:
        if stamp != _epoch:
            raise RuntimeError('角色已切换，旧选歌请求已失效')
        # 预检失败时不发送播放；只有客户端未运行时才可启动本机连接。
        try:
            ready = await _call('client_state')
            if ready.get('source') == 'client_closed':
                raise RuntimeError('客户端已退出，准备启动本机连接')
        except RuntimeError as original_error:
            try:
                await _call('client_launch')
            except RuntimeError:
                raise original_error
            async with asyncio.timeout(12):
                while True:
                    try:
                        ready = await _call('client_state')
                        if ready.get('source') != 'client_closed':
                            break
                        await asyncio.sleep(.3)
                    except RuntimeError:
                        await asyncio.sleep(.3)
        if stamp != _epoch:
            raise RuntimeError('角色已切换，旧选歌请求已失效')
        previous = _owner
        issued = False
        dispatch = asyncio.create_task(_call('open_song', song_id=song_id))
        try:
            try:
                await asyncio.shield(dispatch)
            except asyncio.CancelledError:
                # OS 投递线程不能硬取消，先收敛其回执，再清理可能已起播的本曲。
                await dispatch
                issued = True
                raise
            issued = True
            _owner = {'identity': identity, 'epoch': stamp, 'song_id': song_id,
                      'playback_id': uuid.uuid4().hex}
            async with asyncio.timeout(10):
                while True:
                    if stamp != _epoch:
                        raise RuntimeError('角色已切换，旧播放结果已失效')
                    try:
                        current = await _read()
                    except RuntimeError:
                        await asyncio.sleep(.15)
                        continue
                    if current.get('song_id') == song_id:
                        if current.get('preview'):
                            raise RuntimeError('官方客户端返回试听状态，未报告完整原版播放成功')
                        if current['status'] == 'playing':
                            return _view(current)
                        if current['status'] == 'paused':
                            # 冷启动可能只完成定位。仅在独立 ID 已一致时启动同一首歌。
                            await _call('play', expected_title=current['name'])
                    await asyncio.sleep(.15)
        except BaseException:
            if issued:
                _owner = {'identity': identity, 'epoch': stamp, 'song_id': song_id,
                          'playback_id': uuid.uuid4().hex}
                try:
                    await _pause_owned()
                except Exception:
                    # 保留未收敛归属；角色 quiesce 会再核对，不能带着未知播放切换。
                    pass
                else:
                    _owner = None
            else:
                _owner = previous
            raise


async def control(identity: tuple, playback_id: str, action: str) -> dict | None:
    global _owner
    if action not in ('state', 'pause', 'resume', 'like', 'unlike'):
        raise ValueError('官方客户端仅提供暂停/继续；不将 Stop 静默映射为暂停')
    async with _lock:
        if not _same(identity, playback_id):
            raise RuntimeError('播放归属已失效，未控制任何播放器')
        current = await _read()
        if current.get('song_id') != _owner['song_id']:
            _owner = None
            return None
        if not _same(identity, playback_id):
            raise RuntimeError('角色已切换，旧控制请求已失效')
        if action in ('like', 'unlike'):
            pending = asyncio.create_task(_call('client_favorite', song_id=_owner['song_id'], desired=action == 'like'))
            try:
                await asyncio.shield(pending)
            except asyncio.CancelledError:
                await pending  # 收藏写入不可撤销取消；先完成读回，角色 release 随后收敛。
                raise
            current = await _read()
            if current.get('song_id') != _owner['song_id']:
                _owner = None
                raise RuntimeError('歌曲已变化，未确认收藏结果')
        elif action != 'state':
            await _call('pause' if action == 'pause' else 'play', expected_title=current['name'])
            current = await _read()
        if not _same(identity, playback_id):
            raise RuntimeError('角色已切换，旧控制结果已失效')
        if current.get('song_id') != _owner['song_id']:
            _owner = None
            return None
        return _view(current)


async def favorite_owned(song_id: str, desired: bool, identity: tuple) -> dict:
    if type(desired) is not bool:
        raise ValueError('需要明确的喜欢或取消喜欢目标状态')
    if not song_id and _owner:
        song_id = _owner['song_id']
    if not _owner or _owner['song_id'] != song_id or not _same(identity,_owner['playback_id']):
        raise RuntimeError('当前角色没有此歌曲的有效播放归属，未修改收藏')
    result = await control(identity,_owner['playback_id'],'like' if desired else 'unlike')
    if not result:
        raise RuntimeError('歌曲已由用户更换，未修改新曲目')
    return result
