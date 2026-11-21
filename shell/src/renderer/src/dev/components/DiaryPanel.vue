<script setup lang="ts">
import { computed,onBeforeUnmount,onMounted,ref } from 'vue'
import { diaryApi,type DiaryBrief,type DiaryDetail,type DiaryAsset } from '../api'
import DiaryMedia from '../../diary/DiaryMedia.vue'
const editing=ref(false),editTitle=ref(''),editText=ref(''),editAssets=ref<DiaryAsset[]>([]),mediaBusy=ref(false),revisions=ref<DiaryDetail['diary'][]>([])
const props=defineProps<{embedded?:boolean}>(),emit=defineEmits<{write:[]}>()
const items=ref<DiaryBrief[]>([]),detail=ref<DiaryDetail|null>(null),keyword=ref(''),error=ref(''),notice=ref(''),loading=ref(false),reading=ref(false),busy=ref(false),hasMore=ref(false),pendingDelete=ref<number|null>(null)
let version=0,detailVersion=0,dead=false
const polished=ref(false)
const title=computed(()=>detail.value?.diary.title||detail.value?.diary.summary||'一段记录')
function date(s:string){return new Date(s).toLocaleString('zh-CN',{year:'numeric',month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'})}
function privacy(p:string){return p==='shared'?'已加入角色记忆':'仅保存在日记中'}
function write(){if(props.embedded)emit('write');else void window.yuiro.openDiary()}
async function load(more=false){
 const stamp=++version;loading.value=true;error.value=''
 if(!more){items.value=[];detail.value=null;detailVersion++}
 try{const r=await diaryApi.list({q:keyword.value.trim(),limit:30,offset:more?items.value.length:0});if(stamp!==version||dead)return
  if(r.status!=='ok')throw Error(r.note||'日记暂不可用')
  items.value=more?[...items.value,...r.items.filter(x=>!items.value.some(y=>x.id===y.id))]:r.items;hasMore.value=!keyword.value.trim()&&r.items.length===30
 }catch(e){if(stamp===version)error.value=String(e instanceof Error?e.message:e)}finally{if(stamp===version)loading.value=false}
}
async function open(id:number){editing.value=false;revisions.value=[];const stamp=++detailVersion;detail.value=null;reading.value=true;error.value='';pendingDelete.value=null;polished.value=false
 try{const r=await diaryApi.detail(id);if(stamp!==detailVersion||dead)return;if(r.status!=='ok'||!r.diary)throw Error('记录已不存在');detail.value=r}catch(e){if(stamp===detailVersion)error.value=String(e)}finally{if(stamp===detailVersion)reading.value=false}}
async function mutate(action:'privacy'|'delete'|'review'){
 const id=detail.value?.diary.id;if(!id||busy.value)return
 if(action==='delete'&&pendingDelete.value!==id){pendingDelete.value=id;return}
 const stamp=detailVersion;busy.value=true;error.value=''
 try{
  const r=action==='delete'?await diaryApi.remove(id):action==='review'?await diaryApi.review(id):await diaryApi.setPrivacy(id,detail.value!.diary.privacy==='shared'?'local_only':'shared')
  if(r.status!=='ok')throw Error('note' in r?String(r.note):'操作未完成')
  if(stamp!==detailVersion||dead)return
  if(action==='delete'){detail.value=null;await load();notice.value='记录已删除'}else{await open(id);if(detail.value)items.value=items.value.map(x=>x.id===id?{...x,privacy:detail.value!.diary.privacy,memory_written:detail.value!.diary.memory_written}:x);notice.value=action==='review'?'回应已更新':'记忆共享设置已更新'}
 }catch(e){if(stamp===detailVersion)error.value=String(e)}finally{busy.value=false;pendingDelete.value=null}
}
function edit(snapshot=detail.value?.diary){
 if(!snapshot||!detail.value)return
 editing.value=true;editTitle.value=snapshot.title||'';editText.value=snapshot.raw_text;editAssets.value=[...(snapshot.attachments||[])];error.value=''
}
async function saveEdit(){
 if(!detail.value||busy.value||mediaBusy.value)return
 const id=detail.value.diary.id,stamp=detailVersion;busy.value=true
 try{const r=await diaryApi.edit(id,{revision:detail.value.diary.revision,title:editTitle.value,raw_text:editText.value,attachment_ids:editAssets.value.map(x=>x.id)})
 if(stamp!==detailVersion||dead)return
 if(r.status!=='ok')throw Error('修改未保存')
 await open(id);items.value=items.value.map(x=>x.id===id?{...x,title:detail.value!.diary.title,summary:detail.value!.diary.summary}:x)
 notice.value=detail.value?.diary.privacy==='shared'&&!r.memory_written?'修改已保存；旧记忆已撤回，新记忆暂未写入':'修改已保存，旧版本可在修订历史查看'
 }catch(e){if(stamp===detailVersion)error.value=String(e instanceof Error?e.message:e)}finally{busy.value=false}
}
async function history(){if(!detail.value)return;const stamp=detailVersion;try{const r=await diaryApi.revisions(detail.value.diary.id);if(stamp===detailVersion&&!dead){revisions.value=r.items;if(!r.items.length)notice.value='这篇记录尚无历史修订'}}catch(e){if(stamp===detailVersion)error.value=String(e)}}
function changed(e:StorageEvent){if(e.key==='yuiro-active-character'){version++;detailVersion++;editing.value=false;editAssets.value=[];revisions.value=[];detail.value=null;notice.value='';pendingDelete.value=null;void load()}}
onMounted(()=>{void load();window.addEventListener('storage',changed)})
onBeforeUnmount(()=>{dead=true;version++;detailVersion++;window.removeEventListener('storage',changed)})
</script>
<template>
 <section class="diary-blog" aria-label="日记归档">
  <header class="blog-head"><div><span class="eyebrow">LIFE / JOURNAL</span><h2>日常记录</h2><p>把值得记住的片刻，轻轻留在这里。</p></div><button class="btn btn-primary" @click="write">写一篇</button></header>
  <form class="blog-search" @submit.prevent="load()"><input v-model="keyword" type="search" placeholder="搜索正文与摘要" aria-label="搜索日记"/><button class="btn" :disabled="loading">搜索</button><button type="button" class="btn" :disabled="loading" @click="keyword='';load()">全部记录</button></form>
  <p v-if="error" class="blog-error" role="alert">{{error}}</p><p v-if="notice" class="hint" role="status">{{notice}}</p>
  <template v-if="!detail&&!reading">
   <p class="hint">{{loading?'正在读取…':`${items.length} 篇记录${keyword?' · 搜索最多显示30篇':''}`}}</p>
   <div class="post-list"><button v-for="item in items" :key="item.id" class="post-row" @click="open(item.id)"><time>{{date(item.created_at)}}</time><h3>{{item.title||item.summary||'未命名的片刻'}}</h3><div class="post-meta"><span>{{privacy(item.privacy)}}</span><span v-for="tag in [...item.mood_tags,...item.topics].slice(0,4)" :key="tag">#{{tag}}</span></div><span class="post-open">阅读 →</span></button></div>
   <div v-if="!loading&&!items.length" class="blog-empty"><h3>{{keyword?'暂未找到匹配记录':'还没有记录'}}</h3><p>可以从一句话开始，不需要凑成一整页。</p><button class="btn" @click="write">开始记录</button></div>
   <button v-if="hasMore" class="btn" :disabled="loading" @click="load(true)">加载更多</button>
  </template>
  <p v-if="reading" class="hint">正在打开…</p>
  <article v-if="detail&&!reading" class="post-detail">
   <button :disabled="editing||busy" class="blog-back" @click="detail=null;detailVersion++">← 所有记录</button><time>{{date(detail.diary.created_at)}}</time><h2>{{title}}</h2><div class="post-meta"><span>{{privacy(detail.diary.privacy)}}</span><span v-for="tag in detail.diary.mood_tags" :key="tag">#{{tag}}</span></div>
   <form v-if="editing" class="edit-record" @submit.prevent="saveEdit"><input v-model="editTitle" maxlength="160" aria-label="编辑标题" placeholder="标题" :disabled="busy"/><textarea v-model="editText" aria-label="编辑正文" rows="12" :disabled="busy"/><DiaryMedia v-model="editAssets" :disabled="busy" @busy="mediaBusy=$event"/><div class="post-actions"><button class="btn btn-primary" :disabled="busy||mediaBusy">保存修改</button><button type="button" class="btn" :disabled="busy||mediaBusy" @click="editing=false">取消修改</button></div></form>
   <template v-else>
   <div v-if="detail.diary.polished_text!==detail.diary.raw_text" class="post-tabs"><button class="btn" :aria-pressed="!polished" @click="polished=false">原文</button><button class="btn" :aria-pressed="polished" @click="polished=true">整理稿</button></div>
   <p class="post-body">{{polished?detail.diary.polished_text:detail.diary.raw_text}}</p>
   <DiaryMedia :model-value="detail.diary.attachments||[]" readonly/>
   <div class="post-actions"><button class="btn" :disabled="busy" @click="edit()">编辑记录</button><button class="btn" :disabled="busy" @click="history">修订历史</button></div>
   <div v-if="revisions.length" class="revision-list"><button v-for="old in revisions" :key="old.revision" class="btn" @click="edit(old)">载入版本 {{old.revision}} · {{date(old.updated_at||old.created_at)}}</button><p class="hint">载入后可继续修改，保存将新增修订。</p></div>
   <blockquote v-if="detail.diary.closing_review">{{detail.diary.closing_review}}</blockquote>
   <details class="post-options"><summary>记录与记忆管理</summary><p class="hint">共享才会写入角色记忆；转为仅保存会同步移除关联记忆。</p><div class="post-actions"><button class="btn" :disabled="busy" @click="mutate('privacy')">{{detail.diary.privacy==='shared'?'改为仅保存':'共享到角色记忆'}}</button><button class="btn" :disabled="busy" @click="mutate('review')">生成一句回应</button><button class="btn" :disabled="busy" @click="mutate('delete')">{{pendingDelete===detail.diary.id?'确认删除记录及关联记忆':'删除记录'}}</button><button v-if="pendingDelete" class="btn" @click="pendingDelete=null">取消</button></div></details>
   </template>
  </article>
 </section>
</template>
<style scoped>
.diary-blog{width:100%;max-width:1000px;margin:auto;color:var(--text);padding:12px 0 36px}.blog-head{display:flex;align-items:center;justify-content:space-between;gap:20px;margin-bottom:28px}.eyebrow{font-size:10px;letter-spacing:.18em;color:var(--accent)}.blog-head h2{font-size:26px;font-weight:600;margin:10px 0}.blog-head p{color:var(--text-soft);font-size:13px;margin:0}.blog-search{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:26px}.blog-search input{flex:1;min-width:150px;border:1px solid var(--border);border-radius:10px;padding:10px 12px;background:var(--input);color:inherit}.post-list{display:grid;gap:0}.post-row{position:relative;display:block;width:100%;text-align:left;padding:24px 14px;border:0;border-bottom:1px solid var(--border-soft);background:transparent;color:inherit;cursor:pointer;border-radius:8px}.post-row:hover,.post-row:focus-visible{background:var(--card)}time{display:block;font-size:12px;color:var(--muted)}.post-row h3{font-size:18px;font-weight:500;line-height:1.6;margin:9px 0 12px}.post-meta{display:flex;gap:12px;flex-wrap:wrap;color:var(--muted);font-size:11px}.post-open{display:block;color:var(--accent);font-size:12px;margin-top:14px}.blog-empty{padding:48px 12px;text-align:center;color:var(--text-soft)}.blog-error{color:var(--err)}.post-detail{max-width:720px;margin:auto}.blog-back{border:0;background:none;color:var(--accent);cursor:pointer;padding:0;margin:12px 0 32px}.post-detail h2{font-size:24px;font-weight:500;line-height:1.6;margin:14px 0}.post-body{white-space:pre-wrap;overflow-wrap:anywhere;font-size:16px;line-height:1.95;margin:34px 0}.post-tabs,.post-actions{display:flex;flex-wrap:wrap;gap:8px;margin-top:20px}.post-detail blockquote{border-left:2px solid var(--border);margin:24px 0;padding:8px 18px;color:var(--text-soft);line-height:1.8}.post-options{border-top:1px solid var(--border-soft);margin-top:36px;padding:20px 0}.post-options summary{cursor:pointer;font-size:12px;color:var(--muted)}
.edit-record input,.edit-record textarea{display:block;width:100%;box-sizing:border-box;background:var(--input);color:var(--text);border:1px solid var(--border);border-radius:10px;padding:14px;margin:18px 0;font:inherit;line-height:1.8}.edit-record input{font-size:22px}.edit-record textarea{resize:vertical}.revision-list{display:grid;gap:8px;margin-top:20px}
</style>
