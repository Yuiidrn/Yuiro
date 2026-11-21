"""只读核对 CLI/引擎授权与同一原版取流；不保存账号标识、令牌、签名地址。"""
import asyncio
from datetime import datetime, timezone
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'engine'))
from yuiro.netease import api, run_ncm
from yuiro.netease.availability import song_availability


async def main():
    report = {'read_only': True, 'base_url': api.BASE_URL,
              'parameters': {'trialScene': 'cli', 'withUrl': True, 'bitrate': 128,
                             'search_qualityFlag': False}}
    profile = (await api.call_api('/openapi/music/basic/user/profile/get/v2', {})).get('data') or {}
    now_ms = datetime.now(timezone.utc).timestamp()*1000
    valid = [x for x in profile.get('vipDetail', []) if isinstance(x, dict)
             and isinstance(x.get('expireTime'), (int, float)) and x['expireTime'] > now_ms]
    report['account'] = {'profile_read': True, 'unexpired_membership_records': len(valid),
                         'uses_cli_device': bool(api._ncm_device)}
    paths = api._ncm_cli_paths()
    if paths:
        proc = await asyncio.create_subprocess_exec(*paths, 'config', 'get', 'appId',
                                                    stdout=asyncio.subprocess.PIPE,
                                                    stderr=asyncio.subprocess.PIPE)
        out, _ = await asyncio.wait_for(proc.communicate(), 15)
        match = re.search(r'appId:\s*([A-Za-z0-9_-]+)', out.decode('utf-8', 'replace'))
        report['engine_appid_matches_cli'] = bool(match and match.group(1) == api._app_id())
        proc = await asyncio.create_subprocess_exec(*paths, 'song', 'detail', '--help',
                                                    stdout=asyncio.subprocess.PIPE,
                                                    stderr=asyncio.subprocess.PIPE)
        out, err = await asyncio.wait_for(proc.communicate(), 15)
        report['cli_detail_help'] = [line.strip() for line in (out+err).decode('utf-8', 'replace').splitlines()
                                     if any(k in line.lower() for k in ['bitrate', '码率', 'songid', 'withurl'])]
    cli = await run_ncm(['search', 'song', '--keyword', 'Monody TheFatRat', '--limit', '5',
                         '--userInput', '核对同一账号 Monody 原版当前通道权限'], timeout_s=30)
    report['cli_search'] = {'ok': cli.ok, 'original_playFlag': next(
        (r.get('playFlag') for r in cli.records if str(r.get('originalId')) == '36308916'), None)}
    report['songs'] = []
    for encrypted, label in [('50823456D9AD17D80AE1CCD5E33621C8', 'Monody original'),
                              ('784AC11602D9D320154D1DBBCA25ACB7', 'Monody remix')]:
        detail = await api.song_detail(encrypted)
        report['songs'].append({'label': label, 'song_id': detail.get('originalId'),
                                'has_play_url': bool(detail.get('playUrl')),
                                'bitrate_returned': detail.get('br'),
                                **song_availability(detail, detail=True)})
    target = ROOT / 'docs/plan/netease-client-artifacts/api-audit.json'
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    asyncio.run(main())
