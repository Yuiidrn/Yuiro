"""Windows 客户端窄适配：固定 UI 操作与白名单状态，不开放任意 CDP/JS 接口。"""
from __future__ import annotations

import asyncio
import ctypes
import json
import os
import socket
import struct
import subprocess
import time
from contextlib import asynccontextmanager
from urllib.parse import urlparse

import httpx
import websockets

from . import ops

PORT = 9223
_search_lock = asyncio.Lock()


@asynccontextmanager
async def _connection():
    await asyncio.to_thread(_verified_listener)
    async with httpx.AsyncClient(trust_env=False, timeout=2) as h:
        response = await h.get(f'http://127.0.0.1:{PORT}/json')
        response.raise_for_status()
        targets = [p for p in response.json() if p.get('url') == 'orpheus://orpheus/pub/app.html' and p.get('type') == 'page']
    if len(targets) != 1:
        raise RuntimeError('网易云主页面未就绪，未使用其他检索后端')
    async with websockets.connect(_checked_socket(targets[0]['webSocketDebuggerUrl']), open_timeout=2, max_size=131072) as ws:
        yield ws


async def _rpc(ws, method: str, params: dict, request_id: int = 1) -> dict:
    await ws.send(json.dumps({'id':request_id, 'method':method, 'params':params}))
    async with asyncio.timeout(5):
        while True:
            message = json.loads(await ws.recv())
            if message.get('id') != request_id:
                continue
            if message.get('error') or message.get('result', {}).get('exceptionDetails'):
                raise RuntimeError('当前网易云版本的界面操作不兼容，未回退其他服务')
            return message.get('result', {})


async def search(keyword: str, limit: int = 8) -> dict:
    """通过客户端原生搜索框触发 UI；只读搜索结果，不调用开放平台。"""
    if not keyword.strip() or len(keyword) > 100 or any(ord(ch)<32 for ch in keyword):
        raise ValueError('搜索词需为 1–100 个可显示字符')
    async with _search_lock, _connection() as ws:
        focus = """(()=>{const a=[...document.querySelectorAll('input[type=search]')].filter(e=>e.closest('.searchbox')&&e.getBoundingClientRect().width>0);if(a.length!==1)throw Error('search input');a[0].focus();a[0].select();return true})()"""
        await _rpc(ws, 'Runtime.evaluate', {'expression':focus,'returnByValue':True})
        await _rpc(ws, 'Input.insertText', {'text':keyword}, 2)
        await asyncio.sleep(.25)
        await _rpc(ws, 'Input.dispatchKeyEvent', {'type':'keyDown','key':'Enter','code':'Enter','windowsVirtualKeyCode':13,'nativeVirtualKeyCode':13,'text':'\r'}, 3)
        await _rpc(ws, 'Input.dispatchKeyEvent', {'type':'keyUp','key':'Enter','code':'Enter','windowsVirtualKeyCode':13}, 4)
        previous = None
        deadline = time.monotonic()+12
        while time.monotonic()<deadline:
            result = await _rpc(ws, 'Runtime.evaluate', {'expression':_SEARCH_ROWS,'returnByValue':True}, 5)
            data = result.get('result', {}).get('value') or {}
            if data.get('keyword') == keyword and data.get('items'):
                signature = json.dumps(data['items'], sort_keys=True)
                if signature == previous:
                    return {'status':'ok','source':'netease_client_ui','keyword':keyword,
                            'items':data['items'][:max(1,min(6,limit))]}
                previous = signature
            else:
                previous = None
            await asyncio.sleep(.3)
        raise RuntimeError('客户端未返回可核验的本次单曲结果，未使用 CLI/API 回退')


