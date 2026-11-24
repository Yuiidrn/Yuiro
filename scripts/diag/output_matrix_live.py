"""真实双角色对照与混合负载；串行采样，最后恢复 Hotaru，不保存凭证。"""
import argparse
import asyncio
import hashlib
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx
import psutil

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'engine'))
PROMPTS = [
    '今天有点累，陪我休息一下吧。请用两句简短回应，不要调用工具。',
    '刚刚完成了一件拖很久的事，夸夸我吧。请用两句简短回应，不要调用工具。',
    '今晚想安静看雨，陪我聊聊。请用四句简短回应，不要调用工具。',
]


def processes():
    rows = []
    for process in psutil.process_iter(['pid', 'name', 'memory_info', 'num_threads', 'cmdline']):
        try:
            cmd = ' '.join(process.info['cmdline'] or [])
            if ('uvicorn yuiro.main:app' in cmd or
                    ('Yuiro' in cmd and 'electron.exe' in process.info['name'].lower())):
                rows.append({'pid': process.pid, 'name':process.info['name'],
                             'rss_bytes':process.info['memory_info'].rss,
                             'private_bytes':getattr(process.info['memory_info'], 'private', 0),
                             'threads':process.info['num_threads']})
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return rows


async def main():
    from yuiro.characters import CharacterStore
    from yuiro.config import load_config
    parser = argparse.ArgumentParser()
    parser.add_argument('--duration-seconds', type=int, default=1800)
    parser.add_argument('--rounds', type=int, default=2)
    parser.add_argument('--roles', default='hotaru,hiyori')
    parser.add_argument('--output', default='2026-11-24-output-matrix.json')
    parser.add_argument('--controlled', action='store_true')
    args = parser.parse_args()
    path = ROOT / 'engine/config.toml'
    config = load_config(path, with_character=False)
    headers = {'x-yuiro-secret':config.server.shared_secret}
    store = CharacterStore(path)
    out = ROOT / 'docs/plan' / args.output
    detail = ROOT / '.env-local' / out.stem
    detail.mkdir(exist_ok=True)
    report = {'started_utc':datetime.now(UTC).isoformat(), 'samples':[], 'snapshots':[],
              'switches':[], 'roles':{}, 'scope':'real configured LLM/Fish/renderer graph; '
              'matched experiment context, no memory/tools, baseline translation cache disabled; '
              'ordinary mode includes existing AgentLoop/memory/cache and is not a matched control'}
    for role in ('hotaru', 'hiyori'):
        cfg = store.resolve(role, config)
        report['roles'][role] = {'provider':cfg.tts.provider, 'model':cfg.tts.fish_model,
            'reference_hash':hashlib.sha256(cfg.tts.fish_reference_id.encode()).hexdigest(),
            'asset':cfg.persona.model_path if hasattr(cfg.persona, 'model_path') else '',
            'speak_language':cfg.language.speak_language}
    started = time.monotonic()
    def save():
        report['elapsed_seconds'] = round(time.monotonic()-started, 2)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    async with httpx.AsyncClient(base_url='http://127.0.0.1:8200', headers=headers,
                                 timeout=90, trust_env=False) as client:
        for _ in range(120):
            try:
                if (await client.get('/health', timeout=2)).status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            await asyncio.sleep(.5)
        else:
            raise RuntimeError('engine not ready within startup budget')
        async def switch(role):
            response = await client.post('/api/characters/switch', json={'id':role})
            response.raise_for_status()
            value = response.json()
            report['switches'].append({'role':role, 'switch_ms':value.get('switch_ms'),
                                      'active_id':value.get('active_id')})
            save()
        try:
            round_index = 0
            while round_index < args.rounds or time.monotonic()-started < args.duration_seconds:
                roles = tuple(args.roles.split(','))
                if round_index % 2:
                    roles = roles[::-1]
                for role in roles:
                    await switch(role)
                    modes = ('baseline', 'ja_first', 'zh_first')
                    modes = modes[round_index % 3:] + modes[:round_index % 3]
                    for offset, mode in enumerate(modes):
                        prompt_index = round_index % len(PROMPTS)
                        # 每轮每个角色的三种模式均为同题；轮间轮转顺序。
                        cancel = not args.controlled and round_index > 1 and (round_index+offset) % 4 == 0
                        ordinary = not args.controlled and round_index > 1 and (round_index+offset) % 5 == 0
                        filename = f'{len(report["samples"]):04d}-{role}-{mode}.json'
                        target = detail / filename
                        command = [sys.executable, str(ROOT/'scripts/diag/runtime_renderer_live.py'),
                            '--samples','1','--prompt',PROMPTS[prompt_index],
                            '--output',str(target), '--expected-role',role]
                        if not ordinary:
                            command += ['--bilingual-order',mode]
                        if cancel:
                            command += ['--cancel-all']
                            if round_index % 2:
                                command += ['--cancel-before-audio']
                        child = await asyncio.create_subprocess_exec(*command,
                            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
                        try:
                            await asyncio.wait_for(child.wait(), 115)
                        except TimeoutError:
                            child.kill()
                            await child.wait()
                        if child.returncode == 0 and target.exists():
                            evidence = json.loads(target.read_text(encoding='utf-8'))
                            row = evidence['samples'][0]
                            row['renderer_state'] = evidence['state']
                        else:
                            row = {'error':'diagnostic_process_failed', 'exit_code':child.returncode}
                        row.update(role=role, mode='ordinary' if ordinary else mode,
                                   round=round_index, prompt_index=prompt_index, cancel=cancel)
                        report['samples'].append(row)
                        runtime = (await client.get('/api/runtime')).json()
                        report['snapshots'].append({'sample':len(report['samples']),
                            'processes':processes(), 'observation':runtime.get('observation'),
                            'utc':datetime.now(UTC).isoformat()})
                        save()
                        print(json.dumps({'n':len(report['samples']), 'role':role,
                            'mode':row['mode'], 'first_ms':row.get('first_graph_start_ms'),
                            'cancel':cancel,'error':row.get('error'),
                            'elapsed_seconds':report['elapsed_seconds']}), flush=True)
                round_index += 1
        finally:
            await switch('hotaru')
            report['finished_utc'] = datetime.now(UTC).isoformat()
            save()


if __name__ == '__main__':
    asyncio.run(main())
