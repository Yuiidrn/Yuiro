<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import type { Live2DManifest } from '@shared'
import { useConfigStore } from '../stores/config'
import { useAvatarClickPref } from '../../composables/useAvatarClickPref'
import { motionKey, recommendedClicks } from '../../avatar/clickFeedback'
const store=useConfigStore(),pref=useAvatarClickPref()
const path=computed(()=>String(store.sections?.persona?.model_path??''))
const manifest=ref<Live2DManifest|null>(null),candidate=ref(''),error=ref('')
let version=0
watch(path,async value=>{
  const request=++version;manifest.value=null;candidate.value='';error.value=''
  if(!value)return
  try{const result=await window.yuiro.inspectPetModel(value);if(request===version)manifest.value=result}
  catch(e){if(request===version)error.value=String(e)}
},{immediate:true})
onBeforeUnmount(()=>{version++})
const pool=computed(()=>pref.read(path.value,manifest.value))
const choices=computed(()=>manifest.value?.motions??[])
function label(key:string){const m=choices.value.find(x=>motionKey(x)===key);return m?`${key} · ${m.file.split('/').at(-1)} · ${(m.durationMs/1000).toFixed(1)}秒`:key}
function add(){if(candidate.value&&!pool.value.motions.includes(candidate.value))pref.write(path.value,{...pool.value,motions:[...pool.value.motions,candidate.value]})}
function remove(key:string){pref.write(path.value,{...pool.value,motions:pool.value.motions.filter(x=>x!==key)})}
</script>
<template>
 <section class="bubble card-narrow">
  <h3 class="bubble-title">单击反馈动作池</h3>
  <p class="hint">单击模型轮廓时随机播放，拖动和界面按钮不触发。按角色和模型独立保存，改完即时生效；优先选招呼、开心、思考等中性或正向动作。</p>
  <label><input type="checkbox" :checked="pool.enabled" @change="pref.write(path,{...pool,enabled:($event.target as HTMLInputElement).checked})"/>启用单击反馈</label>
  <p v-if="error" role="alert">{{error}}</p>
  <div class="click-actions">
   <select v-model="candidate" aria-label="选择单击动作"><option value="">从当前模型选择动作…</option><option v-for="motion in choices" :key="motionKey(motion)" :value="motionKey(motion)">{{label(motionKey(motion))}}</option></select>
   <button class="btn" :disabled="!candidate||!manifest" @click="add">添加</button>
   <button class="btn" :disabled="!manifest" @click="pref.write(path,{...pool,motions:recommendedClicks(manifest)})">推荐动作</button>
   <button class="btn" @click="pref.write(path,{...pool,motions:[]})">清空</button>
  </div>
  <p v-if="!pool.motions.length" class="hint">动作池为空，单击不会播放动作。</p>
  <ul><li v-for="key in pool.motions" :key="key">{{label(key)}} <button class="btn" @click="remove(key)">移除</button></li></ul>
 </section>
</template>
<style scoped>
.click-actions{display:flex;flex-wrap:wrap;gap:8px;margin:16px 0}.click-actions select{flex:1;min-width:180px;max-width:100%;background:var(--input);color:var(--text);border:1px solid var(--border);border-radius:8px;padding:8px}ul{list-style:none;padding:0}li{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:9px 0;border-bottom:1px solid var(--border-soft);font-size:12px;overflow-wrap:anywhere}
</style>
