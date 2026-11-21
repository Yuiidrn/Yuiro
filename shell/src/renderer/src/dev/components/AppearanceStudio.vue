<script setup lang="ts">
import { computed,onBeforeUnmount,onMounted,ref,watch } from 'vue'
import { useLocalStorage } from '@vueuse/core'
import type { Live2DManifest } from '@shared'
import Live2DCanvas from '../../components/Live2DCanvas.vue'
import { resolveExpression,resolveMotion,type AvatarIntentLike } from '../../avatar/avatarSlots'
import { readPreview,writePreview } from '../../avatar/previewCache'
import { resourceCategory,resourceLabel } from '../../avatar/catalog'
import { useAvatarClickPref } from '../../composables/useAvatarClickPref'
import { motionKey } from '../../avatar/clickFeedback'
import { useConfigStore } from '../stores/config'
import { api,type PerformanceItem } from '../api'
import PerformanceEditor from './PerformanceEditor.vue'
import AvatarIdleCard from './AvatarIdleCard.vue'
import AvatarClickCard from './AvatarClickCard.vue'
import ModelHealth from './ModelHealth.vue'
type PreviewIntent=AvatarIntentLike&{duration_ms?:number;performance?:string}
type Item={id:string;name:string;category:string;detail:string;kind:'motion'|'expression'|'performance';intent:PreviewIntent}
const store=useConfigStore(),clickPref=useAvatarClickPref()
const current=computed(()=>String(store.sections?.persona?.model_path??''))
const selected=ref(current.value),models=ref<{path:string;registeredHint:string;name?:string;author?:string}[]>([])
const manifest=ref<Live2DManifest|null>(null),performances=ref<PerformanceItem[]>([])
const stage=ref<InstanceType<typeof Live2DCanvas>>(),tab=ref('motion'),query=ref(''),category=ref('全部'),page=ref(0)
const busy=ref(false),loading=ref(true),stageFailed=ref(false),generating=ref(false),error=ref(''),status=ref(''),activeItem=ref(''),sendLive=ref(false)
const thumbs=ref<Record<string,string>>({}),modelThumbs=ref<Record<string,string>>({})
const favorites=useLocalStorage<Record<string,string[]>>('yuiro-appearance-favorites-v1',{})
const favKey=computed(()=>`${store.character?.active_id||'hiyori'}:${selected.value}`)
const favoriteIds=computed(()=>favorites.value?.[favKey.value]??[])
let version=0,work=0,dead=false
const tabs=[['motion','动作'],['expression','表情'],['performance','Agent演出'],['click','单击反馈'],['behavior','互动节奏'],['health','资源维护']]
function modelName(m:{path:string;name?:string;registeredHint:string}){return m.name||`${m.registeredHint} · ${m.path.split('/').at(-2)}`}
function modelImage(path:string){
  if(modelThumbs.value[path])return modelThumbs.value[path]
  const file=path==='/live2d/hiyori/Hiyori.model3.json'?'hiyori.png':path==='/live2d/Hotaru Shiomi/016_casual_spring_01/016_casual_spring_01.model3.json'?'hotaru.png':''
  return file?new URL(`./previews/${file}`,window.location.href).href:''
}
async function scan(){try{models.value=await window.yuiro.scanLive2dModels()}catch(e){error.value=String(e)}}
watch(current,value=>{if(value)selected.value=value},{immediate:true})
watch([selected,()=>store.character?.active_id],async ([path])=>{
  const request=++version;work++;loading.value=true;stageFailed.value=false;manifest.value=null;performances.value=[];activeItem.value='';error.value='';status.value='';sendLive.value=false;page.value=0
  if(!path)return
  try{
    const m=await window.yuiro.inspectPetModel(path)
    if(request!==version||dead)return
    manifest.value=m
    if(path===current.value){const response=await api.getPerformances();if(request===version&&!dead)performances.value=response.performances??[]}
  }catch(e){if(request===version)error.value=String(e)}
},{immediate:true})
function ready(path:string){if(path!==selected.value)return;loading.value=false;modelThumbs.value={...modelThumbs.value,[path]:stage.value?.capturePreview()||''}}
function failed(path:string,message:string){if(path!==selected.value)return;loading.value=false;stageFailed.value=true;error.value=message}
async function applyModel(){
  if(!selected.value||busy.value||selected.value===current.value)return
  const path=selected.value,role=store.character?.active_id;busy.value=true;error.value=''
  try{await store.applySection('persona',{model_path:path});if(role!==store.character?.active_id)return;await window.yuiro.setPetModel(path,role);status.value='模型已应用到当前角色'}catch(e){error.value=String(e)}finally{busy.value=false}
}
const items=computed<Item[]>(()=>{
  if(tab.value==='motion')return (manifest.value?.motions??[]).map(m=>({id:`m:${motionKey(m)}`,kind:'motion',name:resourceLabel(m.file,m.slot),category:resourceCategory(m.slot),detail:`${m.group} #${m.index} · ${(m.durationMs/1000).toFixed(1)}秒${m.direction?' · '+m.direction:''}`,intent:{expression:'',motion:m.group,motion_index:m.index,duration_ms:m.durationMs||2600}}))
  if(tab.value==='expression')return (manifest.value?.expressions??[]).map(e=>({id:`e:${e.name}`,kind:'expression',name:resourceLabel(e.name,e.slot),category:resourceCategory(e.slot),detail:e.name,intent:{expression:e.name}}))
  if(tab.value==='performance')return performances.value.map(p=>({id:`p:${p.name}`,kind:'performance',name:p.name,category:resourceCategory(p.motion_slot||p.expression_slot||''),detail:p.note||'角色语义演出',intent:{...p,performance:p.name}}))
  return []
})
const categories=computed(()=>['全部','收藏',...new Set(items.value.map(x=>x.category))])
const filtered=computed(()=>items.value.filter(x=>(category.value==='全部'||category.value==='收藏'&&favoriteIds.value.includes(x.id)||x.category===category.value)&&`${x.name} ${x.detail}`.toLowerCase().includes(query.value.trim().toLowerCase())))
const visible=computed(()=>filtered.value.slice(page.value*12,page.value*12+12))
const pages=computed(()=>Math.max(1,Math.ceil(filtered.value.length/12)))
watch([tab,query,category],()=>{work++;page.value=0})
watch(tab,()=>{category.value='全部'})
function favorite(id:string){const list=favoriteIds.value;favorites.value={...favorites.value,[favKey.value]:list.includes(id)?list.filter(x=>x!==id):[...list,id]}}
function cacheKey(item:Item){return `${item.kind==='expression'?'v3-head':'v2'}:${selected.value}:${item.id}:${JSON.stringify(item.intent)}`}
function canAddClick(item:Item){return !!resolveMotion(manifest.value,item.intent)}
async function previewIntent(intent:PreviewIntent){
  clearTimeout(autoTimer)
  const request=++work,path=selected.value
  let prepared=false
  try{prepared=await stage.value?.preparePreview(intent,()=>request===work&&!dead&&path===selected.value)||false}
  catch(e){if(request===work&&!dead)error.value=`预览加载失败，可重试：${String(e)}`;return false}
  if(!prepared)return false
  if(sendLive.value&&selected.value===current.value){
    const motion=resolveMotion(manifest.value,intent),expression=resolveExpression(manifest.value,intent)
    try{await window.yuiro.applyPetIntent({characterId:store.character?.active_id,modelPath:current.value,name:intent.performance||'外观预览',expression:expression.name,motion:motion?.group||'',motionIndex:motion?.index,durationMs:intent.duration_ms||motion?.durationMs||1800})}catch(e){error.value=String(e)}
  }
  return request===work&&!dead&&path===selected.value
}
async function preview(item:Item){
  activeItem.value=item.id;status.value=item.name
  const operation=previewIntent(item.intent),request=work
  if(!await operation)return
  await new Promise(r=>setTimeout(r,450))
  if(request!==work||dead)return
  const key=cacheKey(item),image=stage.value?.capturePreview(item.kind==='expression')||''
  if(image){thumbs.value[key]=image;void writePreview(key,image)}
}
function stopPreview(){clearTimeout(autoTimer);work++;stage.value?.cancelPerformance();stage.value?.applyAvatarIntent({expression:''})}