_SEARCH_ROWS = r"""(()=>{
const logs=[...document.querySelectorAll('[data-log]')];
const read=e=>{try{return JSON.parse(e.getAttribute('data-log')||'{}')}catch{return {}}};
const page=logs.find(e=>read(e).oid==='page_pc_search_result');
if(!page)return {keyword:'',items:[]};
const items=[],seen=new Set();
for(const e of page.querySelectorAll('[data-log]')){
 const d=read(e),p=d.params||{};
 if(d.oid!=='cell_pc_common_songcard'||p.s_ctype!=='song'||!(/^[1-9]\d{0,19}$/).test(String(p.s_cid)))continue;
 const name=e.querySelector('.cmd-metacard-content .header')?.textContent?.trim();
 const artist=e.querySelector('.cmd-metacard-content .artist')?.textContent?.trim();
 if(!name||!artist||seen.has(String(p.s_cid)))continue;
 seen.add(String(p.s_cid));items.push({song_id:String(p.s_cid),name:name.slice(0,200),artist:artist.slice(0,200),source:'netease_client_ui'});
 if(items.length>=6)break;
}
return {keyword:String(read(page).params?.s_cid||''),items};})()"""

# 只检查当前客户端的已加载模块，不执行下载的第三方代码。版本变更无法识别即失败。
_CURRENT = r"""(()=>{
if(typeof webpackJsonp==='undefined')throw Error('Unsupported client');
if(!window.__yuiroMusicRequire)webpackJsonp.push([[987662],{987662:function(m,e,r){window.__yuiroMusicRequire=r}},[[987662]]]);
const r=window.__yuiroMusicRequire;
for(const m of Object.values(r.c||{}))for(const v of Object.values(m.exports||{})){
 if(!v||typeof v.getStore!=='function')continue;
 const s=v.getStore(),p=s&&s.playing;if(!p||!('curPlaying' in p))continue;
 const t=p.curPlaying&&p.curPlaying.track||{};
 return {song_id:String(p.curPlaying&&p.curPlaying.resourceId||''),name:String(t.name||p.resourceName||''),
 artist:(t.ar||t.artists||[]).map(a=>a.name||'').join(' / '),duration:Number(p.resourceDuration||0),
 preview:!!(p.freeTrialInfo||p.resourceIsTryType),liked:(()=>{const a=[...document.querySelectorAll('[aria-label=like_number],[aria-label=likenumber_red]')].filter(e=>e.getClientRects().length);if(a.length!==1)return null;return a[0].getAttribute('aria-label')==='likenumber_red'})(),source:'client_store'};
}throw Error('Unsupported current track state');})()"""


def _verified_listener() -> None:
    """确认端口仅绑定回环且属于已注册的官方 exe，拒绝端口被其他应用占用。"""
    if os.name != 'nt':
        raise RuntimeError('官方客户端桥接仅支持 Windows')
    # wintypes 在非 Windows 上 import 即报错，故只能在确认平台后延迟导入
    from ctypes import wintypes

    class Row(ctypes.Structure):
        _fields_ = [(key, wintypes.DWORD) for key in ('state', 'address', 'port', 'remote_address', 'remote_port', 'pid')]
    size = wintypes.DWORD()
    get_table = ctypes.windll.iphlpapi.GetExtendedTcpTable
    get_table.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD), wintypes.BOOL,
                         wintypes.ULONG, ctypes.c_int, wintypes.ULONG]
    if get_table(None, ctypes.byref(size), False, 2, 3, 0) not in (0, 122):
        raise RuntimeError('无法核验本机网易云连接，未执行')
    buffer = ctypes.create_string_buffer(size.value)
    if get_table(buffer, ctypes.byref(size), False, 2, 3, 0) != 0:
        raise RuntimeError('无法核验本机网易云连接，未执行')
    count = wintypes.DWORD.from_buffer(buffer).value
    rows = (Row * count).from_buffer(buffer, ctypes.sizeof(wintypes.DWORD))
    matches = [row for row in rows if socket.ntohs(row.port & 65535) == PORT]
    if len(matches) != 1 or socket.inet_ntoa(struct.pack('<I', matches[0].address)) != '127.0.0.1':
        raise RuntimeError('网易云未建立本地连接；请先退出网易云，再选择“网易云客户端”重试。不会自动关闭其他播放器。')
    kernel = ctypes.windll.kernel32
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.OpenProcess(0x1000, False, matches[0].pid)
    path, capacity = ctypes.create_unicode_buffer(32768), wintypes.DWORD(32768)
    try:
        if not handle or not kernel.QueryFullProcessImageNameW(handle, 0, path, ctypes.byref(capacity)):
            raise RuntimeError('无法确认本机连接所属进程，未执行')
    finally:
        if handle:
            kernel.CloseHandle(handle)
    expected = os.path.normcase(os.path.realpath(ops._netease_executable()))
    actual = os.path.normcase(os.path.realpath(path.value))
    if actual != expected:
        raise RuntimeError('网易云未建立本地连接；请先退出网易云，再选择“网易云客户端”重试。不会自动关闭其他播放器。')


