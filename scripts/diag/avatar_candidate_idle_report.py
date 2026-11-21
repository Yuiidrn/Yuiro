"""校验指定候选的双角色待机记录及文件指纹；不修改运行程序。"""
import argparse
import hashlib
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--soak', required=True)
    parser.add_argument('--manifest', required=True)
    parser.add_argument('--output', required=True)
    options = parser.parse_args()
    soak = json.loads(Path(options.soak).read_text(encoding='utf-8'))
    manifest = json.loads(Path(options.manifest).read_text(encoding='utf-8'))
    changed = [name for name, digest in manifest['files'].items()
               if not Path(name).is_file()
               or hashlib.sha256(Path(name).read_bytes()).hexdigest() != digest]
    assert not changed, changed
    assert soak.get('restored') == 'hotaru'
    assert {r['role'] for r in soak['results']} == {'hiyori', 'hotaru'}
    assert len(soak['results']) == 2
    rows = []
    for row in soak['results']:
        assert row['done'] and row['seconds'] >= soak['plannedSecondsPerRole']
        assert len(row['visibility']) >= soak['plannedSecondsPerRole'] - 10
        assert set(row['visibility']) == {'visible'}
        assert {s['presence'] for s in row['states']} == {'idle'}
        assert row['pixels'] and min(p['occupied'] for p in row['pixels']) > 0
        distinct_hashes = len({p['hash'] for p in row['pixels']})
        assert distinct_hashes > 1
        eyes = row['eyes']
        assert eyes and eyes['frames'] > 0 and eyes['min'] < .15 and eyes['max'] > .8
        motions = sorted({(s.get('motion', ''), s.get('motionIndex'))
                          for s in row['states']}, key=str)
        if row['role'] == 'hiyori':
            assert all(not name or (name == 'Idle' and index == 0) for name, index in motions)
        rows.append({'role': row['role'], 'seconds': row['seconds'],
                     'samples': len(row['states']), 'frameIntervalMs': row['frameIntervalMs'],
                     'eyes': eyes, 'motions': motions,
                     'minOccupied': min(p['occupied'] for p in row['pixels']),
                     'distinctAlphaHashes': distinct_hashes, 'allVisible': True, 'allIdle': True})
    result = {'scope': 'Bounded visible idle on specified candidate; not entire goal completion',
              'results': rows, 'manifestFiles': len(manifest['files']), 'changedFiles': changed,
              'restored': soak['restored'], 'limitations': [
                  'rAF intervals are not GPU frame time or speech latency',
                  'Eye closure transitions include motion ownership, not exact automatic blink counts',
                  'No human naturalness, acoustic latency or multi-hour mixed voice stress proof']}
    Path(options.output).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
