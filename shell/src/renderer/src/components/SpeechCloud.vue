<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { useBubbleFollow } from '../composables/useBubbleFollow'
import { speechBubbleCssVars, useSpeechBubblePref } from '../composables/useSpeechBubblePref'

/**
 * 桌宠回复气泡（Speech Cloud）
 *
 * 呈现桌宠的回复：像漫画角色一样，在**头部的右上侧**浮出一朵对话气泡，
 * 「尖端」朝向模型本人。这是为取代旧「气泡列表堆叠」方案 —— 旧方案把消息一条条往上推，
 * 越堆越高、压住模型的腿脚。
 *
 * 造型沿用项目里聊天气泡（ChatBubble.vue）的既有设计语言：
 *   **不用独立的尾巴元素**，而是把「朝向说话者的那个角」的圆角收小
 *   （assistant 气泡 = 左下角），整个气泡就是一个连续圆角矩形。
 * 这里只是把它等比例放大（字号/内边距/圆角同步放大），并换成白底黑字。
 *
 * 几何约束（改定位前必读）：
 *   模型包围盒 top = cy - h/2 = -0.05h，即**模型顶部在窗口上方之外**，头顶没有空间。
 *   因此气泡不能往正上方摆，只能沿水平方向铺开。
 *
 * 每次只显示当前一条回复：新回复直接替换旧的，读完按字数自动淡出。
 * 位置用 LERP 平滑跟随模型矩形，模型被拖动时会滑过去而不是瞬移。
 *
 * 后续做口型同步（lip sync）时，只需把 visible 绑定到「TTS 播放中」即可。
 */
const props = defineProps<{
  /** 当前回复文本（空串时不可见） */
  text: string
  /** 模型在窗口中的包围盒（client 坐标）；气泡据此定位 */
  rect: { left: number; top: number; width: number; height: number } | null
  visible: boolean
}>()

/* ════════════════════════════════════════════════════════════════
 * ① 位置可调参数（按感官改这里）
 * ════════════════════════════════════════════════════════════════ */

/** 锚点横向位置：模型宽度的几成处。
 *  0.5 = 脸正中；0.7 ≈ 脸右缘；1.0 = 模型右边缘；>1 越出模型右侧。
 *  调小 → 更贴近人物（更易压到头发）；调大 → 更靠右、更分离。 */
const ANCHOR_X_RATIO = 0.72

/** 锚点纵向位置：模型高度的几成处。
 *  0.10 ≈ 眉/眼；0.15 ≈ 鼻尖；0.20 ≈ 下巴；越大越靠下。 */
const ANCHOR_Y_RATIO = 0.14

/*
 * 整体微调（px）不再写死：改由调试台「UI」页的「回复气泡」卡片实时调整，
 * 与歌单卡的左右/上下微调对称 —— 想让气泡换个地方冒出来、避开脸或
 * 让位给别的卡片时用得上。
 */
const { maxWidth, alpha, offsetX, offsetY } = useSpeechBubblePref()

/* ════════════════════════════════════════════════════════════════ */

const anchorX = computed(() => {
  const r = props.rect
  if (!r) return window.innerWidth / 2
  return r.left + r.width * ANCHOR_X_RATIO + offsetX.value
})

const anchorY = computed(() => {
  const r = props.rect
  if (!r) return window.innerHeight * 0.2
  return r.top + r.height * ANCHOR_Y_RATIO + offsetY.value
})

/**
 * 是否真正呈现。
 * 必须同时满足「有可见标记」+「有内容」：文本为空时气泡会退化成只有 padding 的小白块，
 * 悬在锚点（脸侧）位置 —— 这就是「没聊天时脸旁冒出小白点」的原因，两道门都要关。
 */
const active = computed(() => props.visible && props.text.trim().length > 0)

const targetXRef = ref(anchorX.value)
const targetYRef = ref(anchorY.value)

watch(anchorX, (v) => { targetXRef.value = v })
watch(anchorY, (v) => { targetYRef.value = v })

const { currentX, currentY, start, stop } = useBubbleFollow(targetXRef, targetYRef, 0.14)

watch(active, (v) => {
  if (v) start()
  else stop()
}, { immediate: true })

const cloudRef = ref<HTMLDivElement>()
const boxW = ref(0)
const boxH = ref(0)

function measure(): void {
  boxW.value = cloudRef.value?.offsetWidth ?? 0
  boxH.value = cloudRef.value?.offsetHeight ?? 0
}
watch([() => props.text, active], async () => {
  await nextTick()
  measure()
}, { immediate: true })

/** 距窗口边缘的最小留白（px） */
const EDGE = 4

