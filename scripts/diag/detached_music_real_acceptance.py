"""Strict real acceptance: no fixtures, no intercepted playback, no account/URL dumps.

Requires an already authorized ncm-cli account, live Engine/Shell and CDP 9222.
Windows input is real; run serially without moving the mouse or locking the desktop.
"""
import asyncio
import ctypes as c
from ctypes import wintypes as w
import json
import sys
import time

from c0_live_acceptance import DEV, PET, ROOT, Page, pages
from c0_live_scenarios import switch

sys.path.insert(0, str(ROOT / 'engine'))
from yuiro.netease import player
from yuiro.tools.netease_tool import NeteaseSearchTool

OUT = ROOT / 'docs/plan/detached-ui-artifacts/music-real.json'
SEARCH_TERMS = ('Monody TheFatRat', 'Hope Tobu', 'Spectre Alan Walker', 'Sky High Elektronomia')


async def main():
    user = c.windll.user32
    user.SetThreadDpiAwarenessContext(c.c_void_p(-4))
    user.FindWindowW.restype = w.HWND
    cursor = w.POINT()
    user.GetCursorPos(c.byref(cursor))
    report = {'kind': 'real Agent search -> native detached card -> Engine media:play -> mpv progress -> chat stop', 'fixture': False, 'roles': []}

    def save():
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')

    def bounds(title):
        hwnd = user.FindWindowW(None, title)
        rect = w.RECT()
        assert hwnd and user.GetWindowRect(hwnd, c.byref(rect)), title
        return {'x': rect.left, 'y': rect.top, 'width': rect.right-rect.left, 'height': rect.bottom-rect.top}

    async def sample_player():
        return await asyncio.wait_for(player.get_state(), 8)

    preflight = json.loads(await asyncio.wait_for(NeteaseSearchTool().run({'keyword': 'LIFE', 'limit': 3}, 'music-real-preflight'), 35))
    report['preflight'] = {'status': preflight.get('status'), 'count': preflight.get('count')}
    assert preflight.get('status') == 'ok' and preflight.get('count', 0) > 0, report['preflight']
    report['player_baseline'] = await sample_player()
    assert report['player_baseline']['status'] == 'stopped', 'mpv already playing; do not replace unrelated music'
    save()
    info = await pages()
    started_playback = False
    async with Page(next(p for p in info if p['title'] == 'Yuiro')) as pet, Page(next(p for p in info if 'dev.html' in p['url'])) as dev:
        for _ in range(60):
            ready = await dev.evaluate('(()=>{' + DEV + 'return !!s?.character?.active_id&&!s.loading;})()')
            if ready:
                break
            await asyncio.sleep(.2)
        original_role = await dev.evaluate('(()=>{' + DEV + 'return s.character.active_id;})()')
        fade = await dev.evaluate("localStorage.getItem('yuiro-fade-on-hover-enabled')")
        original_bounds = bounds('Yuiro')
        layout = await pet.evaluate('window.yuiro.getPetLayout()')
        terms = iter(SEARCH_TERMS)

        async def position(page, title, point):
            b = bounds(title)
            view = await page.evaluate('({width:innerWidth,height:innerHeight})')
            return (round(b['x'] + point['x']*b['width']/view['width']), round(b['y'] + point['y']*b['height']/view['height']))

        async def search():
            # Isolate each acceptance case using the supported character switch lifecycle.
            # Same-session re-search refusing tool calls is retained as a separate regression.
            await pet.evaluate('window.__restoreRealMusic?.()')
            active = await pet.evaluate('(()=>{' + PET + 'return app.activeCharacter;})()')
            await switch(pet, dev, 'hotaru' if active == 'hiyori' else 'hiyori')
            await switch(pet, dev, active)
            await pet.evaluate('(()=>{' + PET + "const ws=app.socket,send=ws.send;window.__realMusic={sent:[],types:[],assistant:[]};const onMessage=e=>{const m=JSON.parse(e.data);__realMusic.types.push(m.type);if(m.type==='chat:assistant')__realMusic.assistant.push(String(m.text||'').slice(0,300));};ws.addEventListener('message',onMessage);ws.send=function(data){const m=JSON.parse(data);if(m.type==='media:play')__realMusic.sent.push(m);return send.call(this,data)};window.__restoreRealMusic=()=>{ws.send=send;ws.removeEventListener('message',onMessage)};return true;})()")
            term = next(terms)
            query = f'请重新调用 netease_search 搜索 {term}，给我最新可点击的歌曲候选结果卡。这轮只搜索让我选择，不要自动播放，也不要复述旧候选。'
            await pet.evaluate('(()=>{' + PET + 'app.clearResultCard();app.closeMenu();app.sendText(' + json.dumps(query) + ');return true;})()')
            started = time.monotonic()
            while time.monotonic()-started < 90:
                card = await pet.evaluate('(()=>{' + PET + "return app.resultCard&&app.resultCard.kind!=='source'?JSON.parse(JSON.stringify(app.resultCard)):null;})()")
                if card:
                    card['acceptance_search_term'] = term
                    return card, round(time.monotonic()-started, 3)
                await asyncio.sleep(.25)
            raise RuntimeError('Real Agent search did not return a music card within 90 seconds')

        try:
            await dev.evaluate("localStorage.setItem('yuiro-fade-on-hover-enabled','false')")
            for role in ['hiyori', 'hotaru']:
                await switch(pet, dev, role)
                row = {'role': role, 'status': 'running'}
                report['roles'].append(row)
                save()
                card, elapsed = await search()
                row['search_seconds'] = elapsed
                row['search_term'] = card['acceptance_search_term']
                row['candidates'] = card['items']
                save()
                print(json.dumps({'role': role, 'phase': 'real_search', 'count': len(card['items']), 'seconds': elapsed}, ensure_ascii=False), flush=True)
                await asyncio.sleep(.35)
                ui_info = next(p for p in await pages() if 'kind=results' in p['url'])
                async with Page(ui_info) as ui:
                    for _ in range(80):
                        rendered = await ui.evaluate("document.title==='Yuiro 结果'&&document.querySelectorAll('.rc-item').length>0")
                        hwnd = user.FindWindowW(None, 'Yuiro 结果')
                        if rendered and hwnd and user.IsWindowVisible(hwnd):
                            break
                        await asyncio.sleep(.1)
                    assert rendered and hwnd and user.IsWindowVisible(hwnd), 'detached result renderer never became visible/ready'
                    row['before_drag'] = {'pet': bounds('Yuiro'), 'results': bounds('Yuiro 结果')}
                    point = await pet.evaluate('(()=>{' + PET + "app.closeMenu();const m=v.contour,r=v.modelRect;let p=null,best=Infinity;for(let j=0;j<m.height;j++)for(let i=0;i<m.width;i++){const x=m.left+(i+.5)*m.cssWidth/m.width,y=m.top+(j+.5)*m.cssHeight/m.height;if(m.alpha[j*m.width+i]>240&&x>20&&y>20&&x<innerWidth-20&&y<innerHeight-20&&!document.elementsFromPoint(x,y).some(e=>e.closest('button,input,.bm-icon,.panel'))){const d=Math.hypot(x-r.left-r.width/2,y-r.top-r.height*.7);if(d<best){best=d;p={x,y}}}}return p;})()")
                    assert point, 'opaque drag point unavailable'
                    start = await position(pet, 'Yuiro', point)
                    assert user.SetCursorPos(*start), 'Windows input desktop unavailable'
                    await asyncio.sleep(.04)
                    user.mouse_event(2, 0, 0, 0, 0)
                    for step in range(1, 9):
                        user.SetCursorPos(start[0]+step*12, start[1]+step*5)
                        await asyncio.sleep(.04)
                    user.mouse_event(4, 0, 0, 0, 0)
                    await asyncio.sleep(.3)
                    row['after_drag'] = {'pet': bounds('Yuiro'), 'results': bounds('Yuiro 结果')}
                    dx = row['after_drag']['pet']['x']-row['before_drag']['pet']['x']
                    assert abs(dx) > 40, 'native model drag failed'
                    row['follow_delta_x'] = row['after_drag']['results']['x']-row['before_drag']['results']['x']
                    row['follow_delta_y'] = row['after_drag']['results']['y']-row['before_drag']['results']['y']
                    dy = row['after_drag']['pet']['y']-row['before_drag']['pet']['y']
                    assert abs(row['follow_delta_x']-dx) <= 6 and abs(row['follow_delta_y']-dy) <= 6, 'card did not follow drag (place model away from edge for this strict case)'
                    # Layout can legitimately change side near an edge; also verify a live card remains clickable.
                    chosen_index = next(i for i, it in enumerate(card['items']) if it.get('playable') is not False and (it.get('song_id') or it.get('encrypted_id')))
                    chosen = card['items'][chosen_index]
                    point = await ui.evaluate("(()=>{const e=document.querySelectorAll('.rc-item')[" + str(chosen_index) + "];e.scrollIntoView({block:'nearest'});const r=e.getBoundingClientRect();return {x:r.x+20,y:r.y+r.height/2};})()")
                    target = await position(ui, 'Yuiro 结果', point)
                    assert user.IsWindowVisible(user.FindWindowW(None, 'Yuiro 结果'))
                    assert user.SetCursorPos(*target)
                    await asyncio.sleep(.1)
                    click_time = time.monotonic()
                    user.mouse_event(2, 0, 0, 0, 0)
                    user.mouse_event(4, 0, 0, 0, 0)
                    started_playback = True
                    await asyncio.sleep(.3)
                    row['sent'] = await pet.evaluate('window.__realMusic.sent')
                    assert row['sent'], 'native song click did not reach Engine socket'
                    sent = row['sent'][0]
                    assert str(sent.get('song_id')) == str(chosen.get('song_id')) and sent.get('encrypted_id') == chosen.get('encrypted_id'), 'selected song ID changed'
                    row['selected'] = chosen
                    row['card_cleared'] = await pet.evaluate('(()=>{' + PET + 'return app.resultCard===null;})()')
                    assert row['card_cleared']
                    playing = None
                    while time.monotonic()-click_time < 45:
                        state = await sample_player()
                        if state['status'] == 'playing' and state.get('ready') and state.get('position', 0) > .2:
                            playing = state
                            break
                        await asyncio.sleep(.4)
                    assert playing, 'mpv never became ready/playing with advancing time'
                    row['click_to_play_seconds'] = round(time.monotonic()-click_time, 3)
                    row['playing'] = playing
                    await asyncio.sleep(3)
                    row['playing_later'] = await sample_player()
                    assert row['playing_later']['position'] > playing['position'], 'audio timeline not advancing'
                    print(json.dumps({'role': role, 'phase': 'playing', 'title': playing['title'], 'progress': row['playing_later']['position'], 'seconds': row['click_to_play_seconds']}, ensure_ascii=False), flush=True)
                    stop_time = time.monotonic()
                    await pet.evaluate('(()=>{' + PET + "app.sendText('停止播放音乐');return true;})()")
                    while time.monotonic()-stop_time < 30:
                        stopped = await sample_player()
                        if stopped['status'] == 'stopped':
                            break
                        await asyncio.sleep(.3)
                    assert stopped['status'] == 'stopped', 'chat stop did not stop the actual player'
                    row['stop_seconds'] = round(time.monotonic()-stop_time, 3)
                    row['stopped'] = stopped
                    started_playback = False
                    # A second real result must be cleared when leaving the character.
                    second, second_time = await search()
                    row['second_search_seconds'] = second_time
                    row['second_search_term'] = second['acceptance_search_term']
                    row['second_result_count'] = len(second['items'])
                    key = await pet.evaluate('(()=>{' + PET + 'return app.detachedSnapshot().key;})()')
                    await pet.evaluate('window.__restoreRealMusic?.()')
                    target_role = 'hotaru' if role == 'hiyori' else 'hiyori'
                    await switch(pet, dev, target_role)
                    await asyncio.sleep(.35)
                    await pet.evaluate('window.__staleMusicActions=0;window.__staleMusicOff=window.yuiro.onDetachedAction(()=>__staleMusicActions++)')
                    await ui.evaluate('window.yuiro.detachedAction({kind:"results",key:' + json.dumps(key) + ',index:0})')
                    await asyncio.sleep(.15)
                    row['switch_cleanup'] = await pet.evaluate('(()=>{' + PET + 'return {role:app.activeCharacter,card_cleared:app.resultCard===null,speech_hidden:!app.speechVisible,stale_forwarded:window.__staleMusicActions};})()')
                    await pet.evaluate('window.__staleMusicOff()')
                    row['switch_cleanup']['result_window_hidden'] = not bool(user.IsWindowVisible(user.FindWindowW(None, 'Yuiro 结果')))
                    assert row['switch_cleanup']['card_cleared'] and row['switch_cleanup']['result_window_hidden'] and row['switch_cleanup']['stale_forwarded'] == 0
                    row['after_switch_player'] = await sample_player()
                    assert row['after_switch_player']['status'] == 'stopped', 'old card reactivated playback'
                    row['status'] = 'passed'
                    save()
                    print(json.dumps({'role': role, 'status': 'passed', 'stop_seconds': row['stop_seconds'], 'switch_cleanup': row['switch_cleanup']}, ensure_ascii=False), flush=True)
        except Exception as exc:
            report['error'] = {'type': type(exc).__name__, 'message': str(exc)[:400]}
            save()
            raise
        finally:
            await pet.evaluate('(()=>{' + PET + 'window.__restoreRealMusic?.();app.clearResultCard();app.hideSpeech();return true;})()')
            if started_playback and player.pipe_alive():
                await player.control('stop')  # this test's mpv only; never fall through to SMTC
            await switch(pet, dev, original_role)
            await dev.evaluate('localStorage.' + ('removeItem("yuiro-fade-on-hover-enabled")' if fade is None else 'setItem("yuiro-fade-on-hover-enabled",' + json.dumps(fade) + ')'))
            await pet.evaluate('window.yuiro.setPetLayout(' + json.dumps(layout) + ',false)')
            user.SetWindowPos(user.FindWindowW(None, 'Yuiro'), 0, original_bounds['x'], original_bounds['y'], 0, 0, 0x15)
            user.SetCursorPos(cursor.x, cursor.y)


if __name__ == '__main__':
    asyncio.run(main())