async function generate(){
  if(generating.value||loading.value||stageFailed.value||dead)return
  const request=++work,path=selected.value;generating.value=true
  const valid=()=>request===work&&!dead&&path===selected.value
  try{
    // 先整页读缓存，再逐个生成缺项；缓存命中不会播放舞台。
    const batch=visible.value.map(item=>({item,key:cacheKey(item)}))
    await Promise.all(batch.map(async({key})=>{const cached=await readPreview(key);if(valid()&&cached)thumbs.value[key]=cached}))
    for(const {item,key} of batch){
      if(!valid())break
      if(thumbs.value[key])continue
      try{
        const prepared=await stage.value?.preparePreview(item.intent,valid)
        if(!prepared||!valid())break
        await new Promise(r=>setTimeout(r,180))
        if(!valid())break
        const image=stage.value?.capturePreview(item.kind==='expression')||''
        if(image){thumbs.value[key]=image;void writePreview(key,image)}
      }catch(e){if(valid())error.value=`缩略图生成失败，可点击重试：${String(e)}`}
    }
  }finally{generating.value=false}
}
let autoTimer:ReturnType<typeof setTimeout>|undefined
function queueThumbnails(){
  clearTimeout(autoTimer)
  autoTimer=setTimeout(()=>{if(dead)return;if(generating.value){queueThumbnails();return}void generate()},180)
}
watch([visible,loading],()=>{work++;if(!loading.value&&visible.value.length)queueThumbnails()})
function addClick(item:Item){const motion=resolveMotion(manifest.value,item.intent);if(!motion)return;const pool=clickPref.read(selected.value,manifest.value),key=motionKey(motion);if(!pool.motions.includes(key))clickPref.write(selected.value,{...pool,motions:[...pool.motions,key]});status.value='已加入此模型的单击反馈池'}
onMounted(()=>{void scan();window.addEventListener('yuiro:models-changed',scan)})
onBeforeUnmount(()=>{clearTimeout(autoTimer);dead=true;version++;work++;window.removeEventListener('yuiro:models-changed',scan)})
</script>
<template>
 <div class="appearance-studio">
  <header class="studio-heading"><div><span class="eyebrow">CHARACTER STUDIO</span><h2>角色演出工作台</h2><p>先在舞台看效果，再决定角色如何回应你。</p></div><button class="btn" @click="scan">刷新资源</button></header>
  <div class="model-ribbon" aria-label="模型选择">
   <button v-for="m in models" :key="m.path" class="model-tile" :class="{selected:m.path===selected}" :disabled="busy" @click="selected=m.path">
    <img v-if="modelImage(m.path)" :src="modelImage(m.path)" alt=""/><span v-else class="model-placeholder">◇</span><strong>{{modelName(m)}}</strong><small>{{m.path===current?'当前使用':'点击预览'}}{{m.author?' · '+m.author:''}}</small>
   </button>
  </div>
  <p v-if="error" class="studio-error" role="alert">{{error}}</p>
  <div class="studio-workspace">
   <aside class="preview-pane">
    <div class="studio-stage"><Live2DCanvas v-if="selected" ref="stage" :mouth-open="0" :model-path="selected" preview @ready="ready" @failed="failed"/><span v-if="loading" class="stage-loading">加载模型预览…</span><span class="stage-badge">{{selected===current?'当前模型':'仅预览 · 未应用'}}</span></div>
    <p class="preview-status" role="status">{{status||'点击右侧资源，即可在这里播放'}}</p>
    <div class="preview-actions"><button class="btn" @click="stopPreview">停止 / 复位</button><button class="btn btn-primary" :disabled="busy||loading||stageFailed||selected===current" @click="applyModel">{{busy?'应用中…':'应用到当前角色'}}</button></div>
    <label class="hint"><input v-model="sendLive" type="checkbox" :disabled="selected!==current||generating||stageFailed"/>同时在桌宠上试演</label>
   </aside>
   <main class="resource-pane">
    <nav class="studio-tabs" aria-label="演出设置"><button v-for="[id,label] in tabs" :key="id" :class="{active:tab===id}" @click="tab=id">{{label}}</button></nav>
    <template v-if="['motion','expression','performance'].includes(tab)">
     <div v-if="tab==='performance'&&selected!==current" class="hint">应用模型后，可读取当前角色的 Agent 演出搭配。</div>
     <div class="resource-toolbar"><input v-model="query" placeholder="搜索名称、文件或用途…" aria-label="搜索演出资源"/><button class="btn" :disabled="loading||stageFailed||generating||!visible.length" @click="generate">{{generating?`生成中 ${visible.filter(item=>thumbs[cacheKey(item)]).length}/${visible.length}`:'生成本页预览图'}}</button></div>
     <div class="category-chips"><button v-for="c in categories" :key="c" :class="{active:category===c}" @click="category=c">{{c}}</button></div>
     <div class="resource-grid">
      <article v-for="item in visible" :key="item.id" class="resource-tile" :class="{playing:activeItem===item.id}">
       <button class="resource-play" :disabled="loading||stageFailed" @click="preview(item)"><img v-if="thumbs[cacheKey(item)]" :src="thumbs[cacheKey(item)]" alt=""/><span v-else class="resource-placeholder">{{item.kind==='expression'?'◡':'▷'}}<small>点击动态预览</small></span><strong>{{item.name}}</strong><small>{{item.detail}}</small></button>
       <div class="tile-actions"><button :aria-label="favoriteIds.includes(item.id)?'取消收藏':'收藏'" @click="favorite(item.id)">{{favoriteIds.includes(item.id)?'★':'☆'}}</button><button v-if="canAddClick(item)" @click="addClick(item)">＋ 单击池</button></div>
      </article>
     </div>
     <p v-if="!filtered.length" class="hint empty-state">当前分类没有资源，试试其他分类或搜索词。</p>
     <div class="resource-pages"><button class="btn" :disabled="page===0" @click="work++;page--">上一页</button><span>{{page+1}} / {{pages}} · {{filtered.length}} 项</span><button class="btn" :disabled="page+1>=pages" @click="work++;page++">下一页</button></div>
     <details v-if="tab==='performance'&&selected===current"><summary>编辑 Agent 表情、动作搭配与自定义演出</summary><PerformanceEditor local-preview @preview="previewIntent" @catalog="performances=$event"/></details>
    </template>
    <AvatarClickCard v-else-if="tab==='click'&&selected===current"/>
    <AvatarIdleCard v-else-if="tab==='behavior'&&selected===current"/>
    <ModelHealth v-else-if="tab==='health'&&selected===current"/>
    <p v-else class="hint empty-state">应用此模型后，可编辑它的互动配置；预览不会修改当前角色。</p>
   </main>
  </div>
 </div>
