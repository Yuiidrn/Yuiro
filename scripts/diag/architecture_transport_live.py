"""实际Engine的音频帧预算与运行状态检查；不打开麦克风或调用模型。"""
import asyncio
import json
import os
from pathlib import Path

import httpx
import websockets
from websockets.exceptions import ConnectionClosed

ROOT = Path(__file__).resolve().parents[2]


async def main():
    headers = {'x-yuiro-secret': os.environ.get('YUIRO_SHARED_SECRET', '')}
    report = {'scope': 'Real Engine WS oversize admission; no microphone/provider requests'}
    async with websockets.connect('ws://127.0.0.1:8200/ws/audio', additional_headers=headers) as ws:
        await ws.send(b'\0' * 64001)
        try:
            async with asyncio.timeout(5):
                while True:
                    await ws.recv()
        except ConnectionClosed as exc:
            report['oversize_close_code'] = exc.rcvd.code if exc.rcvd else None
    async with httpx.AsyncClient(headers=headers) as client:
        response = await client.get('http://127.0.0.1:8200/api/runtime')
        report['runtime_http_status'] = response.status_code
        data = response.json()
        report['observation'] = data.get('observation')
        report['runtimes'] = data.get('runtimes')
    (ROOT / 'docs/plan/architecture-transport-live.json').write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report))


if __name__ == '__main__':
    asyncio.run(main())
