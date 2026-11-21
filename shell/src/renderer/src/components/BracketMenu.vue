<script setup lang="ts">
/**
 * 括号功能岛：悬停模型时，功能图标从模型中心由内向外弹出，
 * 左右两列呈 "(" ")" 括号状围绕模型（左列对话类 / 右列系统类）。
 * 图标全部落在窗口两侧的交互余量内，绝不遮挡模型本体。
 */
import { nextTick, ref, watch } from 'vue'
import { animate } from 'animejs'
import { Icon } from '@iconify/vue'
import { useUiAppearance } from '../composables/useUiAppearance'
const ui=useUiAppearance()

interface BracketItem {
  id: string
  icon: string
  title: string
  side: 'left' | 'right'
}

const ITEMS: BracketItem[] = [
  { id: 'chat', icon: 'solar:chat-round-dots-bold', title: '聊天', side: 'left' },
  { id: 'voice', icon: 'solar:microphone-3-bold', title: '语音', side: 'left' },
  { id: 'settings', icon: 'solar:settings-bold', title: '设置', side: 'right' },
  // S51：日记取代原「日志」入口（日志仍在调试台「日志」页 —— 它是排查工具，
  // 不该占功能岛的日常席位；日记是日常功能，放在右列中间最好点）。
  { id: 'diary', icon: 'solar:notebook-bold', title: '日记', side: 'right' },
  { id: 'theme', icon: 'solar:sun-bold', title: '主题', side: 'right' },
]

const props = defineProps<{
  open: boolean
  centerX: number // 模型中心（窗口坐标），图标弹出/缩回的原点
  centerY: number
  recording: boolean
  chatActive: boolean
  theme: string
  viewport?:{width:number;height:number}
}>()
const emit = defineEmits<{ (e: 'action', id: string): void }>()

const render = ref(false)
const rootRef = ref<HTMLElement>()
let anims: Array<{ cancel?: () => void }> = []

const leftItems = ITEMS.filter((i) => i.side === 'left')
const rightItems = ITEMS.filter((i) => i.side === 'right')

function slotOffset(index: number, count: number): number {
  return (index - (count - 1) / 2) * Math.max(ui.settings.value.island.gap,ui.settings.value.island.size+4)
}

function iconOf(item: BracketItem): string {
  if (item.id === 'theme') return props.theme === 'light' ? 'solar:sun-bold' : 'solar:moon-bold'
  return item.icon
}

function styleOf(item: BracketItem): Record<string, string> {
  const list = item.side === 'left' ? leftItems : rightItems
  const p=ui.settings.value.island,size=p.size
  const top = props.centerY+p.offsetY + slotOffset(list.indexOf(item), list.length) - size / 2
  const base = { top: `${top}px` }
  // 以模型中心为原点，水平偏移 MODEL_GAP 环抱模型（而非钉在窗口边）
  const x = props.centerX + (item.side === 'left' ? -p.distance-size : p.distance)
  return { ...base, left: `${Math.max(4,Math.min((props.viewport?.width??innerWidth)-size-4,x))}px`,top:`${Math.max(4,Math.min((props.viewport?.height??innerHeight)-size-4,top))}px`,width:size+'px',height:size+'px',borderRadius:p.radius+'%',background:`rgba(${ui.resolvedSkin.value==='lily'?(props.theme==='dark'?'36,45,52':'255,255,255'):'12,12,16'},${p.alpha})`,color:ui.resolvedSkin.value==='lily'?(props.theme==='dark'?'#edf4f1':'#506e62'):'#ffffff' }
}

function cancelAll(): void {
  for (const a of anims) {
    try { a?.cancel?.() } catch { /* ignore */ }
  }
  anims = []
}

async function playIn(): Promise<void> {
  await nextTick()
  const els = Array.from(rootRef.value?.querySelectorAll<HTMLElement>('.bm-icon') ?? [])
  anims = els.map((el, i) => {
    const r = el.getBoundingClientRect()
    const dx = props.centerX - (r.left + r.width / 2)
    const dy = props.centerY - (r.top + r.height / 2)
    return animate(el, {
      translateX: [dx, 0],
      translateY: [dy, 0],
      scale: [0.2, 1],
      opacity: [0, 1],
      duration: ui.settings.value.island.duration,
      easing: 'easeOutBack',
      delay: i * 35,
    })
  })
}

async function playOut(): Promise<void> {
  const els = Array.from(rootRef.value?.querySelectorAll<HTMLElement>('.bm-icon') ?? [])
  if (els.length === 0) return
  const jobs = els.map((el, i) => {
    const r = el.getBoundingClientRect()
    const dx = props.centerX - (r.left + r.width / 2)
    const dy = props.centerY - (r.top + r.height / 2)
    // 缩回顺序与弹出相反（外侧先回），营造"收回中心"的吸附感
    return animate(el, {
      translateX: [0, dx],
      translateY: [0, dy],
      scale: [1, 0.2],
      opacity: [1, 0],
      duration: ui.settings.value.island.duration*.68,
      easing: 'easeInQuad',
      delay: (els.length - 1 - i) * 22,
    })
  })
  anims = jobs
  await Promise.all(jobs)
}

let animationRevision=0
watch(() => props.open, async (v) => {
  const revision=++animationRevision
  cancelAll()
  if (v) {
    render.value = true
    await nextTick()
    if(revision===animationRevision)await playIn()
  } else {
    await playOut()
    if(revision===animationRevision)render.value = false
  }
},{immediate:true})
</script>

<template>
  <div v-if="render" ref="rootRef" class="bracket-menu">
    <button
      v-for="item in ITEMS"
      :key="item.id"
      class="bm-icon"
      :class="[
        item.side,
        {
          recording: item.id === 'voice' && recording,
          active: item.id === 'chat' && chatActive,
        },
      ]"
      :style="styleOf(item)"
      :title="item.title"
      @click.stop="emit('action', item.id)"
    >
      <Icon :icon="iconOf(item)" width="20" />
    </button>
  </div>
</template>

<style scoped>
.bracket-menu {
  position: absolute;
  inset: 0;
  z-index: 45;
  pointer-events: none;
}
.bm-icon {
  position: absolute;
  width: 44px;
  height: 44px;
  border-radius: var(--radius-full);
  background: rgba(12, 12, 16, 0.66);
  -webkit-backdrop-filter: blur(14px) saturate(1.2);
  backdrop-filter: blur(14px) saturate(1.2);
  border: 1px solid rgba(148, 163, 184, 0.25);
  color: #fff;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  pointer-events: auto;
  box-shadow: var(--shadow-float);
  opacity: 0;
  transition: background var(--dur-fast) var(--ease-out),
    border-color var(--dur-fast) var(--ease-out);
  -webkit-app-region: no-drag;
}
.bm-icon:hover {
  background: var(--cbtn-hover);
  border-color: var(--btn-active-border);
}
.bm-icon.active {
  background: var(--cbtn-active);
}
.bm-icon.recording {
  background: var(--rec-color);
  animation: bm-pulse-rec 1.2s ease-in-out infinite;
}
@keyframes bm-pulse-rec {
  0%, 100% { box-shadow: 0 0 0 0 var(--rec-color); }
  50% { box-shadow: 0 0 0 6px transparent; }
}
</style>
