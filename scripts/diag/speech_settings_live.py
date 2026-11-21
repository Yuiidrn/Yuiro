"""实际调试台store保存→桌宠菜单镜像；恢复原开关，不开麦/不请求模型。"""
import asyncio
import json
from pathlib import Path

from appearance_thumbnails_live import connect, pages


async def main():
    pet = next(p for p in pages() if 'index.html' in p['url'])
    dev = next(p for p in pages() if 'dev.html' in p['url'])
    store = "document.querySelector('#app').__vue_app__.config.globalProperties.$pinia._s.get('devConfig')"

    async def check_dev(call,evaluate):
        assert not await evaluate(store+'.hasDraftChanges'), 'Preserve existing unsaved settings'
        await call('Page.reload')
    await connect(dev,check_dev)
    async def reload_pet(call,evaluate):
        assert not await evaluate("!!document.querySelector('.mic-btn.recording')")
        await call('Page.reload')
    await connect(pet,reload_pet)
    await asyncio.sleep(3)
    async def prepare(call,evaluate):
        await evaluate('window.__speechConfigStore='+store)
        await evaluate('__speechConfigStore.load()')
        assert not await evaluate('__speechConfigStore.hasDraftChanges')
        await evaluate('window.__speechConfigBefore=JSON.stringify(__speechConfigStore.sections)')
        return await evaluate('({role:__speechConfigStore.character.active_id,revision:__speechConfigStore.character.revision,barge:__speechConfigStore.sections.vad.barge_in_enabled,tts:__speechConfigStore.sections.tts.reply_tts_enabled})')
    original = await connect(dev,prepare)
    async def menu(call,evaluate):
        await evaluate("""window.__settingsPageToken=crypto.randomUUID();window.__hadSpeechMenu=!!document.querySelector('.dock-menu-panel');
          window.__hadSettingsChat=!!document.querySelector('.chat-dock');
          window.__settingsToggleChat=()=>{const seen=new Set();function find(v){
            if(!v||typeof v!=='object'||seen.has(v))return;seen.add(v);
            if(v.component?.type.__name==='BracketMenu')return v.component;
            return find(v.component?.subTree)||(Array.isArray(v.children)?v.children.map(find).find(Boolean):null)}
            const c=find(document.querySelector('#app')._vnode);if(!c)throw Error('Missing bracket component');c.emit('action','chat')};
          if(!__hadSettingsChat)__settingsToggleChat()""")
        await asyncio.sleep(.3)
        await evaluate("if(!document.querySelector('.dock-menu-panel'))document.querySelector('[title=\"打断 / 语音回复开关（点击展开）\"]').click()")
        return await evaluate('__settingsPageToken')
    token = await connect(pet,menu)
    rows = []
    async def apply(section,key,value):
        async def patch(call,evaluate):
            assert await evaluate('__speechConfigStore.character.active_id==='+json.dumps(original['role']))
            await evaluate('__speechConfigStore.applySection('+json.dumps(section)+','+json.dumps({key:value})+')')
        await connect(dev,patch)
    async def read(label):
        return await connect(pet,lambda c,e:e("[...document.querySelectorAll('.dock-menu-item')].find(x=>x.querySelector('.dmi-label')?.textContent.trim()==="+json.dumps(label)+")?.querySelector('.dmi-state')?.textContent.trim()"))
    async def read_dev(section,key):
        return await connect(dev,lambda c,e:e('__speechConfigStore.sections['+json.dumps(section)+']['+json.dumps(key)+']'))
    async def quick(label):
        await connect(pet,lambda c,e:e("[...document.querySelectorAll('.dock-menu-item')].find(x=>x.querySelector('.dmi-label')?.textContent.trim()==="+json.dumps(label)+").click()"))
    report = {'scope':'current built dev store/API save and cross-window pet menu; no microphone, LLM or synthesis; no refresh/reconnect during setting changes', 'original':original,'rows':rows}
    try:
        for section,key,label,old in [('vad','barge_in_enabled','插话打断',original['barge']),('tts','reply_tts_enabled','语音回复 TTS',original['tts'])]:
            for value in [not old,old]:
                await apply(section,key,value)
                expected = '开' if value else '关'
                for _ in range(80):
                    observed = await read(label)
                    if observed == expected:break
                    await asyncio.sleep(.05)
                row = {'section':section,'value':value,'observed':observed,'passed':observed==expected}
                rows.append(row)
                assert row['passed'], row
        for section,key,label,old in [('vad','barge_in_enabled','插话打断',original['barge']),('tts','reply_tts_enabled','语音回复 TTS',original['tts'])]:
            for value in [not old,old]:
                await quick(label)
                for _ in range(80):
                    observed = await read_dev(section,key)
                    if observed == value:break
                    await asyncio.sleep(.05)
                row = {'direction':'pet-to-dev','section':section,'value':value,'observed':observed,'passed':observed==value}
                rows.append(row)
                assert row['passed'], row
        await connect(dev,lambda c,e:e('__speechConfigStore.hasDraftChanges=true'))
        await quick('插话打断')
        for _ in range(80):
            if await read('插话打断') == ('关' if original['barge'] else '开'):break
            await asyncio.sleep(.05)
        await asyncio.sleep(.3)
        report['dirtyDraftPreserved'] = await read_dev('vad','barge_in_enabled') == original['barge']
        assert report['dirtyDraftPreserved']
        await connect(dev,lambda c,e:e('__speechConfigStore.hasDraftChanges=false;__speechConfigStore.load()'))
        await quick('插话打断')
        for _ in range(80):
            if await read_dev('vad','barge_in_enabled') == original['barge']:break
            await asyncio.sleep(.05)
    finally:
        await connect(dev,lambda c,e:e('__speechConfigStore.hasDraftChanges=false'))
        await apply('vad','barge_in_enabled',original['barge'])
        await apply('tts','reply_tts_enabled',original['tts'])
        async def finish_dev(call,evaluate):
            result = await evaluate('JSON.stringify(__speechConfigStore.sections)===__speechConfigBefore')
            await evaluate('delete window.__speechConfigStore;delete window.__speechConfigBefore')
            return result
        report['configRestored'] = await connect(dev,finish_dev)
        async def finish_pet(call,evaluate):
            result = await evaluate('({sameDocument:__settingsPageToken==='+json.dumps(token)+",mic:!!document.querySelector('.mic-btn.recording'),role:localStorage.getItem('yuiro-active-character')})")
            await evaluate("if(!__hadSpeechMenu)document.querySelector('[title=\"打断 / 语音回复开关（点击展开）\"]').click();if(!__hadSettingsChat)__settingsToggleChat();delete window.__settingsToggleChat;delete window.__hadSettingsChat;delete window.__settingsPageToken;delete window.__hadSpeechMenu")
            return result
        report['final'] = await connect(pet,finish_pet)
        Path('docs/plan/speech-settings-live.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False))


if __name__ == '__main__':
    asyncio.run(main())
