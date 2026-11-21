<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import type { ClientPlayback } from '../../../shared/detachedUi'
import { useUiAppearance } from '../composables/useUiAppearance'
import {
  resultCardCssVars,
  useResultCardPref,
  type ResultCardItem,
  type ResultCardSide,
} from '../composables/useResultCardPref'

/**
 * 桌宠「结果卡」—— 歌单雷达 / 搜索候选 / 歌曲列表的可视化卡片。
 *
 * 这些列表原本只躺在工具返回的 JSON 里，屏幕上什么都不显示，
 * 用户只能听到一句"已经推荐了"，无从知道具体推荐了什么；现在渲染成一张
 * 可点选的卡片（点一下 = 播放这一条）。
 *
 * 定位基准与 SpeechCloud（回复气泡）对称：
 *   回复气泡 —— 模型头部**右侧**（锚点 0.72），从锚点向右铺开；
 *   结果卡   —— 模型头部**左侧**（锚点 0.28 = 0.72 的镜像），从锚点向左铺开。
 * 两者共用同一纵向锚点（0.14 ≈ 眉眼高度），于是分居头部左右、同一高度带，
 * 都贴在模型躯干之外 → 不遮挡模型，且左右留白平衡。
 *
 * 位置与尺寸都可在调试台「UI」页实时调（useResultCardPref，跨窗口共享）。
 */
const props = defineProps<{
  /** 卡片标题（如"歌单雷达"） */
  title: string
  /** 条目列表 */
  items: ResultCardItem[]
  /** 模型在窗口中的包围盒（client 坐标）；卡片据此定位 */
  rect: { left: number; top: number; width: number; height: number } | null
  /** S51：卡片类型 —— `source` 表示联网检索来源（渲染成"标题 + 域名"，点击打开浏览器） */
  kind?: string
  detached?: boolean
  playback?: ClientPlayback | null
  busy?: boolean
}>()

const emit = defineEmits<{ pick: [item: ResultCardItem]; official: [item: ResultCardItem]; client:[item:ResultCardItem]; control:[action:'pause'|'resume'|'like'|'unlike'] }>()

/* ════════════════════════════════════════════════════════════════
 * ① 位置锚点（与 SpeechCloud 刻意保持镜像关系，改一边记得看另一边）
 * ════════════════════════════════════════════════════════════════ */

/** 锚点横向位置：模型宽度的几成处。右侧 0.72 = 回复气泡的锚点。 */
const ANCHOR_X: Record<ResultCardSide, number> = { left: 0.28, right: 0.72 }

/** 锚点纵向位置：与回复气泡同一高度带（0.14 ≈ 眉/眼高度）。 */
const ANCHOR_Y = 0.14

/** 距窗口边缘的最小留白（px） */
const EDGE = 6

/* ════════════════════════════════════════════════════════════════ */

// 外观偏好（左右 / 微调 / 宽度 / 不透明度）来自调试台「UI」页，跨窗口共享
const { side, offsetX, offsetY, maxWidth, alpha } = useResultCardPref()
const ui=useUiAppearance()
const randomCandidates=computed(()=>props.kind==='song'?props.items.filter(it=>/^[1-9]\d{0,19}$/.test(String(it.song_id??''))):[])
function randomPick():void {
  if(props.busy||!randomCandidates.value.length)return
  emit('client',randomCandidates.value[Math.floor(Math.random()*randomCandidates.value.length)])
}

const anchorX = computed(() => {
  const r = props.rect
  if (!r) return window.innerWidth / 2
  return r.left + r.width * ANCHOR_X[side.value] + offsetX.value
})

const anchorY = computed(() => {
  const r = props.rect
  if (!r) return window.innerHeight * 0.2
  return r.top + r.height * ANCHOR_Y + offsetY.value
})

const cardRef = ref<HTMLDivElement>()
const boxW = ref(0)
const boxH = ref(0)
/** 量到真实尺寸后才淡入 —— 否则首帧会用 0 尺寸定位，卡片先闪一下再跳位 */
const measured = ref(false)

async function measure(): Promise<void> {
  await nextTick()
  boxW.value = cardRef.value?.offsetWidth ?? 0
  boxH.value = cardRef.value?.offsetHeight ?? 0
  measured.value = true
}

watch([() => props.items, () => side.value, () => maxWidth.value], measure, { immediate: true })

