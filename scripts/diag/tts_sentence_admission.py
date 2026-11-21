"""测生产_agent_reply内实际_drain的首句交付；不请求模型或TTS。"""
import argparse
import ast
import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path('engine').resolve()))


def production_drain(source_path=None):
    tree = ast.parse((source_path or Path('engine/yuiro/main.py')).read_text(encoding='utf-8'))
    reply = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == '_agent_reply')
    drain = next(n for n in reply.body if isinstance(n, ast.FunctionDef) and n.name == '_drain')
    # 外层仅提供生产闭包所需变量；切分逻辑直接编译本仓库函数。
    setup = ast.parse('''def make():
    pending = ''
    sent_any = False
    on_sentence = True
    def push(text, flush=False):
        nonlocal pending
        pending += text
        return _drain(flush)
    return push
''')
    setup.body[0].body.insert(3, drain)
    scope = {}
    exec(compile(ast.fix_missing_locations(setup), 'production _drain', 'exec'), scope)  # noqa: S102
    return scope['make']()


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True)
    options = parser.parse_args()
    cases = {
        'short-prefix': ['嗯。', '我正在帮你核对这件事情。', '后面的解释还在继续生成，', '最后再补充一些说明。'],
        'normal': ['我正在帮你核对这件事情。', '后面的解释还在继续生成，', '最后再补充一些说明。'],
    }
    rows = []
    for case, chunks in cases.items():
        for sample in range(5):
            push = production_drain()
            started = time.perf_counter()
            emitted = []
            for index, chunk in enumerate(chunks):
                await asyncio.sleep(.02 if index < 2 else .15)
                for sentence in push(chunk):
                    emitted.append({'text': sentence, 'ms': round((time.perf_counter()-started)*1000, 3),
                                    'inputChunksReceived': index + 1})
            for sentence in push('', flush=True):
                emitted.append({'text': sentence, 'ms': round((time.perf_counter()-started)*1000, 3),
                                'inputChunksReceived': len(chunks)})
            assert ''.join(r['text'] for r in emitted) == ''.join(chunks)
            rows.append({'case': case, 'sample': sample + 1, 'firstAdmissionMs': emitted[0]['ms'],
                         'firstAdmissionInputChunks': emitted[0]['inputChunksReceived'], 'emitted': emitted})
    Path(options.output).write_text(json.dumps({'scope': 'Actual production nested sentence drain with deterministic synthetic token delays; not provider/translation/audio TTFA',
                                               'rows': rows}, ensure_ascii=False, indent=2), encoding='utf-8')
    for case in cases:
        values = sorted(r['firstAdmissionMs'] for r in rows if r['case'] == case)
        print(case, 'medianAdmissionMs', values[len(values)//2])


if __name__ == '__main__':
    asyncio.run(main())
