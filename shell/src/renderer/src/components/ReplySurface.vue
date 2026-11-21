<script setup lang="ts">
import { computed,onMounted,onBeforeUnmount,ref } from 'vue'
import { useUiAppearance } from '../composables/useUiAppearance'
import { replyMarkdown } from '../utils/replyMarkdown'
import { mangaBubble } from '../../../shared/mangaBubble'
import CharacterMotif from './CharacterMotif.vue'
const frame=ref<HTMLElement>(),size=ref({width:260,height:140})
let observer:ResizeObserver|undefined
onMounted(()=>{observer=new ResizeObserver(()=>{if(frame.value)size.value={width:frame.value.clientWidth,height:frame.value.clientHeight}});if(frame.value)observer.observe(frame.value)})
onBeforeUnmount(()=>observer?.disconnect())
const shape=computed(()=>mangaBubble(size.value.width,size.value.height,tail.value,ui.settings.value.speech.radius,props.tipY))
const props=defineProps<{text:string;alpha:number;tailSide?:'left'|'right';tipY?:number}>()
const emit=defineEmits<{link:[url:string]}>()
const ui=useUiAppearance()
const style=computed(()=>{
  const s=ui.settings.value.speech,r=s.radius
  const fonts={system:'"Segoe UI","Microsoft YaHei",sans-serif',serif:'"SimSun",serif',hand:'"KaiTi","STKaiti",serif',mono:'Consolas,"Microsoft YaHei",monospace'}
  return {...ui.style('speech'),background:'transparent',borderRadius:s.comic?`${r}px ${r*1.2}px ${r*.9}px ${r*1.1}px / ${r*.6}px ${r*.7}px ${r*.65}px ${r*.75}px`:undefined,fontFamily:fonts[s.font],fontWeight:s.weight,letterSpacing:s.tracking+'px',textAlign:s.align,'--paragraph-gap':s.paragraphGap+'em',color:s.mode==='line'||s.customInk?s.ink:undefined,textShadow:s.mode==='line'?`0 0 ${s.shadowSize}px ${s.shadowColor},0 1px ${s.shadowSize}px ${s.shadowColor}`:undefined}
})
const html=computed(()=>replyMarkdown(props.text))
const tail=computed(()=>ui.settings.value.speech.mode==='bubble'&&ui.settings.value.speech.comic?ui.settings.value.speech.tail:0)
const frameStyle=computed(()=>ui.settings.value.speech.mode==='line'?{}:({paddingLeft:`${(props.tailSide==='right'?0:tail.value)+6}px`,paddingRight:`${(props.tailSide==='right'?tail.value:0)+6}px`,paddingTop:'6px',paddingBottom:'10px',minHeight:tail.value?'112px':undefined}))
function click(e:MouseEvent):void {
  const a=(e.target as Element).closest('a')
  if(!a)return
  e.preventDefault()
  const url=a.getAttribute('href')??''
  if(/^https?:\/\//i.test(url))emit('link',url)
}
</script>
<template><div ref="frame" class="reply-frame" :class="{manga:ui.settings.value.speech.mode==='bubble',ink:ui.settings.value.speech.bubbleStyle==='ink',decorated:ui.settings.value.speech.mode==='bubble'&&ui.settings.value.speech.ornaments}" :style="{...frameStyle,...ui.style('speech')}">
  <svg v-if="ui.settings.value.speech.mode==='bubble'" class="bubble-outline" :class="{'reply-tail':tail,right:tailSide==='right'}" :viewBox="`0 0 ${size.width} ${size.height}`" :style="{opacity:alpha}" aria-hidden="true">
   <path v-if="ui.settings.value.speech.bubbleStyle==='soft'" :d="shape" fill="rgb(var(--panel-rgb))" stroke="rgb(var(--panel-rgb))" stroke-width="6" />
   <path :d="shape" fill="rgb(var(--panel-rgb))" :stroke="ui.settings.value.speech.bubbleStyle==='ink'?'var(--panel-text)':'var(--panel-border)'" :stroke-width="ui.settings.value.speech.bubbleStyle==='ink'?Math.max(2.2,ui.settings.value.speech.border):Math.max(1.3,ui.settings.value.speech.border)" stroke-linejoin="round" />
   <path v-if="ui.settings.value.speech.bubbleStyle==='ink'" :d="`M ${size.width-35} 15 Q ${size.width-18} 16 ${size.width-16} 33`" fill="none" stroke="var(--panel-text)" stroke-width="1.5" stroke-linecap="round" />
  </svg>

  <div class="reply-surface" tabindex="0" role="region" aria-label="角色回复，可用滚轮或方向键查看长内容" :class="{comic:ui.settings.value.speech.comic,line:ui.settings.value.speech.mode==='line'}" :style="{...style,borderWidth:'0'}" @wheel.stop @click="click" v-html="html" />
  <div v-if="ui.settings.value.speech.mode==='bubble'&&ui.settings.value.speech.ornaments" class="reply-footer" aria-hidden="true"><CharacterMotif class="reply-flower" :skin="ui.resolvedSkin.value" :style="{opacity:ui.settings.value.speech.ornamentAlpha}" /></div>
</div></template>
<style scoped>
.reply-frame{position:relative;box-sizing:border-box;width:100%;isolation:isolate;display:flex;flex-direction:column;max-height:min(var(--panel-height),var(--reply-available-height,100000px))}.bubble-outline{position:absolute;inset:0;width:100%;height:100%;pointer-events:none;z-index:-1;overflow:visible}.bubble-outline.right{transform:scaleX(-1)}
.reply-footer{height:34px;flex:0 0 34px;display:flex;justify-content:flex-end;align-items:center;padding-right:14px;pointer-events:none}.reply-flower{width:50px;height:32px;color:var(--panel-accent);--motif-fill:rgb(var(--panel-rgb))}.reply-flower :deep(g){stroke-width:1.6}.reply-surface{position:relative;z-index:1;flex:0 1 auto;min-height:0}.manga .reply-surface{padding:calc(var(--panel-padding) + 6px);padding-right:28px;padding-bottom:calc(var(--panel-padding) + 6px)}
.reply-surface{border:0 solid var(--panel-border)}
.reply-surface{box-sizing:border-box;padding:var(--panel-padding);padding-right:24px;font-size:var(--panel-font);line-height:var(--panel-line);border-radius:var(--panel-radius);color:var(--panel-text);overflow-y:auto;overflow-x:hidden;overscroll-behavior:contain;overflow-wrap:anywhere;scrollbar-width:none;}
.reply-surface::-webkit-scrollbar{display:none}
.reply-surface :deep(> :first-child){margin-top:0}.reply-surface :deep(> :last-child){margin-bottom:0}
.reply-surface.line{border-radius:0;box-shadow:none;outline:none;padding:8px 24px 8px 8px}.reply-surface.line :deep(*){background:transparent;border:0;box-shadow:none;color:inherit}
.reply-surface :deep(p){margin:var(--paragraph-gap,.55em) 0}.reply-surface :deep(h1),.reply-surface :deep(h2),.reply-surface :deep(h3){font-size:1.12em;margin:.7em 0 .3em}
.reply-surface :deep(ul),.reply-surface :deep(ol){padding-left:1.4em;margin:.5em 0}
.reply-surface :deep(pre){white-space:pre-wrap;background:#8882;padding:.6em;border-radius:8px}
.reply-surface :deep(code){font-size:.88em;background:#8882;border-radius:4px;padding:0 .15em}
.reply-surface :deep(blockquote){border-left:3px solid var(--panel-accent);margin:.5em 0;padding-left:.7em;opacity:.85}
.reply-surface :deep(a){color:var(--panel-accent);text-decoration:underline;cursor:pointer}
.reply-surface :deep(table){border-collapse:collapse;font-size:.9em}.reply-surface :deep(td),.reply-surface :deep(th){border:1px solid var(--panel-border);padding:.3em}
</style>
<style>
.result-card,.preview-board,.scene-reply{scrollbar-width:thin;scrollbar-color:transparent transparent}
.result-card:hover,.result-card:focus-within,.preview-board:hover,.scene-reply:hover{scrollbar-color:#b3977366 transparent}
.result-card::-webkit-scrollbar{width:6px;height:6px}
.result-card::-webkit-scrollbar-thumb{background:transparent;border-radius:9px}
.result-card:hover::-webkit-scrollbar-thumb{background:#b3977366}
</style>