const style = computed(() => {
  const appearance={...ui.style(props.kind==='source'?'source':'music'),...resultCardCssVars(maxWidth.value,alpha.value),'--rc-bg':`rgba(var(--panel-rgb), ${alpha.value})`}
  if(props.detached)return { ...appearance, position:'relative' as const,left:'0',top:'0',maxWidth:'none',width:'100%',maxHeight:'var(--panel-height)',boxShadow:'none',paddingRight:'24px' }
  const w = boxW.value
  const h = boxH.value
  const winW = window.innerWidth
  const winH = window.innerHeight
  if (!measured.value || !w || !h) return { visibility: 'hidden' as const }

  // 横向：默认贴模型左侧、从锚点向左铺开（镜像 SpeechCloud 的「向右铺开」）
  const rawLeft = side.value === 'left'
    ? anchorX.value - w * 0.92
    : anchorX.value - w * 0.08
  const left = Math.min(Math.max(rawLeft, EDGE), Math.max(EDGE, winW - w - EDGE))

  // 纵向：锚点作为卡片垂直中心（与回复气泡同高），只做窗口内夹紧
  const rawTop = anchorY.value - h / 2
  const top = Math.min(Math.max(rawTop, EDGE), Math.max(EDGE, winH - h - EDGE))

  // 内联 CSS 变量覆盖 <style> 里的默认值，从而让调试台调参实时生效
  return {
    ...appearance,
    left: `${left}px`,
    top: `${top}px`,
  }
})

/** 朝向模型那一侧的圆角收小，形成指向模型的"尖端"（左侧卡片 → 右下角） */
const tipRight = computed(() => side.value === 'left')

/**
 * S51：来源卡展示**域名**而非完整 URL —— 用户靠域名判断可信度，
 * 一长串带 query 的链接反而看不清。完整链接在点击时交给系统浏览器。
 */
function hostOf(url?: string): string {
  try {
    return new URL(String(url ?? '')).host
  } catch {
    return String(url ?? '')
  }
}
</script>

<template>
  <div
    ref="cardRef"
    class="result-card"
    :class="{ 'tip-right': tipRight }"
    :style="style">
    <div class="rc-head">{{ title }}</div>
    <div v-if="items.some(it=>it.source==='netease_client_ui')" class="rc-rights">来自网易云客户端内搜索</div>
    <div v-if="items.some(it=>it.source==='netease_client_daily')" class="rc-rights">网易云客户端日推 · 随机抽样，点选后播放</div>
    <div v-if="playback" class="rc-playback">
      <span>网易云客户端 · {{ playback.name }}</span>
      <span class="rc-playback-status">{{ playback.status==='playing'?'播放中':'已暂停' }}</span>
      <button class="rc-official rc-control" :disabled="busy" @click.stop="emit('control',playback.status==='playing'?'pause':'resume')">{{ playback.status==='playing'?'暂停':'继续' }}</button>
      <button v-if="typeof playback.liked==='boolean'" class="rc-official rc-favorite" :disabled="busy" :aria-pressed="playback.liked" @click.stop="emit('control',playback.liked?'unlike':'like')">{{playback.liked?'取消喜欢':'喜欢'}}</button>
    </div>
    <div v-if="busy" class="rc-rights" role="status">正在等待网易云状态确认，请勿重复操作…</div>
    <button v-if="randomCandidates.length>1" class="rc-official rc-random" :disabled="busy" @click.stop="randomPick">从这些候选中随机播放</button>
    <ul class="rc-list">
      <!-- 条目可点 —— 点一下等于说"播放这个"，省掉用户复述名字 -->
      <li
        v-for="(it, i) in items"
        :key="i"
        class="rc-item"
        :class="{ 'rc-source': kind === 'source' }"
        :role="kind === 'source' ? 'link' : 'button'"
        tabindex="0"
        @keydown.enter="emit('pick', it)"
        @click="emit('pick', it)">
        <!-- S51：来源卡 —— 标题 + 域名（点开由父组件交给系统浏览器） -->
        <template v-if="kind === 'source'">
          <span class="rc-name">{{ it.title || it.url }}</span>
          <span class="rc-sub">{{ hostOf(it.url) }}</span>
          <span v-if="it.snippet" class="rc-snippet">{{ it.snippet }}</span>
          <time v-if="ui.settings.value.source.showDate" class="rc-date" :datetime="it.published_at || undefined">{{ it.published_at ? it.published_at.slice(0, 10) : '发布时间未知' }}</time>
        </template>
        <template v-else>
          <div class="rc-song">
            <span class="rc-name">{{ it.name }}</span>
            <span class="rc-sub">{{ it.artist || (it.track_count ? it.track_count + ' 首' : '') }}</span>
            <span v-if="it.song_id&&ui.settings.value.results.showAvailableNote" class="rc-rights">由网易云客户端按当前账号权益播放</span>
            <div v-if="it.song_id && kind!=='playlist'" class="rc-players" :class="{stacked:ui.settings.value.results.stackPlayers}">
              <button class="rc-official rc-client" :disabled="busy" @click.stop="emit('client',it)" @keydown.enter.stop>网易云播放</button>
            </div>
            <button v-if="it.song_id&&ui.settings.value.results.showOfficialPage" class="rc-official" @click.stop="emit('official', it)" @keydown.enter.stop.prevent="emit('official', it)">打开官方歌曲页</button>
          </div>
        </template>
      </li>
    </ul>
  </div>
