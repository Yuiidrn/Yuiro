"""默认关闭的双语句对实验；只消费现有 LLM，不执行工具、不写历史或记忆。"""
from __future__ import annotations

import asyncio
import contextlib
import json
import re


def experiment_allowed(order, enabled, speak_language):
    return (enabled == '1' and order in ('baseline', 'ja_first', 'zh_first')
            and (order == 'baseline' or speak_language == 'ja'))


class MeasuredLLM:
    """实验翻译仍调用原 adapter，只累计供应商返回的用量与等待时间。"""
    def __init__(self, llm, metrics):
        self.llm, self.metrics = llm, metrics

    async def stream_text(self, *args, **kwargs):
        import time
        started = time.perf_counter()
        item = {}
        self.metrics.setdefault('translation_calls', []).append(item)
        stream = self.llm.stream_text(*args, **kwargs)
        try:
            async with contextlib.aclosing(stream):
                async for chunk in stream:
                    if chunk.kind == 'done':
                        item['usage'] = chunk.usage
                    yield chunk
        finally:
            item['elapsed_ms'] = round((time.perf_counter()-started)*1000, 3)


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate bilingual field')
        result[key] = value
    return result


class PairParser:
    def __init__(self, order):
        if order not in ('ja_first', 'zh_first'):
            raise ValueError('unknown bilingual order')
        self.keys = ['ja', 'zh'] if order == 'ja_first' else ['zh', 'ja']
        self.pending = ''
        self.total = self.count = 0
        self.ja_ready = False

    def feed(self, token, *, final=False):
        self.total += len(token)
        self.pending += token
        if self.total > 32768:
            raise ValueError('bilingual response budget')
        # 只观测已闭合的日语 JSON 字符串；不在完整句对校验前交给 TTS。
        match = re.search(r'"ja"\s*:\s*', self.pending)
        if match and not self.ja_ready:
            try:
                value, _ = json.JSONDecoder().raw_decode(self.pending[match.end():])
                self.ja_ready = isinstance(value, str)
            except json.JSONDecodeError:
                pass
        result = []
        decoder = json.JSONDecoder(object_pairs_hook=_unique)
        while self.pending.strip():
            self.pending = self.pending.lstrip()
            try:
                pair, end = decoder.raw_decode(self.pending)
            except json.JSONDecodeError:
                if final:
                    raise
                break
            if end > 4096:
                raise ValueError('bilingual line budget')
            self.pending = self.pending[end:]
            if not isinstance(pair, dict) or list(pair) != self.keys:
                raise ValueError('bilingual fields/order')
            for value in pair.values():
                if (not isinstance(value, str) or not value.strip() or len(value) > 1500
                        or re.search(r'[<>\[\]{}\n\r]|```|(?:tool(?:_call)?|function(?:_call)?|emotion|motion|角色|日语|中文)\s*[:：]', value, re.IGNORECASE)
                        or re.match(r'\s*(?:ja|zh|jp|cn|japanese|chinese|speech|display|voice|日文|日本語|中国語)\s*[:：]', value, re.IGNORECASE)):
                    raise ValueError('bilingual control/invalid text')
                if value.rstrip()[-1] not in '。！？!?」”':
                    raise ValueError('bilingual incomplete sentence')
            if not re.search(r'[ぁ-ヿ]', pair['ja']) or not re.search(r'[\u3400-\u9fff]', pair['zh']):
                raise ValueError('bilingual language guard')
            self.count += 1
            if self.count > 16:
                raise ValueError('bilingual pair budget')
            result.append(pair)
        if len(self.pending) > 4096:
            raise ValueError('bilingual line budget')
        return result


async def generate_pairs(llm, persona, text, order, deliver, check, trace, metrics):
    parser = PairParser(order)
    fields = '{"ja":"完整自然的日语句子。","zh":"语义对应的中文句子。"}'
    if order == 'zh_first':
        fields = '{"zh":"语义对应的中文句子。","ja":"完整自然的日语句子。"}'
    prompt = (persona + '\n这是隔离的角色闲聊实验，不提供工具、外部操作或记忆。'
              '若要求执行操作，只解释这里不能执行。每行仅输出一个JSON对象，顺序严格为'
              + fields + '。每对是一句完整日语朗读及对应中文显示。'
              '用自然角色口吻，两种语言语义一致。禁止代码围栏、前缀、动作、表情和工具标签。')
    trace.mark('llm_request')
    stream = llm.stream_text([{'role': 'system', 'content': prompt},
                             {'role': 'user', 'content': text}], max_tokens=2048)
    output = []
    metrics['sentences'] = []

    async def consume(token='', final=False):
        pairs = parser.feed(token, final=final)
        if parser.ja_ready:
            trace.mark('bilingual_ja_ready')
        for pair in pairs:
            check()
            trace.mark('bilingual_pair_ready')
            await deliver(pair)
            output.append(pair['zh'])
            metrics['sentences'].append(pair)

    async with asyncio.timeout(60), contextlib.aclosing(stream):
        async for chunk in stream:
            check()
            if chunk.kind == 'token':
                trace.mark('llm_first_token')
                await consume(chunk.content)
            elif chunk.kind == 'done':
                metrics['usage'] = chunk.usage
            else:
                raise ValueError('bilingual non-text output rejected')
        await consume(final=True)
    if not output:
        raise ValueError('bilingual empty output')
    metrics.update(order=order, pairs=len(output), generated_chars=parser.total)
    trace.mark('bilingual_generation_end')
    return ''.join(output)


async def generate_conventional(llm, persona, text, deliver, check, trace, metrics):
    """匹配实验上下文的对照组：原有中文分句及独立翻译，不注入记忆/工具。"""
    from yuiro.audio.speech_text import sentence_boundary
    pending = ''
    result = []
    sent = False
    prompt = (persona + '\n这是隔离的角色闲聊实验，不提供工具、外部操作或记忆。'
              '若要求执行操作，只解释这里不能执行。只输出自然角色口吻的完整中文句子，'
              '禁止代码围栏、前缀、动作、表情和工具标签。')
    trace.mark('llm_request')
    stream = llm.stream_text([{'role':'system', 'content':prompt},
                             {'role':'user', 'content':text}], max_tokens=2048)
    async with asyncio.timeout(60), contextlib.aclosing(stream):
        async for chunk in stream:
            check()
            if chunk.kind == 'token':
                trace.mark('llm_first_token')
                pending += chunk.content
                result.append(chunk.content)
                if sum(map(len, result)) > 32768:
                    raise ValueError('conventional response budget')
                while True:
                    end = sentence_boundary(pending, min_len=12 if sent else 6)
                    if end < 0:
                        break
                    await deliver({'zh':pending[:end+1]})
                    pending = pending[end+1:]
                    sent = True
            elif chunk.kind == 'done':
                metrics['usage'] = chunk.usage
            else:
                raise ValueError('conventional non-text output rejected')
        if pending.strip():
            await deliver({'zh':pending})
    trace.mark('bilingual_generation_end')
    metrics.update(order='baseline', generated_chars=sum(map(len, result)))
    return ''.join(result)
