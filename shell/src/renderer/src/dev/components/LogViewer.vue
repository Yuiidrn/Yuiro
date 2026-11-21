<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useLogStore } from '../stores/logs'
import type { LogEntry } from '@shared'

const store = useLogStore()

const sources = ['', 'engine', 'chat', 'config', 'test', 'systemd', 'shell']
const levels = ['', 'DEBUG', 'INFO', 'WARNING', 'ERROR']

const listEl = ref<HTMLDivElement>()
const follow = ref(true)
const autoScroll = ref(true)

let timer: ReturnType<typeof setInterval> | null = null

function levelClass(level: string): string {
  switch (level) {
    case 'ERROR': return 'lv-error'
    case 'WARNING': return 'lv-warn'
    case 'DEBUG': return 'lv-debug'
    default: return 'lv-info'
  }
}

function fmtTime(ts: number): string {
  const d = new Date(ts * 1000)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
}

function onUserScroll(): void {
  if (!listEl.value) return
  const el = listEl.value
  const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 40
  if (!nearBottom) autoScroll.value = false
  else autoScroll.value = true
}

function scrollToBottom(): void {
  if (!listEl.value) return
  listEl.value.scrollTop = listEl.value.scrollHeight
}

async function tick(): Promise<void> {
  if (store.paused) return
  await store.refresh()
  if (autoScroll.value) requestAnimationFrame(scrollToBottom)
}

async function toggleFollow(): Promise<void> {
  autoScroll.value = !autoScroll.value
  follow.value = autoScroll.value
  if (autoScroll.value) scrollToBottom()
}

async function togglePause(): Promise<void> {
  store.paused = !store.paused
}

onMounted(() => {
  tick()
  timer = setInterval(tick, 2000)
})

onBeforeUnmount(() => {
  if (timer) clearInterval(timer)
})
</script>

<template>
  <div class="log-viewer">
    <div class="lv-toolbar">
      <select v-model="store.source" class="sel">
        <option v-for="s in sources" :key="s" :value="s">{{ s || '全部来源' }}</option>
      </select>
      <select v-model="store.level" class="sel">
        <option v-for="l in levels" :key="l" :value="l">{{ l || '全部级别' }}</option>
      </select>

      <button class="btn" :class="{ 'btn-on': !store.paused }" @click="togglePause">
        {{ store.paused ? '已暂停' : '实时' }}
      </button>
      <button class="btn" :class="{ 'btn-on': autoScroll }" @click="toggleFollow">跟随</button>
      <button class="btn" @click="tick">刷新</button>
      <button class="btn btn-danger" @click="store.clear()">清空</button>
      <span class="lv-count">{{ store.filtered.length }} 条</span>
    </div>

    <div ref="listEl" class="lv-list" @scroll.passive="onUserScroll">
      <div v-for="(l, i) in store.filtered" :key="i" class="lv-row">
        <span class="lv-time">{{ fmtTime(l.ts) }}</span>
        <span class="lv-level" :class="levelClass(l.level)">{{ l.level }}</span>
        <span class="lv-source">{{ l.source }}</span>
        <span class="lv-msg">{{ l.message }}</span>
      </div>
      <div v-if="!store.filtered.length" class="lv-empty">暂无日志</div>
    </div>
    <p v-if="store.error" class="lv-error">{{ store.error }}</p>
  </div>
</template>

<style scoped>
.log-viewer { display: flex; flex-direction: column; height: 100%; }
.lv-toolbar { display: flex; align-items: center; gap: 8px; padding: 12px 16px; border-bottom: 1px solid var(--border); flex-wrap: wrap; }
.sel { padding: 6px 10px; border-radius: 8px; border: 1px solid var(--border); background: var(--input); color: var(--text); font-size: 12px; outline: none; }
.btn { padding: 6px 12px; border-radius: 8px; border: 1px solid var(--border); background: transparent; color: var(--text); cursor: pointer; font-size: 12px; }
.btn:hover { background: var(--card-head); }
.btn-on { background: var(--accent); border-color: var(--accent); color: #fff; }
.btn-danger { color: var(--err); border-color: var(--err); }
.lv-count { margin-left: auto; font-size: 12px; color: var(--muted); }
.lv-list { flex: 1; overflow-y: auto; padding: 8px 0; font-family: ui-monospace, SFMono-Regular, Consolas, monospace; font-size: 12px; }
.lv-row { display: flex; gap: 10px; padding: 3px 16px; line-height: 1.5; }
.lv-row:hover { background: var(--card-head); }
.lv-time { color: var(--muted); flex-shrink: 0; }
.lv-level { width: 64px; flex-shrink: 0; font-weight: 600; }
.lv-level.lv-error { color: var(--err); }
.lv-level.lv-warn { color: var(--warn); }
.lv-level.lv-debug { color: var(--muted); }
.lv-level.lv-info { color: var(--ok); }
.lv-source { width: 72px; flex-shrink: 0; color: var(--accent); }
.lv-msg { color: var(--text); word-break: break-all; }
.lv-empty { padding: 24px; text-align: center; color: var(--muted); }
.lv-error { margin: 8px 16px; font-size: 12px; color: var(--err); }
</style>