def _checked_socket(url: str) -> str:
    u = urlparse(url)
    if (u.scheme != 'ws' or u.hostname != '127.0.0.1' or u.port != PORT
            or not u.path.startswith('/devtools/page/') or u.username or u.password or u.query or u.fragment):
        raise RuntimeError('拒绝非本机网易云状态连接')
    return url


async def state() -> dict:
    try:
        await asyncio.to_thread(_verified_listener)
    except RuntimeError:
        if not await asyncio.to_thread(_running):
            return {'source':'client_closed', 'song_id':'', 'name':'', 'status':'closed'}
        raise
    async with httpx.AsyncClient(trust_env=False, timeout=2) as h:
        response = await h.get(f'http://127.0.0.1:{PORT}/json')
        response.raise_for_status()
        targets = [t for t in response.json() if t.get('type') == 'page'
                   and t.get('url') == 'orpheus://orpheus/pub/app.html']
    if len(targets) != 1:
        raise RuntimeError('网易云主页面不唯一或尚未就绪，未执行播放')
    async with websockets.connect(_checked_socket(targets[0]['webSocketDebuggerUrl']),
                                  open_timeout=2, max_size=65536) as ws:
        await ws.send(json.dumps({'id': 1, 'method': 'Runtime.evaluate',
                                 'params': {'expression': _CURRENT, 'returnByValue': True}}))
        async with asyncio.timeout(3):
            while True:
                reply = json.loads(await ws.recv())
                if reply.get('id') == 1:
                    break
    result = reply.get('result') or {}
    if reply.get('error') or result.get('exceptionDetails'):
        raise RuntimeError('当前网易云版本的歌曲状态不兼容，未执行播放')
    value = result.get('result', {}).get('value')
    if not isinstance(value, dict) or value.get('source') != 'client_store':
        raise RuntimeError('无法核验网易云当前歌曲，未执行播放')
    return value


def _running() -> bool:
    p = subprocess.run(['tasklist', '/FI', 'IMAGENAME eq cloudmusic.exe', '/FO', 'CSV', '/NH'],
                       capture_output=True, encoding='utf-8', errors='replace', timeout=5,
                       creationflags=ops._CREATE_NO_WINDOW)
    if p.returncode:
        raise RuntimeError('无法确认网易云是否退出，未启动另一个播放器')
    return 'cloudmusic.exe' in p.stdout.casefold()


