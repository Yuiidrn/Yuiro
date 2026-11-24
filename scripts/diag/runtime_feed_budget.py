"""隔离执行 HEAD/工作区真实投喂函数，比较慢翻译下的任务峰值。

只调用替身依赖，不启动 main、不读密钥、不调用云服务。
"""
import ast
import asyncio
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from types import MethodType

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'engine'))


async def measure(source):
    from yuiro import audio

    tree = ast.parse(source)
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'VoicePipeline')
    node = next(n for n in cls.body if isinstance(n, ast.AsyncFunctionDef)
                and n.name == '_speak_impl')
    scope = dict(vars(audio))
    scope['vlog'] = lambda *args: None
    exec(compile(ast.Module(body=[node], type_ignores=[]), 'production feed', 'exec'), scope)  # noqa: S102
    release, entered = asyncio.Event(), asyncio.Event()
    active = peak = total = 0
    played = []

    class Renderer:
        async def render_speak(self, text):
            nonlocal active, peak, total
            active += 1
            total += 1
            peak = max(active, peak)
            if active >= 4:
                entered.set()
            try:
                await release.wait()
                return text
            finally:
                active -= 1

    class TTS:
        async def synthesize_segment(self, text):
            return audio.AudioSegment(wav=text.encode(), sample_rate=24000, volumes=[])

    async def play(sid, segment):
        played.append(segment.wav.decode())

    pipe = audio.VoicePipeline(tts=TTS(), renderer=Renderer(), play_callback=play,
                               asr_lock_cool_ms=0)
    pipe._speak_impl = MethodType(scope['_speak_impl'], pipe)
    sentences = [f'第{i}句' for i in range(64)]
    task = asyncio.create_task(pipe._speak_impl('probe', sentences=sentences))
    try:
        await asyncio.wait_for(entered.wait(), 2)
        for _ in range(20):
            await asyncio.sleep(0)
        result = {'blocked_translation_peak': peak, 'admitted_while_blocked': total}
        release.set()
        await asyncio.wait_for(task, 3)
        result.update(ordered_lossless=played == sentences, active_after=active,
                      source_sha256=hashlib.sha256(source.encode()).hexdigest())
        return result
    finally:
        release.set()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def main():
    raw = await asyncio.to_thread(subprocess.check_output,
                                  ['git', 'show', 'HEAD:engine/yuiro/audio/__init__.py'], cwd=ROOT)
    before = raw.decode('utf-8')
    after = (ROOT / 'engine/yuiro/audio/__init__.py').read_text(encoding='utf-8')
    result = {'kind': 'production_function_with_fake_dependencies_NOT_real_audio_latency',
              'before': await measure(before), 'after': await measure(after)}
    output = ROOT / 'docs/plan/runtime-feed-budget-evidence.json'
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    asyncio.run(main())
