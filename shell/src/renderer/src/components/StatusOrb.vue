<script setup lang="ts">
/**
 * 连接状态泡：纯指示器（无点击交互）。
 * 沉在模型脚下居中，呼吸脉冲；录音时变为红色急促脉冲。
 */
defineProps<{
  status: string // 'ok' | 'off' | 'err'
  recording: boolean
  x: number // 模型区中心 x（窗口坐标）
}>()
</script>

<template>
  <div class="status-orb" :class="[status, { recording }]" :style="{ left: `${x}px` }">
    <span class="orb-core"></span>
  </div>
</template>

<style scoped>
.status-orb {
  position: absolute;
  bottom: 14px;
  transform: translateX(-50%);
  width: 14px;
  height: 14px;
  display: flex;
  align-items: center;
  justify-content: center;
  pointer-events: none;
  z-index: 40;
  transition: left var(--dur-med) var(--ease-out);
}
.orb-core {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: var(--dot-off);
  box-shadow: 0 0 8px 2px color-mix(in srgb, var(--dot-off) 45%, transparent);
  animation: orb-breathe 2.4s ease-in-out infinite;
  transition: background var(--dur-med), box-shadow var(--dur-med);
}
.status-orb.ok .orb-core {
  background: var(--dot-ok);
  box-shadow: 0 0 10px 3px color-mix(in srgb, var(--dot-ok) 55%, transparent);
}
.status-orb.err .orb-core {
  background: var(--dot-err);
  box-shadow: 0 0 10px 3px color-mix(in srgb, var(--dot-err) 55%, transparent);
}
.status-orb.recording .orb-core {
  background: var(--rec-color);
  box-shadow: 0 0 12px 4px color-mix(in srgb, var(--rec-color) 60%, transparent);
  animation-duration: 1s;
}
@keyframes orb-breathe {
  0%, 100% { transform: scale(1); opacity: 1; }
  50% { transform: scale(0.78); opacity: 0.7; }
}
</style>
