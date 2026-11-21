<script setup lang="ts">
import { computed,onBeforeUnmount,onMounted,ref } from 'vue'
import Live2DCanvas from '../../components/Live2DCanvas.vue'
import ReplySurface from '../../components/ReplySurface.vue'
import BracketMenu from '../../components/BracketMenu.vue'
import { useConfigStore } from '../stores/config'
import { useUiAppearance } from '../../composables/useUiAppearance'
import { useSpeechBubblePref } from '../../composables/useSpeechBubblePref'
import { placeDetached } from '../../../../main/detachedLayout'
import { dialogueLine,dialogueAnchor,dialogueOffset } from '../../../../shared/dialogueLine'
const props=defineProps<{text:string}>()
const store=useConfigStore(),ui=useUiAppearance(),bubble=useSpeechBubblePref()
const enabled=ref(true),island=ref(false),scene=ref<HTMLElement>(),canvas=ref<InstanceType<typeof Live2DCanvas>>()
const model=ref({x:110,y:70,width:100,height:270}),area=ref({x:0,y:0,width:700,height:460})
const reply=ref<HTMLElement>(),replyHeight=ref(180),previewScale=ref(.5),previewX=ref(0),previewY=ref(0)
let timer=0
function update():void {
  if(scene.value){
    previewScale.value=Math.min(scene.value.clientWidth/1000,scene.value.clientHeight/700)
    previewX.value=(scene.value.clientWidth-1000*previewScale.value)/2
    previewY.value=(scene.value.clientHeight-700*previewScale.value)/2
  }
  const r=canvas.value?.getLocalModelRect(),host=scene.value?.querySelector<HTMLElement>('.scene-model')
  if(!r||!host)return
  model.value={x:host.offsetLeft+r.left,y:host.offsetTop+r.top,width:r.width,height:r.height}
  area.value={x:0,y:0,width:1000,height:700}
  if(reply.value)replyHeight.value=reply.value.offsetHeight
}
const width=computed(()=>bubble.maxWidth.value+(ui.settings.value.speech.mode==='bubble'&&ui.settings.value.speech.comic?ui.settings.value.speech.tail:0))
const placement=computed(()=>placeDetached(model.value,area.value,{width:width.value,height:replyHeight.value},ui.settings.value.speechSide,bubble.offsetX.value,bubble.offsetY.value+dialogueOffset(ui.settings.value.speech,String(store.sections.persona?.model_path??''),model.value.height,replyHeight.value),[],ui.settings.value.gap))
const side=computed(()=>placement.value&&placement.value.x+placement.value.width/2<model.value.x+model.value.width/2?'right':'left')
const curve=computed(()=>{const a=dialogueAnchor(ui.settings.value.speech,String(store.sections.persona?.model_path??''));return placement.value&&ui.settings.value.speech.mode==='line'?dialogueLine(model.value,placement.value,a.mouthX,a.mouthY,ui.settings.value.speech.fontSize,ui.settings.value.speech.lineBend):null})
onMounted(()=>{timer=window.setInterval(update,250)})
onBeforeUnmount(()=>clearInterval(timer))
</script>
<template>
  <div class="scene-controls"><label><input v-model="enabled" type="checkbox" /> 开启当前模型与气泡的相对位置预览</label><label v-if="enabled"><input v-model="island" type="checkbox" /> 展示功能岛</label></div>
  <template v-if="enabled">
    <div ref="scene" class="ui-scene">
      <div class="scene-stage" :style="{left:previewX+'px',top:previewY+'px',transform:`scale(${previewScale})`}">
      <div class="scene-model"><Live2DCanvas ref="canvas" preview :mouth-open="0" :model-path="String(store.sections.persona?.model_path??'')" /></div>
      <svg v-if="curve" class="scene-curve" :style="{left:curve.x+'px',top:curve.y+'px',width:curve.width+'px',height:curve.height+'px'}" :viewBox="`0 0 ${curve.width} ${curve.height}`" aria-hidden="true"><path :d="curve.path" fill="none" :stroke="ui.settings.value.speech.lineColor" :stroke-width="ui.settings.value.speech.lineWidth" stroke-linecap="round" /></svg>
      <div ref="reply" class="scene-reply" :style="{left:(placement?.x??0)+'px',top:(placement?.y??0)+'px',width:(placement?.width??width)+'px',visibility:placement?'visible':'hidden'}"><ReplySurface :text="props.text" :alpha="bubble.alpha.value" :tail-side="side" :tip-y="placement&&ui.settings.value.speech.headAnchored?model.y+model.height*dialogueAnchor(ui.settings.value.speech,String(store.sections.persona?.model_path??'')).mouthY-placement.y:undefined" /></div>
      <BracketMenu :open="island" :viewport="area" :center-x="model.x+model.width/2" :center-y="model.y+model.height*.5" :recording="false" :chat-active="false" theme="light" />
      <div v-if="!placement" class="scene-note">预览区域空间不足，请缩小气泡或偏移。</div>
      </div>
    </div>
    <p class="hint">加载当前角色的真实资源，模型与气泡按同一比例缩放，仅本地演示；不换角色、不发送消息或播放。布局使用同一避让函数；桌面工作区及其他卡片仍会影响最终位置。曲线尖端朝向角色一侧，不穿越模型。</p>
  </template>
</template>
<style scoped>
.scene-controls{display:flex;flex-wrap:wrap;gap:12px;font-size:12px;margin:14px 0}.ui-scene{position:relative;height:460px;width:100%;overflow:hidden;border:1px solid var(--border);border-radius:20px;background:radial-gradient(ellipse at 40% 20%,#c3b3d633,transparent 65%),var(--card-head)}.scene-stage{position:absolute;width:1000px;height:700px;transform-origin:0 0}.scene-model{position:absolute;left:0;top:0;width:40%;height:100%;pointer-events:none}.scene-reply{position:absolute;max-height:420px;overflow:auto}.scene-note{position:absolute;right:12px;bottom:12px;font-size:12px}
</style>
<style scoped>.scene-curve{position:absolute;pointer-events:none;overflow:visible}</style>
