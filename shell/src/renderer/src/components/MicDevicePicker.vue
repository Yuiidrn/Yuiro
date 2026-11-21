<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { Icon } from '@iconify/vue'
import { useAudioDevices } from '../composables/useAudioDevices'

/**
 * 录音设备选择器 —— **所有语音入口共用这一个组件**（桌宠聊天坞 / 日记窗口 / 调试台语音联调）。
 *
 * 三条刻意的设计：
 *   1. **打开面板时才探测权限**：要读到设备真名必须先拿一次麦克风权限，而拿权限会点亮
 *      系统指示灯。所以探测只发生在用户主动点开列表的那一刻，不在挂载时静默开麦。
 *   2. **不用图标库图标**，只用 `▾ / ✓ / ↻` 这几个字符：本地图标集里图标名写错
 *      不会报错、只是空白（这个坑踩过），而这里的可读性不该赌。
 *   3. **选择是全局的**：走 `useAudioDevices` 的单例 + localStorage，
 *      所以"在日记窗口换了麦，聊天坞会跟着换"（BroadcastChannel 同步）。
 */
const props = defineProps<{
  /** 前缀文案，如"输入" —— 留空则只显示设备名。 */
  label?: string
  /** 窄容器用：隐藏前缀，只留设备名与箭头。 */
  compact?: boolean
  /**
   * 极紧凑形态：只留「麦克风图标 + ▾」，连设备名都收起（用于聊天坞输入胶囊）。
   *
   * 为什么需要它：语音入口的**切换控件必须常驻在按钮旁边**。此前聊天坞只在
   * "录音展开区"里放设备选择 —— 而那块只在**开麦之后**才出现，想换麦时它还没出现，
   * 等于没有（用户实测反馈："聊天框的语音按钮没有看到设备切换"）。
   * 当前设备名在 `title` 与弹出面板里给到。
   */
  bare?: boolean
  disabled?: boolean
}>()

const emit = defineEmits<{ (e: 'changed', id: string): void }>()

const { devices, selectedId, ready, probing, error, refresh, select, currentLabel, listen } =
  useAudioDevices()
listen()

const open = ref(false)
const root = ref<HTMLElement | null>(null)

const caption = computed(() => (probing.value ? '检测中…' : currentLabel()))

async function toggle(): Promise<void> {
  if (props.disabled) return
  open.value = !open.value
  // 只在打开时探测：拿权限 → 解锁设备名（采样完立刻释放，不在这里开始录音）
  if (open.value) await refresh(true)
}

function pick(id: string): void {
  select(id)
  emit('changed', id)
  open.value = false
}

/** 点面板外面关掉（mousedown 比 click 更早，避免与按钮的 click 打架）。 */
function onDocDown(ev: MouseEvent): void {
  if (root.value && !root.value.contains(ev.target as Node)) open.value = false
}

watch(open, (v) => {
  if (v) document.addEventListener('mousedown', onDocDown)
  else document.removeEventListener('mousedown', onDocDown)
})
onBeforeUnmount(() => document.removeEventListener('mousedown', onDocDown))
</script>

