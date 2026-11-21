<script setup lang="ts">
import { computed, nextTick, onMounted, onBeforeUnmount, ref } from 'vue'
import type { DetachedContent, UiKind, DetachedAction } from '../../../shared/detachedUi'
import ResultCard from '../components/ResultCard.vue'
import type { ResultCardItem } from '../composables/useResultCardPref'
import ReplySurface from '../components/ReplySurface.vue'
import { useUiAppearance } from '../composables/useUiAppearance'
const ui=useUiAppearance()
const requestedKind=new URLSearchParams(location.search).get('kind')
const kind:UiKind=requestedKind==='sources'?'sources':requestedKind==='results'?'results':'speech'
document.title=kind==='speech'?'Yuiro 回复':kind==='sources'?'Yuiro 来源':'Yuiro 结果'
const state=ref<DetachedContent|null>(null)
const root=ref<HTMLElement>()
const availableHeight=ref(screen.availHeight-16)
function updateAvailableHeight():void {availableHeight.value=screen.availHeight-16}
const card=computed(()=>kind==='sources'?state.value?.sources:state.value?.results)
const content=computed(()=>kind==='speech'?state.value?.speech:card.value)
const items=computed(()=>(card.value?.items??[]) as ResultCardItem[])
const style=computed(()=>({...ui.style(kind==='speech'?'speech':card.value?.kind==='source'?'source':'music'),width:`${Math.min(content.value?.width??224,screen.availWidth-20)}px`,borderRadius:kind==='speech'&&(ui.settings.value.speech.comic||ui.settings.value.speech.mode==='line')?'0':'var(--panel-radius)'}))
function openLink(url:string):void {void window.yuiro.openExternal(url)}
function action(index?:number,dismiss=false,action:DetachedAction['action']='pick'):void {
  if(state.value)window.yuiro.detachedAction({kind,key:state.value.key,index,dismiss,action})
}
let off:(()=>void)|undefined
let observer:ResizeObserver|undefined
async function measure():Promise<void> {
  await nextTick()
  if(root.value&&state.value)window.yuiro.detachedSize({width:root.value.offsetWidth,height:root.value.offsetHeight,key:state.value.key})
}
onMounted(()=>{
  window.addEventListener('resize',updateAvailableHeight)
  off=window.yuiro.onDetachedState(s=>{state.value=s;void measure()})
  observer=new ResizeObserver(()=>void measure())
  if(root.value)observer.observe(root.value)
  window.yuiro.detachedReady()
})
onBeforeUnmount(()=>{off?.();observer?.disconnect();window.removeEventListener('resize',updateAvailableHeight)})
</script>
<template>
  <main ref="root" class="surface" :class="{line:kind==='speech'&&ui.settings.value.speech.mode==='line'}" :style="{...style,'--reply-available-height':availableHeight+'px'}" :data-kind="kind">
    <button class="close" aria-label="收起" @click="action(undefined,true)">×</button>
    <ReplySurface v-if="kind==='speech'" :text="state?.speech.text??''" :alpha="state?.speech.alpha??.92" :tail-side="state?.speech.tailSide" :tip-y="state?.speech.tipY" @link="openLink" />
    <ResultCard v-else-if="card" detached :rect="null" :title="card.title" :kind="card.kind" :items="items" :playback="card.playback" :busy="card.busy" @pick="item=>action(items.indexOf(item))" @official="item=>action(items.indexOf(item),false,'open_official')" @client="item=>action(items.indexOf(item),false,'client_play')" @control="v=>action(undefined,false,v==='pause'?'client_pause':v==='resume'?'client_resume':v==='like'?'client_like':'client_unlike')"/>
  </main>
</template>
<style>
*{box-sizing:border-box}html,body,#app{margin:0;background:transparent;overflow:hidden;font-family:'Segoe UI','Microsoft YaHei',sans-serif;color:#29221c}
.surface{position:relative;min-height:40px;max-width:1024px;border-radius:16px;overflow:hidden;--radius-sm:6px;--dur-fast:120ms;--ease-out:ease-out}
.close{position:absolute;right:10px;top:9px;z-index:30;border:0;border-radius:50%;background:transparent;color:var(--panel-accent,#8c775b);font-size:16px;cursor:pointer;width:22px;height:22px}
.close:hover{background:#e8d6b9}
.surface .close{opacity:0}.surface:hover .close,.surface:focus-within .close{opacity:1}
</style>
