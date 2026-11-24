"""真实配置下的新旧control协议顺序校验，不播放音频或打开麦克风。"""
import asyncio
import json
import os
from pathlib import Path

import websockets

ROOT = Path(__file__).resolve().parents[2]


async def main():
    rows = []
    for streaming in (False, True):
        headers = {'x-yuiro-secret': os.environ.get('YUIRO_SHARED_SECRET', '')}
        async with websockets.connect('ws://127.0.0.1:8200/ws/control',
                                       additional_headers=headers) as ws:
            async with asyncio.timeout(60):
                while json.loads(await ws.recv()).get('type') != 'session:ready':
                    pass
                request = {'type': 'chat:user', 'text': '请只回复“你好呀。”，不要调用工具。',
                           'web_search': False}
                if streaming:
                    request['stream_reply'] = True
                await ws.send(json.dumps(request))
                events = []
                while True:
                    event = json.loads(await ws.recv())
                    events.append(event['type'])
                    if event['type'] == 'approval:required':
                        raise RuntimeError('unexpected approval; not accepted')
                    if event['type'] == 'tts:reply_end':
                        break
                assert 'chat:assistant' in events and 'tts:reply_audio' in events
                if not streaming:
                    assert events.index('chat:assistant') < events.index('tts:reply_audio')
                rows.append({'stream_reply': streaming, 'types': events, 'passed': True})
    (ROOT / 'docs/plan/architecture-compat-live.json').write_text(
        json.dumps(rows, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(rows))


if __name__ == '__main__':
    asyncio.run(main())
