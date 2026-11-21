"""双角色真实客户端收藏/日推验收；无平台 API，无合成搜索数据。"""
import asyncio,json,sys,time
from c0_live_acceptance import ROOT,PET,DEV,Page,pages
from c0_live_scenarios import switch
from ui_customization_acceptance import until
sys.path.insert(0,str(ROOT/'engine'))
from yuiro.native import netease_client as native
OUT=ROOT/'docs/plan/curve-favorite-artifacts'

async def main():
    report={'kind':'real card click + real Agent favorite/rec + native client readback','roles':[]}
    OUT.mkdir(exist_ok=True)
    def save(): (OUT/'dual-live.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    async with Page(next(p for p in await pages() if p['title']=='Yuiro')) as pet,Page(next(p for p in await pages() if 'dev.html' in p['url'])) as dev:
        original=await dev.evaluate('(()=>{'+DEV+'return s.character.active_id;})()')
        baseline=None
        try:
            for role in ['hiyori','hotaru']:
                await switch(pet,dev,role)
                await pet.evaluate('(()=>{'+PET+'app.clearResultCard();app.sendText("/搜歌 Monody");return true;})()')
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
                    start=time.monotonic();await card.evaluate('document.querySelector(".rc-favorite").click()')
                    await until(pet,'(()=>{'+PET+'return app.officialPlayback?.liked==='+json.dumps(not baseline)+'&&!app.officialPending;})()',80)
                    assert (await native.favorite('36308916'))['liked']==(not baseline)
                    row['card_write_readback_seconds']=round(time.monotonic()-start,2);save()
                    target='true' if baseline else 'false'
                    query='请仅调用 netease_favorite，将当前角色拥有的歌曲 ID 36308916 的 liked 设为 '+target+'，等待读回后如实报告。不播放，不调用其他工具。'
                    start=time.monotonic();await pet.evaluate('(()=>{'+PET+'app.sendText('+json.dumps(query,ensure_ascii=False)+');return true;})()')
                    async def restored():
                        for _ in range(160):
                            if (await native.favorite('36308916'))['liked']==baseline:return
                            await asyncio.sleep(.5)
                        raise RuntimeError('Agent did not restore favorite')
                    await restored();row['agent_restore_seconds']=round(time.monotonic()-start,2);row['favorite_restored']=True;save()
                    await until(pet,'(()=>{'+PET+'return !app.turnBusy;})()',45)
                # Real Agent recommendation, no replacement playback.
                before=await native.state()
                await pet.evaluate('(()=>{'+PET+'app.clearResultCard();app.sendText("请调用 netease_recommend 随机推荐几首客户端每日推荐里的歌，只展示候选，不播放，不搜索。");return true;})()')
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