const style = computed(() => {
  const w = boxW.value
  const h = boxH.value
  const winW = window.innerWidth
  const winH = window.innerHeight

  // 水平：气泡从锚点向右铺开（左边缘略越过锚点），并夹紧在窗口内
  const rawLeft = currentX.value - w * 0.08
  const left = Math.min(Math.max(rawLeft, EDGE), Math.max(EDGE, winW - w - EDGE))

  // 垂直：锚点作为气泡的垂直中心；模型顶部在窗口外，这里只做窗口内夹紧
  const rawTop = currentY.value - h / 2
  const top = Math.min(Math.max(rawTop, EDGE), Math.max(EDGE, winH - h - EDGE))

  // 内联 CSS 变量覆盖 <style> 里的默认值，从而让调试台调参实时生效
  return {
    ...speechBubbleCssVars(maxWidth.value, alpha.value),
    left: `${left}px`,
    top: `${top}px`,
  }
})
</script>

<template>
  <!--
    隐藏用 visibility 而非仅 opacity：
    气泡带 backdrop-filter，Chromium 会为它单独建合成层，opacity:0 不足以让它彻底不绘制
    （表现为「没聊天时元素提前闪现」）。visibility:hidden 才是真正取消渲染。
  -->
  <div
    class="speech-wrap"
    :class="{ shown: active }"
    :style="style">
    <div ref="cloudRef" class="speech-cloud">
      <span class="speech-text">{{ text }}</span>
    </div>
  </div>
</template>

<style scoped>
/* ════════════════════════════════════════════════════════════════
 * ② 外观可调参数（按感官改这里）
 *
 * 数值 = ChatBubble 聊天气泡的等比放大：
 *   基准   padding 8/13px · radius 16px · 尖角 6px · font 14px
 *   放大项 padding 10/15px · radius 18px · 尖角 7px · font 15px
 * 改的时候按同比例一起动，造型语言才不会跑偏。
 * ════════════════════════════════════════════════════════════════ */
.speech-wrap {
  /* 底色 / 字色：白底黑字 */
  --cloud-bg: rgba(255, 255, 255, 0.92);
  --cloud-text: #1f1a16;

  /* 圆角：三边一致，只有朝向模型的那一角收小（这就是"尖"） */
  --cloud-radius: 18px;
  --cloud-tip-radius: 7px;   /* 越小越尖；和 --cloud-radius 相同就退化成普通圆角矩形 */

  /* 内边距 / 字号 / 行高 */
  --cloud-pad-y: 10px;
  --cloud-pad-x: 15px;
  --cloud-font: 15px;
  --cloud-line-height: 1.5;

  /* 最大宽度（越小越窄，但文字会换行变高） */
  --cloud-max-w: 190px;

/* ════════════════════════════════════════════════════════════════ */

  position: absolute;
  z-index: 20;
  pointer-events: none;
  will-change: left, top, opacity;
  /* 默认彻底不可见；显示时淡入，隐藏时先淡出再取消渲染 */
  opacity: 0;
  visibility: hidden;
  transition: opacity 220ms var(--ease-out), visibility 0s linear 220ms;
}
.speech-wrap.shown {
  opacity: 1;
  visibility: visible;
  transition: opacity 220ms var(--ease-out), visibility 0s linear 0s;
}

/*
 * 气泡本体：一个完整的圆角矩形，左下角（朝向模型的一侧）圆角收小，
 * 形成指向模型的"尖端"—— 与 ChatBubble 的思路完全一致，不做外挂尾巴。
 */
.speech-cloud {
  max-width: min(42vw, var(--cloud-max-w));
  padding: var(--cloud-pad-y) var(--cloud-pad-x);
  border-radius: var(--cloud-radius) var(--cloud-radius) var(--cloud-radius) var(--cloud-tip-radius);
  background: var(--cloud-bg);
  -webkit-backdrop-filter: blur(10px) saturate(1.1);
  backdrop-filter: blur(10px) saturate(1.1);
  box-shadow: 0 4px 14px rgba(60, 45, 30, 0.18);
  color: var(--cloud-text);
  font-size: var(--cloud-font);
  line-height: var(--cloud-line-height);
  word-break: break-word;
  /* 弹出：像气泡"啵"一下冒出来，锚点在左下（靠近模型） */
  transform-origin: 6% 100%;
  transition: transform 220ms var(--ease-out);
}
.speech-wrap:not(.shown) .speech-cloud { transform: scale(0.88); }
.speech-wrap.shown .speech-cloud { transform: scale(1); }

.speech-text { display: inline; }
</style>
