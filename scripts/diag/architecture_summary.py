"""从保留的JSON证据计算统计，不访问模型或用户数据。"""
import hashlib
import json
import math
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PLAN = ROOT / 'docs/plan'


def stats(values):
    values = sorted(values)
    if not values:
        return {'n': 0}
    return {'n': len(values), 'p50_ms': round(values[math.ceil(len(values)*.5)-1], 2),
            'p95_ms': round(values[math.ceil(len(values)*.95)-1], 2),
            'max_ms': round(max(values), 2)}


def main():
    report = {}
    for label, name in [('before_long', 'architecture-live-before.json'),
                        ('after_long', 'architecture-live-after.json'),
                        ('hot_candidate', 'architecture-live-hot-final.json'),
                        ('hot_final', 'architecture-live-accepted.json')]:
        source = PLAN / name
        if not source.exists():
            continue
        data = json.loads(source.read_text(encoding='utf-8'))
        rows = data['samples']
        record = {'evidence': name, 'attempts': len(rows),
                  'failures': sum(bool(r.get('error')) for r in rows)}
        if label.startswith('hot_'):
            record['warmup'] = rows[0]
            rows = rows[1:]
        record['first_play'] = stats([r['first_start_ms'] for r in rows
                                      if not r.get('error') and 'first_start_ms' in r])
        record['rows'] = [{k: r.get(k) for k in ('sample', 'first_start_ms', 'reply_ms',
                                                'first_receive_ms', 'error', 'trace_id')}
                          for r in rows]
        record['engine_stages'] = {key: stats([r['stages_ms'][key] for r in rows
                                              if key in r.get('stages_ms', {})])
                                   for key in ('memory_retrieve', 'llm_first_token', 'first_sentence',
                                               'translation_start', 'lang_render', 'tts_first_audio',
                                               'audio_sent')}
        record['decode_after_receive'] = stats([r['decode_end_ms']-r['first_receive_ms']
                                                for r in rows if 'decode_end_ms' in r])
        record['engine_durations'] = {
            label: stats([r['stages_ms'][end]-r['stages_ms'][begin] for r in rows
                          if end in r.get('stages_ms', {}) and begin in r['stages_ms']])
            for label, begin, end in [
                ('memory', 'memory_retrieve_start', 'memory_retrieve'),
                ('llm_to_first_token', 'llm_request_start', 'llm_first_token'),
                ('first_sentence_prepare', 'llm_first_token', 'first_sentence'),
                ('translation', 'translation_start', 'lang_render'),
                ('tts_first_block_after_translation', 'lang_render', 'tts_first_audio'),
                ('send_first_audio', 'tts_first_audio', 'audio_sent')]}
        report[label] = record
    probe = json.loads((PLAN / 'architecture-consolidation-probe.json').read_text(encoding='utf-8'))
    report['controlled_medians'] = {
        label: round(statistics.median(row[label][key] for row in probe['samples']), 2)
        for label, key in [('speech_before', 'first_audio_callback_ms'),
                           ('speech_after', 'first_audio_callback_ms'),
                           ('observer_before', 'publish_ms'), ('observer_after', 'publish_ms'),
                           ('disk_before', 'loop_tick_ms'), ('disk_after', 'loop_tick_ms')]}
    paths = ['engine/yuiro/main.py', 'engine/yuiro/audio/output.py',
             'engine/yuiro/runtime/observation.py', 'engine/yuiro/runtime/event_log.py',
             'shell/src/renderer/src/App.vue',
             'shell/src/renderer/src/composables/useVoiceInput.ts',
             'shell/src/shared/playback-admission.ts', 'shell/src/shared/engine-protocol.ts',
             'engine/config.toml']
    report['current_file_sha256'] = {path: hashlib.sha256((ROOT/path).read_bytes()).hexdigest()
                                     for path in paths if (ROOT/path).exists()}
    (PLAN / 'architecture-consolidation-summary.json').write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k: ({'first_play': v.get('first_play'), 'attempts': v.get('attempts'),
                          'failures': v.get('failures')} if isinstance(v, dict) and 'first_play' in v
                          else v) for k, v in report.items() if k != 'current_file_sha256'}))


if __name__ == '__main__':
    main()
