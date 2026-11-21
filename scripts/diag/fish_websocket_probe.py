"""Fish官方WS协议有界验证；不接入生产、不播放、不采麦。"""
import argparse
import asyncio
import json
import sys
import time
import urllib.request
from pathlib import Path

import msgpack
import websockets

sys.path.insert(0, str(Path('engine').resolve()))
from yuiro.characters import CharacterStore
from yuiro.config import load_config
from yuiro.keychain import load_fish_key


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--lead-ms', type=int, default=0)
    parser.add_argument('--output', default='docs/plan/fish-websocket-probe.json')
    options = parser.parse_args()
    if not 0 <= options.lead_ms <= 5000:
        raise ValueError('lead-ms must be between 0 and 5000')
    path = Path('engine/config.toml')
    cfg = CharacterStore(path).resolve('hotaru', load_config(path, with_character=False))
    assert cfg.tts.provider == 'fish'
    key = load_fish_key()
    assert key
    rows = []
    for mode in ['whole-text', 'first-phrase-then-remainder']:
        started = time.perf_counter()
        row = {'mode': mode, 'audioMessages': 0, 'pcmBytes': 0}

        async def text_ready(started=started):
            await asyncio.sleep(options.lead_ms / 1000)
            return round((time.perf_counter()-started)*1000, 1)

        ready = asyncio.create_task(text_ready())
        try:
            async with asyncio.timeout(45), websockets.connect('wss://api.fish.audio/v1/tts/live',
                additional_headers={'Authorization': f'Bearer {key}', 'model': cfg.tts.fish_model},
                proxy=urllib.request.getproxies().get('https') or True,
                open_timeout=10, max_size=8_000_000) as socket:
                row['connectMs'] = round((time.perf_counter()-started)*1000, 1)
                row['textReadyMs'] = await ready
                row['connectionReadyBeforeText'] = row['connectMs'] <= row['textReadyMs']

                async def send(payload):
                    await socket.send(msgpack.packb(payload, use_bin_type=True))

                await send({'event': 'start', 'request': {'text': '', 'reference_id': cfg.tts.fish_reference_id,
                    'format': 'pcm', 'sample_rate': 44100, 'latency': cfg.tts.fish_latency,
                    'prosody': {'speed': cfg.tts.fish_speed}}})
                await send({'event': 'text', 'text': 'こんにちは。今日はどんな一日でしたか？'
                            if mode == 'whole-text' else 'こんにちは。'})
                await send({'event': 'flush'})
                remainder = mode != 'whole-text'
                if not remainder:
                    await send({'event': 'stop'})
                previous = None
                gaps = []
                async for packet in socket:
                    event = msgpack.unpackb(packet, raw=False)
                    if event.get('event') == 'audio':
                        audio = event.get('audio', b'')
                        if not isinstance(audio, bytes) or not audio:
                            continue
                        now = round((time.perf_counter()-started)*1000, 1)
                        row.setdefault('firstRawAudioMs', now)
                        if previous is not None:
                            gaps.append(round(now-previous, 1))
                        previous = now
                        row['pcmBytes'] += len(audio)
                        row['audioMessages'] += 1
                        if row['pcmBytes'] >= 44100*2*.48:
                            row.setdefault('first480msPlayableMs', now)
                        if remainder:
                            row['remainderSentAfterFirstAudioMs'] = now
                            await send({'event': 'text', 'text': '今日はどんな一日でしたか？'})
                            await send({'event': 'flush'})
                            await send({'event': 'stop'})
                            remainder = False
                    elif event.get('event') == 'finish':
                        row['finishReason'] = event.get('reason')
                        row['completeMs'] = round((time.perf_counter()-started)*1000, 1)
                        break
                    elif event.get('event') == 'error':
                        row['errorType'] = 'ServerErrorEvent'
                        break
                row['audioDurationMs'] = round(row['pcmBytes']/2/44100*1000, 1)
                row['maximumAudioMessageGapMs'] = max(gaps, default=0)
                row['passed'] = row.get('finishReason') == 'stop' and 'first480msPlayableMs' in row
        except (websockets.exceptions.WebSocketException, OSError, TimeoutError,
                ValueError, TypeError) as exc:
            row.update(errorType=type(exc).__name__, elapsedMs=round((time.perf_counter()-started)*1000, 1),
                       passed=False)
            response = getattr(exc, 'response', None)
            if response is not None:
                row['httpStatus'] = response.status_code
        finally:
            ready.cancel()
            await asyncio.gather(ready, return_exceptions=True)
        if 'first480msPlayableMs' in row:
            row['first480msAfterTextReadyMs'] = round(row['first480msPlayableMs']-row['textReadyMs'], 1)
        rows.append(row)
        print(json.dumps(row), flush=True)
        Path(options.output).write_text(json.dumps({
            'scope': 'Maximum two standalone actual official MessagePack WS requests; same Hotaru voice/model/latency/speed and combined text, PCM16 at 44100, first480ms matches HTTP local block threshold; no production replacement/playback/microphone or translation',
            'simulatedTextLeadMs': options.lead_ms, 'rows': rows}, indent=2), encoding='utf-8')
        if not row.get('passed'):
            break


if __name__ == '__main__':
    asyncio.run(main())
