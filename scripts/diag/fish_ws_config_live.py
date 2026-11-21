"""当前Hotaru真实配置入口/静音合成自检，finally恢复原传输设置。"""
import asyncio
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path('engine').resolve()))
from appearance_thumbnails_live import connect, pages
from yuiro.characters import CharacterStore


async def main():
    store = CharacterStore(Path('engine/config.toml'))
    hiyori = store.root / 'hiyori.toml'
    before = hashlib.sha256(hiyori.read_bytes()).hexdigest()
    pet = next(p for p in pages() if 'index.html' in p['url'])

    async def run(call, evaluate):
        state = await evaluate("({role:localStorage.getItem('yuiro-active-character'),mic:!!document.querySelector('.mic-btn.recording'),presence:JSON.parse(localStorage.getItem('yuiro-avatar-status')||'{}').presence})")
        assert state == {'role': 'hotaru', 'mic': False, 'presence': 'idle'}, state
        return await evaluate("""(async()=>{
          const headers={'Content-Type':'application/json','x-yuiro-secret':await window.yuiro.getEngineSecret()};
          const read=async()=>{const r=await fetch('http://127.0.0.1:8200/api/config',{headers});
            if(!r.ok)throw Error('Config read');return r.json()};
          const original=await read();if(original.character.active_id!=='hotaru')throw Error('Wrong active role');
          const initial=original.sections.tts.fish_transport;
          const write=async transport=>{const cfg=await read();if(cfg.character.active_id!=='hotaru')throw Error('Role changed');
            return fetch('http://127.0.0.1:8200/api/config',{method:'PUT',headers,
              body:JSON.stringify({character_id:'hotaru',character_revision:cfg.character.revision,
                patch:{tts:{fish_transport:transport}}})})};
          let result={initialTransport:initial};
          try{
            result.invalidTransportStatus=(await write('invalid-fixture')).status;
            if(result.invalidTransportStatus!==400)throw Error('Invalid transport accepted');
            const changed=await write('websocket');if(!changed.ok)throw Error('Config update failed');
            const cfg=await read();if(cfg.sections.tts.fish_transport!=='websocket')throw Error('Transport not stored');
            const test=await fetch('http://127.0.0.1:8200/api/providers/tts/test',{
              method:'POST',headers,body:JSON.stringify({lang:'ja'})});
            const data=await test.json();result.test={httpStatus:test.status,status:data.status,
              transport:data.transport,latencyWholeClipMs:data.latency_ms,wavBytes:data.wav_bytes,
              sampleRate:data.sample_rate,hasAudio:!!data.audio_base64};
            result.passed=data.status==='ok'&&data.transport==='websocket'&&data.wav_bytes>44;
          }finally{
            const restored=await write(initial);if(!restored.ok)throw Error('Config restore failed');
            const final=await read();result.restoredTransport=final.sections.tts.fish_transport;
            result.completeSectionsRestored=JSON.stringify(original.sections)===JSON.stringify(final.sections);
          }return result})()""")

    result = await connect(pet, run)
    result['hiyoriFileUnchanged'] = before == hashlib.sha256(hiyori.read_bytes()).hexdigest()
    Path('docs/plan/fish-ws-config-live.json').write_text(json.dumps({
        'scope': 'Actual authenticated config validation/hot-reload/test endpoint with single paid synthesis; no playback/microphone; transport restored, no audio/config contents saved in report',
        **result}, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result))
    assert result['passed'] and result['completeSectionsRestored'] and result['hiyoriFileUnchanged']


if __name__ == '__main__':
    asyncio.run(main())