</template>

<style scoped>
.rc-players { display:flex;flex-wrap:wrap;gap:4px; }
.rc-players.stacked{flex-direction:column}.rc-players.stacked button{align-self:stretch;text-align:left}
.rc-playback { display:flex;flex-direction:column;gap:6px;padding:8px 10px;border-bottom:1px solid var(--panel-border,#dbc9aa);font-size:1em; }
.rc-playback-status { white-space:nowrap; }
.rc-official:disabled { opacity:.5;cursor:wait; }
.rc-source { flex-direction: column; align-items: stretch !important; gap: 4px !important; padding: 8px 6px !important; }
.rc-source .rc-name { white-space: normal; font-weight: 600; }
.rc-snippet { font-size: 1em; line-height: inherit; display: -webkit-box; -webkit-line-clamp: var(--source-lines,3); -webkit-box-orient: vertical; overflow: hidden; }
.rc-date { font-size: .92em; opacity: 0.65; }
.rc-song { display:flex;flex-direction:column;gap:4px;min-width:0;width:100%; }
.rc-song .rc-name { white-space:normal; }
.rc-rights { font-size:.92em;line-height:1.4;opacity:.75; }
.rc-official { align-self:flex-start;border:1px solid var(--panel-border,#cbb78e);border-radius:8px;background:transparent;color:var(--panel-accent,#8a5a12);cursor:pointer;font:inherit;padding:3px 6px; }
/*
 * 造型与回复气泡（SpeechCloud）同一套语言：奶白半透 + 毛玻璃 + 大圆角，
 * 只是把「朝向模型的那一角」收小当作尖端，左右镜像。
 */
.result-card {
  --rc-bg: rgba(255, 255, 255, 0.92);
  --rc-text: #1f1a16;
  --rc-max-w: 224px;

  /* 三边一致，只有朝模型那一角收小（--rc-tip-radius） */
  --rc-radius: 16px;
  --rc-tip-radius: 7px;

  position: absolute;
  z-index: 20;
  /* 平时不挡模型、不吃鼠标事件；自身可点选，故这里是 auto */
  pointer-events: auto;
  max-width: min(46vw, var(--rc-max-w));
  max-height: 46vh;
  overflow-y: auto;
  box-sizing:border-box;
  padding: var(--panel-padding,12px);
  border-radius: var(--panel-radius,16px);
  background: var(--rc-bg);
  -webkit-backdrop-filter: blur(10px) saturate(1.1);
  backdrop-filter: blur(10px) saturate(1.1);
  box-shadow: 0 4px 14px rgba(60, 45, 30, 0.18);
  color: var(--panel-text,var(--rc-text));
  font-size: var(--panel-font,12px);
  line-height: var(--panel-line,1.5);
  will-change: left, top, opacity;
  animation: rc-in 200ms var(--ease-out);
}

/* 尖端：朝向模型的那一角（左侧卡片 → 右下角） */
.result-card.tip-right {
  border-radius: var(--panel-radius,16px);
}

@keyframes rc-in {
  from { opacity: 0; transform: scale(0.94); }
  to { opacity: 1; transform: scale(1); }
}

.rc-head {
  margin-bottom: 5px;
  font-weight: 600;
  color: var(--panel-accent,#8a5a12);
}

.rc-list { margin: 0; padding: 0; list-style: none; }

.rc-item {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  gap: 10px;
  padding: var(--panel-row,6px) 6px;
  border-radius: var(--radius-sm);
  cursor: pointer;
  transition: background var(--dur-fast) var(--ease-out);
}
.rc-item:hover { background: rgba(224, 154, 62, 0.16); }
.rc-item:active { background: rgba(224, 154, 62, 0.3); }

.rc-name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.rc-sub {
  flex-shrink: 0;
  font-size: .92em;
  opacity: 0.6;
}
</style>