def launch_if_closed() -> None:
    """只有用户显式选择官方客户端时调用；已有进程不重启、不接管。"""
    if _running():
        raise RuntimeError('请先退出网易云，再选择“网易云客户端”连接；不会自动重启正在使用的客户端。')
    executable = ops._netease_executable()
    process = subprocess.Popen([executable, '--remote-debugging-address=127.0.0.1',
                      f'--remote-debugging-port={PORT}'], cwd=os.path.dirname(executable),
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(.3)
    if process.poll() is not None and not _running():
        raise RuntimeError(f'网易云启动后退出（code={process.returncode}），未开始播放')


async def favorite(song_id: str, desired: bool | None = None) -> dict:
    """仅操作当前 ID；目标状态幂等，最多点击一次。超时未知不得重试 toggle。"""
    if not __import__('re').fullmatch(r'[1-9][0-9]{0,19}', song_id):
        raise ValueError('需要明确的数字歌曲 ID')
    if desired is not None and type(desired) is not bool:
        raise ValueError('喜欢状态必须是布尔值')
    async with _search_lock:
        current = await state()
        if current.get('song_id') != song_id or type(current.get('liked')) is not bool:
            raise RuntimeError('当前歌曲 ID 或喜欢状态无法核验，未修改收藏')
        if desired is None or current['liked'] == desired:
            return current
        # ID 和图标在同一个 JS 回合再次核验，避免两次 RPC 间人工切歌。
        expression = "(()=>{const t=" + _CURRENT + ";if(t.song_id!==" + json.dumps(song_id) + ")throw Error('changed track');const a=[...document.querySelectorAll('[aria-label=like_number],[aria-label=likenumber_red]')].filter(e=>e.getClientRects().length);if(a.length!==1||!a[0].closest('button'))throw Error('unknown like');const desired=" + json.dumps(desired) + ";if(t.liked!==desired)a[0].click();return true})()"
        async with _connection() as ws:
            await _rpc(ws, 'Runtime.evaluate', {'expression':expression,'returnByValue':True})
        deadline = time.monotonic() + 60
        stable = 0
        while time.monotonic() < deadline:
            await asyncio.sleep(.5)
            try:
                current = await state()
            except (OSError, websockets.exceptions.ConnectionClosed):
                continue  # 只重读，不重复写入。
            if current.get('song_id') != song_id:
                raise RuntimeError('歌曲已变化，收藏结果未确认；未操作新歌曲')
            stable = stable + 1 if current.get('liked') is desired else 0
            if stable >= 2:
                return current
        raise RuntimeError('喜欢状态写入未确认；未重复点击或回退 API，请在客户端核对')


_DAILY_ROWS = r"""(()=>{
const read=e=>{try{return JSON.parse(e.getAttribute('data-log')||'{}')}catch{return {}}};
const page=[...document.querySelectorAll('[data-log]')].find(e=>read(e).oid==='page_pc_daily_recommend');
if(!page)return [];
const items=[],seen=new Set();
for(const e of page.querySelectorAll('[data-log]')){
 const d=read(e),p=d.params||{},id=String(p.s_cid||'');
 if(d.oid!=='cell_pc_songlist_song'||p.s_ctype!=='song'||!(/^[1-9]\d{0,19}$/).test(id)||seen.has(id))continue;
 const name=e.querySelector('.td-title .title')?.getAttribute('title');
 const artist=e.querySelector('[data-testid=tid_tracktitlecell_artist]')?.textContent?.trim();
 if(!name||!artist)continue;seen.add(id);items.push({song_id:id,name:name.slice(0,200),artist:artist.slice(0,200),source:'netease_client_daily'});
}return items.slice(0,40)})()"""

async def recommend(limit: int = 6) -> dict:
    """打开官方日推详情，读取已加载候选后随机抽样；不启动播放/随机模式。"""
    async with _search_lock:
        async with _connection() as ws:
            await _rpc(ws,'Runtime.evaluate',{'expression':"(()=>{const e=document.querySelector('#left_nav_recommend');if(!e)throw Error('missing recommend');e.click();return true})()",'returnByValue':True})
        deadline=time.monotonic()+12
        while time.monotonic()<deadline:
            async with _connection() as ws:
                ready=await _rpc(ws,'Runtime.evaluate',{'expression':"(()=>{const e=document.querySelector('#dailyRecommendCard .title');if(!e)return false;e.click();return true})()",'returnByValue':True})
            if ready.get('result',{}).get('value'):break
            await asyncio.sleep(.3)
        else:raise RuntimeError('客户端日推入口不可核验，未回退 API')
        previous=None
        while time.monotonic()<deadline:
            async with _connection() as ws:
                result=await _rpc(ws,'Runtime.evaluate',{'expression':_DAILY_ROWS,'returnByValue':True})
            items=result.get('result',{}).get('value')
            if items and items==previous:
                import random
                return {'status':'ok','source':'netease_client_daily','items':random.sample(items,min(len(items),max(1,min(6,limit)))),'played':False,'message':'从客户端当前加载的日推歌曲中随机抽取，点击后才播放'}
            previous=items
            await asyncio.sleep(.4)
        raise RuntimeError('客户端未返回可核验的日推单曲，未自动播放或回退 API')
