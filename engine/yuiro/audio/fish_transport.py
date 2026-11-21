"""Fish无角色状态的HTTP连接池；所有凭证/音色均由每次请求提供。"""
from __future__ import annotations

import asyncio
from weakref import WeakKeyDictionary

import httpx

_clients: WeakKeyDictionary[asyncio.AbstractEventLoop, httpx.AsyncClient] = WeakKeyDictionary()


def fish_http_client() -> httpx.AsyncClient:
    """同一引擎事件循环共用传输，不跨循环借用连接。"""
    loop = asyncio.get_running_loop()
    client = _clients.get(loop)
    if client is None or client.is_closed:
        client = httpx.AsyncClient(
            timeout=httpx.Timeout(60, connect=10, pool=10),
            limits=httpx.Limits(max_connections=8, max_keepalive_connections=4,
                               keepalive_expiry=60),
        )
        _clients[loop] = client
    return client


async def close_fish_http_client() -> None:
    """引擎退出时关闭本循环连接池；单次取消只关闭该请求响应。"""
    client = _clients.pop(asyncio.get_running_loop(), None)
    if client is not None:
        await client.aclose()
