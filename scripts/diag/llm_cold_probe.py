"""真实安装的SDK冷资源测量；假地址/假凭证，无网络请求。"""
import argparse
import asyncio
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'engine'))


def child(mode):
    import openai
    from yuiro.agent import OpenAIProvider
    started = time.perf_counter()
    if mode == 'before':
        # 与改前构造完全相同：资源在首轮才读取。
        client = openai.AsyncOpenAI(base_url='https://example.invalid/v1', api_key='fixture',
            timeout=openai.Timeout(connect=10, read=30, write=30, pool=10), max_retries=0)
    else:
        client = OpenAIProvider('https://example.invalid/v1', 'fixture', 'fixture')._client
    constructed = time.perf_counter()
    _ = client.chat.completions
    end = time.perf_counter()
    asyncio.run(client.close())
    print(json.dumps({'mode':mode,'construction_ms':round((constructed-started)*1000,3),
                      'first_turn_resource_ms':round((end-constructed)*1000,3)}))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--child', choices=['before','after'])
    args = parser.parse_args()
    if args.child:
        child(args.child)
        return
    rows = []
    for index in range(3):
        for mode in (('before','after') if index % 2 == 0 else ('after','before')):
            result = subprocess.run([sys.executable,__file__,'--child',mode], capture_output=True,
                                    text=True,check=True)
            rows.append(json.loads(result.stdout.strip().splitlines()[-1]))
    report = {'scope':'offline real installed SDK; fresh process each sample; no requests, '
                      'initialization moved to existing provider construction, not removed',
              'samples':rows}
    (ROOT/'docs/plan/2026-11-24-llm-cold-resources.json').write_text(
        json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False))


if __name__ == '__main__':
    main()
