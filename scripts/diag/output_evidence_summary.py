"""从保留的原始测量计算汇总，不把缓存、换角或取消混入匹配时延。"""
import hashlib
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PLAN = ROOT / 'docs/plan'


def stats(values):
    values = sorted(v for v in values if v is not None)
    if not values:
        return {'n':0}
    return {'n':len(values), 'p50':round(values[math.ceil(len(values)*.5)-1], 3),
            'p95':round(values[math.ceil(len(values)*.95)-1], 3),
            'max':round(values[-1], 3), 'min':round(values[0], 3)}


def samples(name):
    path = PLAN / name
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else None


def group(rows):
    def stage(row, left, right):
        marks = row.get('stages_ms', {})
        return marks[right]-marks[left] if left in marks and right in marks else None
    def token_total(row, key):
        metrics = row.get('audio_experiment', row.get('experiment', {}))
        calls = [metrics.get('usage') or {}]
        calls += [item.get('usage') or {} for item in metrics.get('translation_calls', [])]
        if any(key not in item for item in calls):
            return None
        return sum(item.get(key, 0) for item in calls)
    return {'completed':all(r.get('completed') for r in rows),
            'peak_queue_bytes':max((r.get('peak_queued_bytes', 0) for r in rows),default=0),
            'peak_decode_ahead_seconds':max((r.get('peak_decode_ahead_seconds', 0) for r in rows),default=0),
            'first_graph_ms':stats([r.get('first_graph_start_ms') for r in rows]),
            'ja_field_ms':stats([r.get('stages_ms', {}).get('bilingual_ja_ready') for r in rows]),
            'first_readable_ja_ms':stats([r.get('stages_ms', {}).get('lang_render',
                r.get('stages_ms', {}).get('bilingual_ja_ready')) for r in rows]),
            'pair_ms':stats([r.get('stages_ms', {}).get('bilingual_pair_ready') for r in rows]),
            'translation_ms':stats([stage(r,'translation_start','lang_render') for r in rows]),
            'generation_ms':stats([stage(r,'llm_request','bilingual_generation_end') for r in rows]),
            'generated_reply_tokens':stats([(r.get('experiment', {}).get('usage') or {}).get('completion_tokens') for r in rows]),
            'total_completion_tokens':stats([token_total(r,'completion_tokens') for r in rows]),
            'total_prompt_tokens':stats([token_total(r,'prompt_tokens') for r in rows]),
            'generation_to_playback_done_ms':stats([r.get('total_ms') for r in rows]),
            'wire_delivery_ms':stats([r.get('wire_delivery_ms') for r in rows])}


def main():
    output = {'packets':{}, 'controlled':{}, 'soak':{}}
    for name in ('2026-11-24-tts-packets-hotaru.json', '2026-11-24-tts-packets-hotaru-400.json'):
        report = samples(name)
        for budget in sorted({r['first_chunk_ms'] for r in report['samples']}):
            rows = [r for r in report['samples'] if r['first_chunk_ms'] == budget and not r.get('error')]
            output['packets'][f'{name}:{budget}'] = {
                'first_callback_ms':stats([r['first_callback_ms'] for r in rows]),
                'raw_ttfb_ms':stats([r['timings']['raw_first_audio_ms']-r['timings']['first_flush_sent_ms'] for r in rows]),
                'accumulation_ms':stats([r['timings']['first_playable_ms']-r['timings']['raw_first_audio_ms'] for r in rows]),
                'split_cpu_ms':stats([r['timings']['split_cpu_ms'] for r in rows]),
                'rms_cpu_ms':stats([r['timings']['rms_cpu_ms'] for r in rows])}
    controlled = samples('2026-11-24-output-controlled-final.json')
    if controlled:
        for mode in ('baseline', 'ja_first', 'zh_first'):
            rows = [r for r in controlled['samples'] if r['mode'] == mode and not r.get('error') and not r.get('cancel')]
            output['controlled'][mode] = group(rows)
    soak = samples('2026-11-24-output-matrix.json')
    if soak:
        rows = soak['samples']
        output['soak'] = {'n':len(rows), 'elapsed_seconds':soak['elapsed_seconds'],
            'failures':sum(bool(r.get('error')) for r in rows),
            'cancels':sum(bool(r.get('cancel')) for r in rows),
            'late_starts':sum(r.get('late_starts',0) for r in rows),
            'cancel_settle_ms':stats([r.get('cancel_server_settle_ms') for r in rows if r.get('cancel')]),
            'peak_queue_bytes':max(r.get('peak_queued_bytes',0) for r in rows),
            'peak_decode_ahead_seconds':max(r.get('peak_decode_ahead_seconds',0) for r in rows),
            'renderer_max_tick_gap_ms':stats([r.get('renderer_max_tick_gap_ms') for r in rows]),
            'health_ping_ms':stats([p.get('ms') for r in rows for p in r.get('engine_health_pings',[])]),
            'underruns':sum(r.get('budget_after',{}).get('underruns',0)-r.get('budget_before',{}).get('underruns',0) for r in rows),
            'pending_after':stats([r.get('budget_after',{}).get('pending') for r in rows]),
            'observation_last':soak['snapshots'][-1]['observation'],
            'process_rss_first':soak['snapshots'][0]['processes'],
            'process_rss_last':soak['snapshots'][-1]['processes']}
        mismatches = []
        for index, row in enumerate(rows):
            path = ROOT / '.env-local/output-matrix' / f'{index:04d}-{row["role"]}-{row["mode"] if row["mode"] != "ordinary" else ""}.json'
            # 旧采样器未冻结角色；原始逐次文件保留当时 renderer 模型，按编号取证。
            candidates = list(path.parent.glob(f'{index:04d}-*.json'))
            if candidates:
                state = json.loads(candidates[0].read_text(encoding='utf-8')).get('state', {})
                actual = str(state.get('model', '')).lower()
                if row['role'] not in actual:
                    mismatches.append({'sample':index+1, 'requested_role':row['role'], 'renderer_model':state.get('model')})
        output['soak']['role_mismatches_excluded_from_role_conclusions'] = mismatches
    files = ['engine/yuiro/main.py','engine/yuiro/agent/__init__.py',
             'engine/yuiro/audio/bilingual.py','engine/yuiro/audio/fish.py',
             'engine/yuiro/audio/fish_websocket.py','engine/yuiro/audio/__init__.py',
             'shell/src/renderer/src/App.vue','shell/src/renderer/src/composables/useVoiceInput.ts']
    output['source_sha256'] = {name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in files}
    path = PLAN / '2026-11-24-output-summary.json'
    path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