</template>
<style scoped>
.appearance-studio{color:var(--text);max-width:1500px;margin:auto}.studio-heading{display:flex;justify-content:space-between;align-items:center;gap:18px;margin-bottom:14px}.eyebrow{font-size:10px;letter-spacing:.18em;color:var(--accent)}h2{font-weight:500;font-size:25px;margin:8px 0}.studio-heading p{font-size:12px;color:var(--muted);margin:0}.model-ribbon{display:flex;gap:12px;overflow-x:auto;padding:4px 2px 14px}.model-tile{position:relative;flex:0 0 245px;border:1px solid var(--border);border-radius:16px;background:var(--card);color:inherit;cursor:pointer;padding:10px;display:grid;grid-template-columns:68px 1fr;align-items:center;gap:6px 10px;text-align:left;height:104px;box-sizing:border-box}.model-tile.selected{border-color:var(--accent);background:var(--accent-soft)}.model-tile img,.model-placeholder{grid-row:1 / 3;width:68px;height:82px;object-fit:contain}.model-placeholder{display:grid;place-items:center;font-size:48px;color:var(--accent);background:linear-gradient(130deg,var(--accent-soft),transparent);border-radius:10px}.model-tile strong{font-size:12px;font-weight:500}.model-tile small{font-size:10px;color:var(--muted)}.studio-workspace{display:grid;grid-template-columns:minmax(240px,.85fr) minmax(350px,1.35fr);gap:24px;align-items:start}.preview-pane{position:sticky;top:12px;min-width:0}.studio-stage{height:clamp(350px,55vh,620px);position:relative;overflow:hidden;border:1px solid var(--border);border-radius:24px;background:radial-gradient(ellipse at 50% 60%,var(--accent-soft),transparent 75%),var(--card)}.stage-badge,.stage-loading{position:absolute;left:14px;top:14px;font-size:10px;color:var(--muted);background:var(--card);padding:6px 9px;border-radius:20px}.stage-loading{top:auto;bottom:14px}.preview-status{font-size:12px;line-height:1.7;min-height:2em;color:var(--text-soft)}.preview-actions{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:12px}.resource-pane{min-width:0}.studio-tabs,.category-chips{display:flex;gap:7px;flex-wrap:wrap;margin-bottom:18px}.studio-tabs button,.category-chips button{border:0;border-radius:9px;padding:8px 11px;background:var(--card);color:var(--text-soft);cursor:pointer;font:inherit;font-size:12px}.studio-tabs button.active,.category-chips button.active{background:var(--accent-soft);color:var(--accent)}.resource-toolbar{display:flex;gap:8px;margin-bottom:16px}.resource-toolbar input{min-width:80px;flex:1;background:var(--input);border:1px solid var(--border);color:inherit;border-radius:10px;padding:9px 12px}.resource-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(135px,1fr));gap:12px}.resource-tile{border:1px solid var(--border-soft);border-radius:15px;overflow:hidden;background:var(--card);transition:border-color .2s}.resource-tile.playing{border-color:var(--accent)}.resource-play{width:100%;padding:9px;border:0;background:none;color:inherit;cursor:pointer;display:flex;flex-direction:column;gap:7px;text-align:left}.resource-play img,.resource-placeholder{width:100%;height:120px;object-fit:contain;background:linear-gradient(145deg,var(--accent-soft),transparent);border-radius:9px}.resource-placeholder{display:flex;flex-direction:column;align-items:center;justify-content:center;font-size:32px;color:var(--accent)}.resource-placeholder small{font-size:10px;margin-top:8px}.resource-play strong{font-size:11px;font-weight:500;overflow-wrap:anywhere}.resource-play small{font-size:10px;color:var(--muted);overflow-wrap:anywhere}.tile-actions{display:flex;justify-content:space-between;border-top:1px solid var(--border-soft);padding:5px 8px}.tile-actions button{border:0;background:none;color:var(--accent);font-size:11px;padding:5px;cursor:pointer}.resource-pages{display:flex;align-items:center;justify-content:center;gap:12px;margin:20px 0;font-size:11px;color:var(--muted)}.studio-error{color:var(--err);font-size:12px}.empty-state{padding:30px;text-align:center}details{margin-top:18px}summary{cursor:pointer;font-size:12px;color:var(--text-soft);padding:12px 0}@media(max-width:850px){.studio-workspace{grid-template-columns:240px minmax(260px,1fr);gap:14px}.resource-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}@media(max-width:620px){.studio-workspace{grid-template-columns:1fr}.preview-pane{position:relative;top:0}.studio-stage{height:330px}}
</style>
