"""双角色真实客户端收藏/日推验收；无平台 API，无合成搜索数据。"""
import asyncio,json,sys,time
from c0_live_acceptance import ROOT,PET,DEV,Page,pages
from c0_live_scenarios import switch
from ui_customization_acceptance import until
sys.path.insert(0,str(ROOT/'engine'))
from yuiro.native import netease_client as native
OUT=ROOT/'docs/plan/manga-skins-artifacts'

async def main():
    report={'kind':'natural speech without tool names or IDs + real Agent/client + result synchronization','roles':[]}
    OUT.mkdir(exist_ok=True)
    def save(): (OUT/'natural-music.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    async with Page(next(p for p in await pages() if p['title']=='Yuiro')) as pet,Page(next(p for p in await pages() if 'dev.html' in p['url'])) as dev:
        original=await dev.evaluate('(()=>{'+DEV+'return s.character.active_id;})()')
        baseline=None
        try:
            for role in ['hiyori','hotaru']:
                await switch(pet,dev,role)
                await pet.evaluate('(()=>{'+PET+'app.clearResultCard();app.sendText("帮我找一下 TheFatRat 和 Laura Brehm 的 Monody 原版，我来选。");;return true;})()')
                await until(pet,'(()=>{'+PET+'return app.resultCard?.items?.some(x=>x.song_id==="36308916");})()',35)
                cardinfo=None
                for _ in range(80):
                    cardinfo=next((p for p in await pages() if p['title']=='Yuiro 结果'),None)
                    if cardinfo:break
                    await asyncio.sleep(.1)
                async with Page(cardinfo) as card:
                    await until(card,'[...document.querySelectorAll(".rc-item")].some(e=>e.textContent.includes("Monody"))')
                    index=await pet.evaluate('(()=>{'+PET+'return app.resultCard.items.findIndex(x=>x.song_id==="36308916");})()')
                    await card.evaluate('document.querySelectorAll(".rc-item")['+str(index)+'].querySelector(".rc-client").click()')
                    await until(pet,'(()=>{'+PET+'return app.officialPlayback?.song_id==="36308916"&&app.officialPlayback.status==="playing"&&!app.officialPending;})()',35)
                    await card.evaluate('document.querySelector(".rc-control").click()')
                    await until(pet,'(()=>{'+PET+'return app.officialPlayback?.status==="paused"&&!app.officialPending;})()',20)
                    current=await native.favorite('36308916')
                    if baseline is None:baseline=current['liked']
                    assert current['liked']==baseline
                    row={'role':role,'song_id':current['song_id'],'original_liked':baseline,'playing_then_paused':True};report['roles'].append(row);save()
                    await until(card,'!!document.querySelector(".rc-favorite")&&!document.querySelector(".rc-favorite").disabled')
                    query='取消喜欢' if baseline else '喜欢这首'
                    row['write_utterance']=query
                    start=time.monotonic();await pet.evaluate('(()=>{'+PET+'app.sendText('+json.dumps(query,ensure_ascii=False)+');return true;})()')
                    await until(pet,'(()=>{'+PET+'return app.officialPlayback?.liked==='+json.dumps(not baseline)+'&&!app.officialPending;})()',80)
                    assert (await native.favorite('36308916'))['liked']==(not baseline)
                    row['natural_write_and_card_sync_seconds']=round(time.monotonic()-start,2);save()
                    await until(pet,'(()=>{'+PET+'return !app.turnBusy;})()',60)
                    query='喜欢这首' if baseline else '取消喜欢'
                    row['restore_utterance']=query
                    start=time.monotonic();await pet.evaluate('(()=>{'+PET+'app.sendText('+json.dumps(query,ensure_ascii=False)+');return true;})()')
                    async def restored():
                        for _ in range(160):
                            if (await native.favorite('36308916'))['liked']==baseline:return
                            await asyncio.sleep(.5)
                        raise RuntimeError('Agent did not restore favorite')
                    await restored();row['agent_restore_seconds']=round(time.monotonic()-start,2);row['favorite_restored']=True
                    await until(pet,'(()=>{'+PET+'return app.officialPlayback?.liked==='+json.dumps(baseline)+'&&!app.officialPending;})()',15)
                    row['card_restore_synchronized']=True;save()
                    await until(pet,'(()=>{'+PET+'return !app.turnBusy;})()',45)
                # Real Agent recommendation, no replacement playback.
                before=await native.state()
                await pet.evaluate('(()=>{'+PET+'app.clearResultCard();app.sendText("推荐几首歌");return true;})()')
                await until(pet,'(()=>{'+PET+'return app.resultCard?.items?.length&&app.resultCard.items.every(x=>x.source==="netease_client_daily");})()',70)
                after=await native.state();assert after['song_id']==before['song_id']
                row['agent_daily_candidates']=await pet.evaluate('(()=>{'+PET+'return JSON.parse(JSON.stringify(app.resultCard.items));})()')
                row['recommend_did_not_change_song']=True;save()
                await until(pet,'(()=>{'+PET+'return !app.turnBusy;})()',45)
            await switch(pet,dev,'hiyori');await switch(pet,dev,'hotaru')
            report['role_cards_cleared']=await pet.evaluate('(()=>{'+PET+'return !app.resultCard&&!app.officialPlayback;})()')
        finally:
            # Only the known test song may be restored; never toggle another song.
            now=await native.state()
            if baseline is not None and now['song_id']=='36308916':
                final=await native.favorite('36308916',baseline);report['final_favorite_restored']=final['liked']==baseline
            await switch(pet,dev,'hotaru' if original=='hiyori' else 'hiyori');await switch(pet,dev,original)
            await pet.evaluate('(()=>{'+PET+'app.clearResultCard();app.hideSpeech();return true;})()')
            report['original_role_restored']=original;save()
    print(json.dumps(report,ensure_ascii=False))

if __name__=='__main__':asyncio.run(main())
