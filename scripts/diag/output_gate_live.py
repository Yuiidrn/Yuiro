"""真实控制端点验证实验门禁；只期待拒绝，不调用工具/麦克风。"""
import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

import httpx
import websockets

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'engine'))


async def main():
    from yuiro.config import load_config
    parser = argparse.ArgumentParser()
    parser.add_argument('--expected-role', required=True, choices=['hotaru','hiyori'])
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    cfg = load_config(ROOT/'engine/config.toml', with_character=False)
    async with httpx.AsyncClient(trust_env=False) as client:
        role = (await client.get('http://127.0.0.1:8200/api/characters')).json()['active_id']
    if role != args.expected_role:
        raise RuntimeError('unexpected active role')
    started = time.perf_counter()
    async with websockets.connect('ws://127.0.0.1:8200/ws/control',
            additional_headers={'x-yuiro-secret':cfg.server.shared_secret}) as ws:
        async with asyncio.timeout(8):
            while json.loads(await ws.recv()).get('type') != 'session:ready':
                pass
            await ws.send(json.dumps({'type':'chat:user', 'text':'你好。',
                'stream_reply':True,'bilingual_order':'ja_first','reply_request_id':'gate-probe'}))
            observed = []
            while True:
                frame = json.loads(await ws.recv())
                observed.append(frame.get('type'))
                if frame.get('type') == 'tts:reply_audio':
                    raise AssertionError('disabled experiment produced audio')
                if frame.get('type') == 'chat:busy':
                    if frame.get('reason') != 'bilingual_experiment_disabled':
                        raise AssertionError('unexpected rejection reason')
                    break
    report = {'role':role, 'passed':True, 'observed':observed,
              'elapsed_ms':round((time.perf_counter()-started)*1000, 3),
              'scope':'real gate refusal before generation; no model/tool/ASR call'}
    (ROOT/'docs/plan'/args.output).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False))


if __name__ == '__main__':
    asyncio.run(main())
