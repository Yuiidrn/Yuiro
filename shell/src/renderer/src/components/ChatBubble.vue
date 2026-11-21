<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { animate } from 'animejs'

const props = defineProps<{
  text: string
  role: 'user' | 'assistant'
  index: number
  isNew: boolean
}>()

const emit = defineEmits<{
  (e: 'animdone', index: number): void
}>()

const el = ref<HTMLDivElement>()
const animating = ref(false)

const bubbleClass = computed(() => ({
  'c-bubble': true,
  [`role-${props.role}`]: true,
  'is-new': props.isNew && animating.value,
}))

// 按 grapheme 切分（Intl.Segmenter，正确处理 emoji/组合字符）——
// airi PoppinText 模式：逐字错峰弹出，营造打字感。
const chars = computed<string[]>(() => {
  const seg = new Intl.Segmenter(undefined, { granularity: 'grapheme' })
  return Array.from(seg.segment(props.text), (s) => s.segment)
})

/**
 * 入场动画（airi 两阶段 + PoppinText 逐字）：
 * 1. 边框缩放入场（scale 0.85→1, opacity 0→1, 120ms）
 * 2. 逐字 fade/popup（每字 translateY(3px)→0 + opacity 0→1，18ms 错峰，总时长封顶）
 */
async function playEnterAnimation(): Promise<void> {
  if (!el.value || !props.isNew) return
  animating.value = true
  await nextTick()

  const bubble = el.value
  await animate(bubble, {
    scale: [0.85, 1],
    opacity: [0, 1],
    duration: 120,
    easing: 'easeOutCubic',
  })

  // 逐字弹出：错峰 delay，总时长随字数增长但有上限
  const charEls = Array.from(el.value.querySelectorAll('.c-char'))
  const per = 18
  const maxDelay = 900
  const capped = Math.min(charEls.length * per, maxDelay)
  await Promise.all(charEls.map((ch, i) =>
    animate(ch, {
      opacity: [0, 1],
      translateY: [3, 0],
      duration: 220,
      easing: 'easeOutQuad',
      delay: Math.min(i * per, capped),
    }),
  ))

  animating.value = false
  emit('animdone', props.index)
}

onMounted(() => {
  if (props.isNew) playEnterAnimation()
})

watch(() => props.isNew, (val) => {
  if (val) playEnterAnimation()
})
</script>

<template>
  <div ref="el" :class="bubbleClass">
    <span class="c-bubble-text">
      <span v-for="(ch, i) in chars" :key="i" class="c-char">{{ ch }}</span>
    </span>
  </div>
</template>

<style scoped>
/*
 * 聊天气泡：米白 / 米黄奶油。
 * 透明度按「不挡住桌宠模型」为基准 —— 半透 + 背景模糊，
 * 气泡压在模型上时仍能看清轮廓，不做成实心色块。
 */
.c-bubble {
  padding: 8px 13px;
  border-radius: 16px;
  font-size: var(--text-sm);
  line-height: 1.55;
  max-width: 86%;
  word-break: break-word;
  will-change: transform, opacity;
  -webkit-backdrop-filter: blur(10px);
  backdrop-filter: blur(10px);
  box-shadow: 0 2px 10px rgba(120, 95, 60, 0.10);
  border: 1px solid transparent;
}
.c-bubble.is-new {
  opacity: 0;
  transform: scale(0.85);
}

/* 用户消息：暖琥珀，右下角收口（气泡指向发送者） */
.c-bubble.role-user {
  align-self: flex-end;
  background: var(--msg-user-bg);
  color: var(--msg-user-text);
  border-bottom-right-radius: 6px;
  border-color: color-mix(in srgb, var(--msg-user-bg) 70%, transparent);
}

/* 助理消息：米白，左下角收口 */
.c-bubble.role-assistant {
  align-self: flex-start;
  background: var(--msg-assistant-bg);
  color: var(--msg-assistant-text);
  border-bottom-left-radius: 6px;
  border-color: var(--chat-border);
}

.c-bubble-text {
  display: inline;
}
.c-char {
  display: inline-block;
  will-change: opacity, transform;
}
.c-bubble.is-new .c-char {
  opacity: 0;
}
</style>

