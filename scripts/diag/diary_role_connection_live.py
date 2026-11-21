"""日记正常连接与正式角色切换冒烟；不读正文、不输入/保存/朗读，不覆盖已有草稿。"""
import asyncio
import json
import re
from pathlib import Path

from appearance_thumbnails_live import connect, pages


async def main():
    bundle = re.search(r'src="([^"]*diary-[^"]+\.js)"', Path('shell/out/renderer/diary.html').read_text(encoding='utf-8')).group(1).split('/')[-1]
    original = next((p for p in pages() if 'diary.html' in p['url']), None)
    pet = next(p for p in pages() if 'index.html' in p['url'])
    dev = next(p for p in pages() if 'dev.html' in p['url'])
    report = {'scope':'actual built diary connection and formal role changes, no text/audio/LLM or microphone; controlled async races covered separately by production-function tests',
              'preExistingWindow':original is not None, 'expectedBundle':bundle, 'rows':[]}
    if original is None:
        await connect(pet, lambda c,e:e('window.yuiro.openDiary()'))
        await asyncio.sleep(2)
    diary = next(p for p in pages() if 'diary.html' in p['url'])

    async def state():
        return await connect(diary, lambda c,e:e("({role:localStorage.getItem('yuiro-active-character'),connected:!!document.querySelector('.connection.ok'),draftPresent:[...document.querySelectorAll('.journal-textarea')].some(x=>x.value.length>0)||!!document.querySelector('.draft-segments p'),latestBundle:[...document.scripts].some(s=>s.src.endsWith("+json.dumps(bundle)+"))})"))

    async def select(role):
        await connect(dev, lambda c,e:e("(()=>{const s=document.querySelector('.character-picker select');s.value="+json.dumps(role)+";s.dispatchEvent(new Event('change',{bubbles:true}))})()"))
        for _ in range(120):
            row = await state()
            if row['role']==role and row['connected']:
                await asyncio.sleep(.5)
                return await state()
            await asyncio.sleep(.25)
        raise RuntimeError('Diary reconnect timeout')

    initial = await state()
    report['initial'] = initial
    assert initial['role']=='hotaru', initial
    try:
        if initial['draftPresent'] or original is not None:
            report['switchSkipped'] = 'Preserved existing window or draft; no reload or role change for this smoke'
        else:
            report['rows'].append(await select('hiyori'))
            report['rows'].append(await select('hotaru'))
            assert all(row['connected'] and row['latestBundle'] for row in report['rows'])
    finally:
        if report['rows']:
            report['restored'] = await select('hotaru')
        if original is None:
            await connect(diary, lambda c,e:c('Page.close'))
        Path('docs/plan/diary-role-connection-live.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False))


if __name__ == '__main__':
    asyncio.run(main())
