"""有限计费传输对比；同音色文本、不播放、不采麦，不改变生产路由。"""
import asyncio
import io
import json
import re
import sys
import time
import urllib.request
import wave
from pathlib import Path

import httpx

sys.path.insert(0, str(Path('engine').resolve()))
import itertools

from yuiro.audio.fish import FishAudioProvider
from yuiro.characters import CharacterStore
from yuiro.config import load_config
from yuiro.keychain import load_fish_key


async def main():
    config_path = Path('engine/config.toml')
    cfg = CharacterStore(config_path).resolve('hotaru', load_config(config_path, with_character=False))
    assert cfg.tts.provider == 'fish' and cfg.tts.segment_streaming
    assert load_fish_key(), 'Configure local secure credential first'
    proxy_present = bool(urllib.request.getproxies().get('https'))
    rows = []
    current = None

    async def trace(name, info):
        if current is None:
            return
        if name.endswith('connect_tcp.started'):
            current['tcpConnects'] += 1
        if name.endswith('start_tls.started'):
            current['tlsStarts'] += 1
        if name.endswith('receive_response_headers.complete'):
            current['headersMs'] = round((time.perf_counter() - current['_started']) * 1000, 1)

    async def attach(request):
        request.extensions['trace'] = trace

    def client(trust_env=True):
        return httpx.AsyncClient(timeout=httpx.Timeout(20, connect=5, pool=5), trust_env=trust_env,
                                 limits=httpx.Limits(max_connections=8, max_keepalive_connections=4,
                                                    keepalive_expiry=60),
                                 event_hooks={'request': [attach]})

    shared = client()
    modes = ['fresh-current', 'pooled-current-cold', 'pooled-current-warm',
             'fresh-direct', 'pooled-current-warm', 'fresh-direct']
    direct_failed = False
    try:
        for index, mode in enumerate(modes):
            if mode == 'fresh-direct' and (not proxy_present or direct_failed):
                continue
            transport = shared if mode.startswith('pooled') else client(mode != 'fresh-direct')
            current = {'sample': index + 1, 'mode': mode, 'tcpConnects': 0, 'tlsStarts': 0,
                       '_started': time.perf_counter()}
            provider = FishAudioProvider(reference_id=cfg.tts.fish_reference_id,
                model=cfg.tts.fish_model, latency=cfg.tts.fish_latency, speed=cfg.tts.fish_speed,
                segment_streaming=True, http_client=transport)
            chunks = []
            try:
                async with asyncio.timeout(30):
                    async for segment in provider.synthesize_stream('こんにちは。今日はどんな一日でしたか？'):
                        with wave.open(io.BytesIO(segment.wav)) as audio:
                            assert audio.getsampwidth() == 2 and audio.getnchannels() == 1
                            duration = audio.getnframes() / audio.getframerate() * 1000
                        chunks.append({'ms': round((time.perf_counter()-current['_started'])*1000, 1),
                                       'durationMs': round(duration, 1)})
                assert chunks
                current.update(firstPlayableChunkMs=chunks[0]['ms'],
                               completeMs=round((time.perf_counter()-current['_started'])*1000, 1),
                               audioDurationMs=round(sum(c['durationMs'] for c in chunks), 1),
                               maximumYieldGapMs=max((round(b['ms']-a['ms'], 1)
                                                     for a, b in itertools.pairwise(chunks)), default=0))
            except (RuntimeError, TimeoutError, httpx.HTTPError) as exc:
                current.update(errorType=type(exc).__name__,
                               elapsedMs=round((time.perf_counter()-current['_started'])*1000, 1))
                status = re.search(r'Fish HTTP (\d{3})', str(exc))
                if status:
                    current['httpStatus'] = int(status.group(1))
                if mode == 'fresh-direct':
                    direct_failed = True
            finally:
                if transport is not shared:
                    await transport.aclose()
            current.pop('_started')
            current['chunks'] = chunks
            rows.append(current)
            print(json.dumps({k: v for k, v in current.items() if k != 'chunks'}), flush=True)
            Path('docs/plan/fish-transport-probe.json').write_text(json.dumps({
                'scope': 'Maximum six interleaved independent paid requests through production Fish provider with explicitly injected transport; unchanged voice/model/latency/text; no playback/microphone/config change; too few for causal latency SLA',
                'systemHttpsProxyPresent': proxy_present, 'rows': rows,
                'directRouteChangedInProduction': False}, ensure_ascii=False, indent=2), encoding='utf-8')
            if current.get('httpStatus') in (401, 402, 403, 429):
                break
    finally:
        await shared.aclose()


if __name__ == '__main__':
    asyncio.run(main())
