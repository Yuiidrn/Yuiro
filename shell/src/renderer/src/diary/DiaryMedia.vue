<script setup lang="ts">
import {ref,watch,onBeforeUnmount} from 'vue'
import {ENGINE_DEBUG_BASE} from '@shared'
import type {DiaryAsset} from '../dev/api'
const props=defineProps<{modelValue:DiaryAsset[];readonly?:boolean;disabled?:boolean}>()
const emit=defineEmits<{'update:modelValue':[DiaryAsset[]];busy:[boolean]}>()
const urls=ref<Record<string,string>>({}),error=ref(''),uploading=ref(false),picker=ref<HTMLInputElement>()
let version=0,disposed=false
async function headers(){return {'x-yuiro-secret':await window.yuiro.getEngineSecret(),'x-yuiro-character':localStorage.getItem('yuiro-active-character')||''}}
function clear(){Object.values(urls.value).forEach(URL.revokeObjectURL);urls.value={}}
watch(()=>props.modelValue.map(x=>x.id).join(','),async()=>{
 const stamp=++version;clear()
 for(const item of props.modelValue){
  try{const res=await fetch(`${ENGINE_DEBUG_BASE}/api/diary/assets/${item.id}`,{headers:await headers()});if(!res.ok)throw Error('附件暂不可读取');const blob=await res.blob();if(stamp!==version||disposed)return;urls.value[item.id]=URL.createObjectURL(blob)}catch(e){if(stamp===version)error.value=String(e)}
 }
},{immediate:true})
async function add(files:FileList|null){
 if(!files||props.readonly||props.disabled||uploading.value)return
 const role=localStorage.getItem('yuiro-active-character');uploading.value=true;emit('busy',true);error.value=''
 try{
  for(const file of Array.from(files)){
   if(props.modelValue.length>=8)throw Error('每篇最多8个附件')
   if(file.size>20*1024*1024)throw Error('单个附件不能超过20MB')
   const auth=await headers();if(disposed||role!==localStorage.getItem('yuiro-active-character'))return
   const res=await fetch(`${ENGINE_DEBUG_BASE}/api/diary/assets?name=${encodeURIComponent(file.name)}`,{method:'POST',headers:auth,body:file})
   const data=await res.json();if(!res.ok)throw Error(data.detail||'附件上传失败')
   if(disposed||role!==localStorage.getItem('yuiro-active-character'))return
   emit('update:modelValue',[...props.modelValue,data.asset]);await new Promise(r=>setTimeout(r,0))
  }
 }catch(e){error.value=String(e instanceof Error?e.message:e)}finally{uploading.value=false;emit('busy',false);if(picker.value)picker.value.value=''}
}
onBeforeUnmount(()=>{disposed=true;version++;clear()})
</script>
<template>
 <section class="media-area" @dragover.prevent @drop.prevent="add($event.dataTransfer?.files||null)">
  <div v-if="modelValue.length" class="media-grid"><figure v-for="item in modelValue" :key="item.id">
   <img v-if="item.mime.startsWith('image/')&&urls[item.id]" :src="urls[item.id]" :alt="item.name" loading="lazy"/>
   <audio v-else-if="item.mime.startsWith('audio/')&&urls[item.id]" :src="urls[item.id]" controls preload="metadata"/>
   <video v-else-if="urls[item.id]" :src="urls[item.id]" controls preload="metadata"/>
   <figcaption><span :title="item.name">{{item.name}}</span><button v-if="!readonly" type="button" :disabled="disabled||uploading" @click="emit('update:modelValue',modelValue.filter(x=>x.id!==item.id))" :aria-label="`移除${item.name}`">×</button><a v-if="urls[item.id]" :href="urls[item.id]" :download="item.name">下载</a></figcaption>
  </figure></div>
  <template v-if="!readonly"><input ref="picker" type="file" multiple accept="image/png,image/jpeg,image/gif,image/webp,audio/mpeg,audio/wav,audio/ogg,video/mp4,video/webm" hidden @change="add(($event.target as HTMLInputElement).files)"/><button class="text-button" type="button" :disabled="disabled||uploading" @click="picker?.click()">{{uploading?'正在添加…':'＋ 图片、音频或视频'}}</button></template>
  <p v-if="error" role="alert">{{error}}</p>
 </section>
</template>
<style scoped>
.media-area{margin:20px 0}.media-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(240px,100%),1fr));gap:16px}figure{margin:0;border:1px solid var(--border-soft);border-radius:12px;padding:10px;background:var(--card);min-width:0}img,video{display:block;width:100%;max-height:280px;object-fit:contain;border-radius:8px}audio{width:100%}figcaption{display:flex;align-items:center;gap:10px;font-size:12px;color:var(--muted);padding-top:10px}figcaption span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;flex:1}button,a{color:var(--accent);background:none;border:0;cursor:pointer}p{font-size:12px;color:var(--err)}.text-button{padding:10px 0;font:inherit;font-size:13px}
</style>
