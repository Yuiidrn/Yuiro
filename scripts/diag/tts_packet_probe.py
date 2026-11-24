"""真实角色音色同文首块对照；不播放、不写历史、不修改角色配置。"""
import argparse
import asyncio
import hashlib
import json
import sys
import time
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'engine'))
TEXTS = ['こんにちは。今日はゆっくり一緒に過ごそうね。',
         '少し疲れたんだね。無理しないで、ここでひと休みしよう。',
         'いいね、その調子。一つずつ確かめながら進めていこう。',
         '待っていてくれてありがとう。お茶を飲みながら、続きを話そう。',
         '静かな時間も好きだよ。何も話さなくても、そばにいるからね。',
         '今日の予定は決まったかな。まずは小さなことから始めよう。']


async def main():
    from yuiro.audio.fish import build_fish_provider
    from yuiro.audio.fish_transport import close_fish_http_client
    from yuiro.characters import CharacterStore
    from yuiro.config import load_config

    parser = argparse.ArgumentParser()
    parser.add_argument('--role', default='hotaru')
    parser.add_argument('--pairs', type=int, default=6)
    parser.add_argument('--chunks', default='480,240')
    parser.add_argument('--output')
    args = parser.parse_args()
    path = ROOT / 'engine/config.toml'
    cfg = CharacterStore(path).resolve(args.role, load_config(path, with_character=False))
    report = {'scope': 'real configured Fish; captured WAV, no player/ASR/LLM/history',
              'role': args.role, 'model': cfg.tts.fish_model,
              'reference_hash': hashlib.sha256(cfg.tts.fish_reference_id.encode()).hexdigest(),
              'samples': []}
    choices = tuple(int(v) for v in args.chunks.split(','))
    out = ROOT / 'docs/plan' / (args.output or f'2026-11-24-tts-packets-{args.role}.json')
    try:
        for index in range(args.pairs):
            for chunk in (choices if index % 2 == 0 else choices[::-1]):
                provider = build_fish_provider(replace(cfg.tts, fish_transport='websocket',
                                                       fish_first_chunk_ms=chunk, segment_streaming=True))
                text = TEXTS[index % len(TEXTS)]
                row = {'pair': index, 'first_chunk_ms': chunk, 'text': text,
                       'first_in_process': index == 0 and chunk == 480}
                started = time.perf_counter()
                try:
                    async with asyncio.timeout(75):
                        total = count = 0
                        async for part in provider.synthesize_stream(text):
                            if not count:
                                row['first_callback_ms'] = round((time.perf_counter()-started)*1000, 3)
                                row['timings'] = part.timings
                            count += 1
                            total += len(part.wav)-44
                        row.update(chunks=count, pcm_bytes=total, audio_duration_ms=round(total/88.2, 2),
                                   total_ms=round((time.perf_counter()-started)*1000, 3))
                except Exception as exc:  # noqa: BLE001 — 不打印供应商正文或密钥
                    row['error'] = type(exc).__name__
                report['samples'].append(row)
                out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
                print(json.dumps(row, ensure_ascii=False), flush=True)
    finally:
        await close_fish_http_client()


if __name__ == '__main__':
    asyncio.run(main())