<template>
  <div ref="root" class="mdev" :class="{ open, compact, bare }">
    <!-- bare：输入胶囊里塞不下设备名，只留图标 + 箭头（当前设备名见 title / 面板）。
         ⚠ 图标**不能再用麦克风** —— 它紧挨着语音开关（也是麦克风图标），两个同款图标
         并排会让人分不清哪个是开关、哪个是选择。这里用「竖直滑块」表达"可调 / 可选"，
         与"开关"形成分工。 -->
    <button
      v-if="bare"
      class="mdev-btn"
      :disabled="disabled"
      :title="`录音设备：${caption}（点击切换）`"
      @click="toggle">
      <Icon icon="solar:slider-vertical-bold" width="14" />
      <span class="mdev-caret">▾</span>
    </button>
    <button
      v-else
      class="mdev-btn"
      :disabled="disabled"
      :title="`录音设备：${caption}（点击切换）`"
      @click="toggle">
      <span class="mdev-name">
        <span v-if="label && !compact" class="mdev-prefix">{{ label }}：</span>{{ caption }}
      </span>
      <span class="mdev-caret">▾</span>
    </button>

    <div v-if="open" class="mdev-pop">
      <div class="mdev-head">
        <span>录音设备</span>
        <button class="mdev-refresh" :disabled="probing" title="重新检测" @click="refresh(true)">
          ↻
        </button>
      </div>

      <ul class="mdev-list">
        <li class="mdev-item" :class="{ on: !selectedId }" @click="pick('')">
          <span class="mdev-tick">{{ !selectedId ? '✓' : '' }}</span>
          <span class="mdev-item-name">系统默认</span>
        </li>
        <li
          v-for="d in devices"
          :key="d.id"
          class="mdev-item"
          :class="{ on: selectedId === d.id }"
          @click="pick(d.id)">
          <span class="mdev-tick">{{ selectedId === d.id ? '✓' : '' }}</span>
          <span class="mdev-item-name">{{ d.label }}</span>
        </li>
      </ul>

      <p v-if="probing" class="mdev-note">正在检测设备…</p>
      <p v-else-if="!devices.length" class="mdev-note">没有检测到麦克风设备</p>
      <p v-else-if="!ready" class="mdev-note">
        设备名需要在获得一次麦克风权限后才能读取，点 ↻ 重试。
      </p>
      <p v-if="error" class="mdev-err">{{ error }}</p>
    </div>
  </div>
</template>

<style scoped>
.mdev { position: relative; display: inline-block; max-width: 100%; }

.mdev-btn {
  display: inline-flex; align-items: center; gap: 5px;
  max-width: 100%; padding: 4px 9px; border-radius: 7px; cursor: pointer;
  font-size: 11.5px; font-family: inherit;
  background: rgba(148, 163, 184, 0.12); color: inherit;
  border: 1px solid rgba(148, 163, 184, 0.3);
  transition: background 160ms ease, border-color 160ms ease;
}
.mdev-btn:hover:not(:disabled) { background: rgba(148, 163, 184, 0.2); }
.mdev-btn:disabled { opacity: 0.45; cursor: default; }
.mdev.open .mdev-btn { border-color: rgba(148, 163, 184, 0.6); }
.mdev-prefix { opacity: 0.7; }
.mdev-name {
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 190px;
}
.mdev.compact .mdev-name { max-width: 120px; }
.mdev-caret { opacity: 0.6; font-size: 10px; }
/* bare：只是"图标 + ▾"，不显示设备名 */
.mdev.bare .mdev-btn { padding: 4px 6px; gap: 3px; }

.mdev-pop {
  position: absolute; z-index: 40; left: 0; bottom: calc(100% + 6px);
  min-width: 220px; max-width: 320px; padding: 8px;
  border-radius: 10px;
  background: rgba(28, 26, 24, 0.97);
  border: 1px solid rgba(148, 163, 184, 0.28);
  box-shadow: 0 12px 28px rgba(0, 0, 0, 0.4);
  color: #e8e2d8; font-size: 12px;
}
.mdev-head {
  display: flex; align-items: center; justify-content: space-between;
  padding: 0 4px 6px; color: #a9a29a; font-size: 11px;
}
.mdev-refresh {
  border: none; background: transparent; cursor: pointer; color: inherit;
  font-size: 13px; line-height: 1; padding: 2px 4px; border-radius: 5px;
}
.mdev-refresh:hover:not(:disabled) { background: rgba(148, 163, 184, 0.18); }
.mdev-refresh:disabled { opacity: 0.4; cursor: default; }

.mdev-list { list-style: none; margin: 0; padding: 0; max-height: 190px; overflow-y: auto; }
.mdev-item {
  display: flex; align-items: center; gap: 6px;
  padding: 6px 7px; border-radius: 7px; cursor: pointer;
}
.mdev-item:hover { background: rgba(148, 163, 184, 0.16); }
.mdev-item.on { background: rgba(148, 163, 184, 0.22); }
.mdev-tick { width: 12px; flex-shrink: 0; color: #8fc79a; font-size: 11px; }
.mdev-item-name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.mdev-note { margin: 6px 4px 0; color: #a9a29a; font-size: 11px; line-height: 1.6; }
.mdev-err { margin: 6px 4px 0; color: #e0a0a0; font-size: 11px; line-height: 1.6; }
</style>
