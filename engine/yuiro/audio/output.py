"""既有输出管线的共享句子通道与逐句翻译/合成，不拥有新的 Runtime。"""
from __future__ import annotations

import asyncio
import contextlib
from collections import deque

from yuiro.audio.speech_text import speech_body
from yuiro.logger import vlog


class SentenceChannel:
    """有界、可结束的句子通道；finish 不向满队列塞哨兵。"""

    def __init__(self, capacity=4, wait_s=5.0):
        if capacity < 1 or wait_s <= 0:
            raise ValueError('sentence channel requires positive budgets')
        self.capacity = capacity
        self.wait_s = wait_s
        self._items = deque()
        self._condition = asyncio.Condition()
        self._closed = False
        self.peak = 0

    async def put(self, text):
        async with asyncio.timeout(self.wait_s):
            async with self._condition:
                await self._condition.wait_for(
                    lambda: self._closed or len(self._items) < self.capacity)
                if self._closed:
                    raise RuntimeError('sentence channel closed')
                if len(text) > 16000:
                    raise ValueError('sentence exceeds output budget')
                self._items.append(text)
                self.peak = max(self.peak, len(self._items))
                self._condition.notify_all()

    async def finish(self, *, discard=False):
        async with self._condition:
            self._closed = True
            if discard:
                self._items.clear()
            self._condition.notify_all()

    async def __aiter__(self):
        while True:
            async with self._condition:
                await self._condition.wait_for(lambda: self._closed or bool(self._items))
                if not self._items:
                    return
                item = self._items.popleft()
                self._condition.notify_all()
            yield item


async def translated_sentences(source, render, check, trace=None):
    """文字/语音/Presence 共用的清洗、翻译和旧代屏障。"""
    async for text in source:
        check()
        clean = speech_body(text)
        if not any(c.isalnum() for c in clean):
            continue
        if trace:
            trace.mark('translation_start')
        value = await render(clean)
        check()
        if trace:
            trace.mark('lang_render')
        if value and any(c.isalnum() for c in value):
            yield value


async def sentence_audio(tts, sentences, *, prepared=None):
    """同一 provider 的 WS 持续输入或 HTTP 逐句合成，保序且无隐式重试。"""
    if prepared is not None:
        async with contextlib.aclosing(prepared.stream(sentences)) as stream:
            async for part in stream:
                yield part
        return
    async for sentence in sentences:
        try:
            stream = getattr(tts, 'synthesize_stream', None)
            if callable(stream):
                async with contextlib.aclosing(stream(sentence)) as chunks:
                    async for part in chunks:
                        yield part
            else:
                yield await tts.synthesize_segment(sentence)
        except Exception as exc:  # noqa: BLE001 — 沿用单句失败跳过，不重试或换音色
            vlog('tts', f'单句合成失败: {type(exc).__name__}')


class ReplyStream:
    """文字入口的单轮输出桥；任务仍登记到现有 reply task 表。"""

    def __init__(self, speak, register, generation, trace=None, prepare=None):
        self.channel = SentenceChannel()
        self.speak = speak
        self.register = register
        self.generation = generation
        self.trace = trace
        self.task = None
        self.disabled = False
        self.sent = False
        self.prepare = prepare
        self.ready = asyncio.Event()
        self.owner_generation = None
        self.failure = None
        if prepare:
            self._start()

    def _start(self):
        async def run():
            prepared = None
            try:
                prepared = self.prepare() if self.prepare else None
                await self.ready.wait()
                await self.speak(self.channel, self.owner_generation, prepared)
            finally:
                if prepared is not None:
                    await prepared.close()
        self.task = asyncio.create_task(run())
        self.register(self.task)

    async def send(self, sentence):
        if self.disabled:
            return
        if self.task is None:
            if self.trace:
                self.trace.mark('first_sentence')
            self._start()
        if not self.ready.is_set():
            self.owner_generation = self.generation()
            self.ready.set()
            if self.trace:
                self.trace.mark('first_sentence')
        if self.task.done():
            await asyncio.gather(self.task, return_exceptions=True)
            self.disabled = True
            return
        try:
            await self.channel.put(sentence)
            self.sent = True
        except (TimeoutError, RuntimeError, ValueError) as exc:
            self.failure = type(exc).__name__
            # 声音慢/退出不拖死文字回答；显式丢弃本轮剩余声音，不重发已播句。
            await self.abort()

    async def finish(self, fallback=''):
        if not self.sent and not self.disabled and fallback.strip():
            await self.send(fallback)
        await self.channel.finish()
        if not self.sent and self.task:
            await self.abort()

    async def abort(self):
        self.disabled = True
        await self.channel.finish(discard=True)
        if self.task is not None:
            if not self.task.done() and not self.task.cancelling():
                self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
