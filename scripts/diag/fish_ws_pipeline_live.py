"""真实LLM/出口翻译/生产VoicePipeline/WS；ASR为固定替身，不采麦或播放。"""
import asyncio
import json
import sys
import time
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path('engine').resolve()))
from tts_sentence_admission import production_drain
from yuiro.agent import OpenAIProvider
from yuiro.audio import VoicePipeline
from yuiro.audio.fish import build_fish_provider
from yuiro.audio.render import OutputRenderer
from yuiro.characters import CharacterStore
from yuiro.config import load_config
from yuiro.keychain import load_llm_key


async def main():
    path = Path('engine/config.toml')
    cfg = CharacterStore(path).resolve('hotaru', load_config(path, with_character=False))
    key = load_llm_key()
    assert key and cfg.tts.provider == 'fish'
    llm = OpenAIProvider(cfg.llm.base_url, cfg.llm.model, key)
    translator = OpenAIProvider(cfg.llm.base_url, cfg.llm.model, key, temperature=0)
    renderer = OutputRenderer(translator, display_language=cfg.language.display_language,
                              speak_language=cfg.language.speak_language,
                              timeout_s=cfg.language.translate_timeout_s)
    tts = build_fish_provider(replace(cfg.tts, fish_transport='websocket', segment_streaming=True))
    started = time.perf_counter()
    marks, segments, events = {}, [], []

    def mark(name):
        marks.setdefault(name, round((time.perf_counter()-started)*1000, 1))

    class ASR:
        def transcribe(self, audio):
            return '请用两句简短中文介绍你能陪我做什么，每句不超过十五字。'

    async def sentences(text, sid, callback):
        push = production_drain()
        parts = []
        mark('llmStart')
        async for chunk in llm.stream_text([
            {'role': 'system', 'content': '只输出两句简短中文，不调用工具，不使用Markdown。'},
            {'role': 'user', 'content': text},
        ]):
            if chunk.kind == 'token':
                mark('llmFirstToken')
                parts.append(chunk.content)
                for sentence in push(chunk.content):
                    mark('firstSentence')
                    await callback(sentence)
        for sentence in push('', flush=True):
            mark('firstSentence')
            await callback(sentence)
        mark('llmEnd')
        return ''.join(parts)

    async def play(sid, segment):
        mark('firstAudioDelivered')
        segments.append({'ms': round((time.perf_counter()-started)*1000, 1),
                         'sampleRate': segment.sample_rate, 'bytes': len(segment.wav),
                         'streaming': segment.streaming, 'streamId': segment.stream_id})

    async def event(sid, kind, payload):
        events.append(kind)

    pipe = VoicePipeline(asr=ASR(), tts=tts, renderer=renderer, sentence_llm_callback=sentences,
                         play_callback=play, event_callback=event, asr_lock_cool_ms=0)
    pipe._audio['ws-probe'] = [b'\0\0' * 8000]
    report = {'scope': 'Single isolated production VoicePipeline with real LLM/translation/Fish WS; fixed ASR substitute and captured audio callback, no real microphone/playback/UI/acoustic latency/history writes/config change'}
    try:
        async with asyncio.timeout(75):
            await pipe.on_speech_end('ws-probe')
            task = pipe._speak_tasks.get('ws-probe')
            if task is not None:
                await task
        report['passed'] = bool(segments) and len({s['streamId'] for s in segments}) == 1
    except Exception as exc:  # noqa: BLE001 — 诊断仅记异常类型，禁止供应商正文/凭证。
        report.update(passed=False, errorType=type(exc).__name__)
    finally:
        pending = list(pipe._speak_tasks.values()) + list(pipe._turn_tasks.values())
        stopped = pipe.interrupt('ws-probe')
        if stopped is not None:
            await stopped
        await asyncio.gather(*pending, return_exceptions=True)
        await llm._client.close()
        await translator._client.close()
        report.update(marks=marks, segments=segments, events=events,
                      translationStats=renderer.stats, productionTransportChanged=False)
        Path('docs/plan/fish-ws-pipeline-live.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps({k: v for k, v in report.items() if k not in ('segments', 'events')}, ensure_ascii=False))


if __name__ == '__main__':
    asyncio.run(main())
