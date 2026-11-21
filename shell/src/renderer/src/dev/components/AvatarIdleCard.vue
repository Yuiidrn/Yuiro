<script setup lang="ts">
import { useLocalStorage } from '@vueuse/core'
import { computed, onMounted, ref, watch } from 'vue'
import type { Live2DManifest } from '@shared'
import { useAvatarIdlePref } from '../../composables/useAvatarIdlePref'
import { idleCandidates } from '../../avatar/avatarSlots'
import { useConfigStore } from '../stores/config'

/**
 * 待机行为（调试台「外观」页）
 *
 * 为什么需要单独一张卡：待机是最常被看到的状态，也是最容易"过"的状态。
 * 以前是全组随机 + 播完立刻续播（Hiyori 会把 8.6s 的全身动作当待机反复播）。
 * 现在只播 idle 语义动作、播完停顿；这里把这些参数交给你调。
 *
 * 改动即时同步到桌宠窗口（localStorage 同源 + storage 事件），无需重启。
 */
const store = useConfigStore()
const { agentReactionsEnabled,agentCooldownMs,agentMaxMs,fixedMotion,gazeHoldMs,gazeEnabled,gazeStrength,gestureCooldownMs,gestureMaxMs,reactiveEnabled, enabled, intervalMinMs, intervalMaxMs, maxDurationMs, reset } = useAvatarIdlePref()

const modelPath = computed(() => String(store.sections?.persona?.model_path ?? ''))
const manifest = ref<Live2DManifest | null>(null)
const error = ref('')
const observed=useLocalStorage('yuiro-avatar-status',{model:'',presence:'idle',expression:'',motion:'',motionIndex:null as number|null,until:0,at:0})
const matches=computed(()=>observed.value.model===modelPath.value)

async function refresh(): Promise<void> {
  if (!modelPath.value) return
  try {
    manifest.value = await window.yuiro.inspectPetModel(modelPath.value)
    error.value = ''
  } catch (e) {
    manifest.value = null
    error.value = e instanceof Error ? e.message : String(e)
  }
}

onMounted(refresh)
watch(modelPath, refresh)

const idlePool = computed(() => manifest.value?.index.idle ?? [])
/** 按当前时长上限过滤后的候选（与渲染层 idleCandidates 同规则） */
const usable = computed(() => idleCandidates(manifest.value,maxDurationMs.value,fixedMotion.value))

function fmt(ms: number): string {
  return `${(ms / 1000).toFixed(1)}s`
}
</script>

<template>
  <p v-if="matches&&observed.at" class="hint" aria-live="polite">模型状态快照：{{observed.presence}} · 表情 {{observed.expression||'默认'}} · 动作 {{observed.motion||'无'}} {{observed.motionIndex??''}} · 更新于 {{new Date(observed.at).toLocaleTimeString()}}</p>
  <label class="idle-row"><input v-model="reactiveEnabled" type="checkbox"/>交互状态反应（思考表情、说话短动作；按角色独立保存）</label>
  <div class="bubble card-narrow idle-card">
    <label class="idle-row"><input v-model="agentReactionsEnabled" type="checkbox"/>Agent任务微反应（关注、成功回应、待确认；按角色保存）</label>
    <label class="idle-row">Agent反应冷却 {{(agentCooldownMs/1000).toFixed(0)}}秒<input v-model.number="agentCooldownMs" type="range" min="3000" max="60000" step="1000"/></label>
    <label class="idle-row">Agent动作时长上限 {{(agentMaxMs/1000).toFixed(1)}}秒<input v-model.number="agentMaxMs" type="range" min="500" max="6000" step="100"/></label>
    <label class="idle-row"><input v-model="gazeEnabled" type="checkbox"/>关注附近鼠标（平滑、小幅度，远离后回正）</label>
    <label class="idle-row">鼠标静止 {{(gazeHoldMs/1000).toFixed(1)}}秒后恢复待机<input v-model.number="gazeHoldMs" type="range" min="500" max="10000" step="100"/></label>
    <label class="idle-row">注视幅度 {{gazeStrength.toFixed(2)}}<input v-model.number="gazeStrength" type="range" min="0" max="0.4" step="0.01"/></label>
    <label class="idle-row">说话动作冷却 {{(gestureCooldownMs/1000).toFixed(0)}}秒<input v-model.number="gestureCooldownMs" type="range" min="5000" max="60000" step="1000"/></label>
    <label class="idle-row">说话动作时长上限 {{(gestureMaxMs/1000).toFixed(1)}}秒<input v-model.number="gestureMaxMs" type="range" min="500" max="4000" step="100"/></label>
    <div class="row-between">
      <div>
        <h3 class="bubble-title">待机行为</h3>
        <p class="hint">
          Hiyori 固定播放选中的一个待机动作，丰富互动由单击动作池负责。待机只使用模型的 <strong>idle 类动作</strong>，播完停顿一段时间再播下一个；
          表情恢复最近的持续情绪，不再随机跳动。改完即时生效。
        </p>
      </div>
      <div class="idle-actions">
        <button class="btn" :disabled="!enabled" @click="enabled = false">暂停待机</button>
        <button class="btn" @click="reset">恢复默认</button>
      </div>
    </div>

    <label class="idle-row">待机动作
      <select v-model="fixedMotion" aria-label="待机动作选择">
        <option v-if="store.character?.active_id==='hotaru'" value="">按原待机池轮换</option>
        <option v-for="m in idlePool" :key="`${m.group}#${m.index}`" :value="`${m.group}#${m.index}`">{{m.group}} #{{m.index}} · {{fmt(m.durationMs)}}</option>
      </select>
    </label>
    <p v-if="fixedMotion&&!usable.length" class="hint">所选动作在当前模型中不可用，待机暂停；请选择一个有效动作。</p>
    <div class="idle-row">
      <div class="idle-text">
        <span class="idle-title">播放待机动作</span>
        <span class="hint">仅暂停待机动作；交互反应和鼠标注视由上方开关控制。</span>
      </div>
      <button
        class="toggle"
        :class="{ on: enabled }"
        :aria-pressed="enabled"
        @click="enabled = !enabled">
        {{ enabled ? '已开启' : '已关闭' }}
      </button>
    </div>

    <div class="idle-row idle-col">
      <label class="idle-label" for="idle-min">
        最短停顿
        <span class="idle-val">{{ (intervalMinMs / 1000).toFixed(0) }}s</span>
      </label>
      <input
        id="idle-min"
        v-model.number="intervalMinMs"
        type="range" min="2000" max="30000" step="500"
        class="slider" :disabled="!enabled" />
    </div>

    <div class="idle-row idle-col">
      <label class="idle-label" for="idle-max">
        最长停顿
        <span class="idle-val">{{ (intervalMaxMs / 1000).toFixed(0) }}s</span>
      </label>
      <input
        id="idle-max"
        v-model.number="intervalMaxMs"
        type="range" min="3000" max="60000" step="500"
        class="slider" :disabled="!enabled" />
    </div>

    <div class="idle-row idle-col">
      <label class="idle-label" for="idle-dur">
        动作时长上限
        <span class="idle-val">{{ (maxDurationMs / 1000).toFixed(1) }}s</span>
      </label>
      <input
        id="idle-dur"
        v-model.number="maxDurationMs"
        type="range" min="1000" max="12000" step="250"
        class="slider" :disabled="!enabled||!!fixedMotion" />
      <span class="hint">
        固定选中的动作不受此轮换筛选限制；轮换模式下超过该时长的 idle 动作会被跳过（例如 Hiyori 那个 8.6s 的全身动作）。
      </span>
    </div>

    <p v-if="error" class="idle-err">{{ error }}</p>
    <p v-else-if="manifest" class="hint">
      当前模型 idle 候选：<strong>{{ usable.length }}</strong> 个（共 {{ idlePool.length }} 个）<template v-if="usable.length">
        ·
        {{ usable.map(m => `${m.group}#${m.index} (${fmt(m.durationMs || 0)})`).join('、') }}
      </template>
    </p>
    <p v-if="manifest && !idlePool.length" class="hint">
      该模型没有 idle 类动作 → 待机将保持静止（可在「表现档案」里为它指定动作）。
    </p>
  </div>
</template>

<style scoped>
.idle-card { display: flex; flex-direction: column; gap: 12px; max-width: 760px; }
.idle-actions { display: flex; gap: 8px; flex-shrink: 0; }

.idle-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  padding: 10px 12px;
  border-radius: var(--radius-md);
  background: var(--card-head);
}
.idle-col { flex-direction: column; align-items: stretch; gap: 6px; }
.idle-text { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.idle-title { font-size: 13px; font-weight: 600; }
.idle-label { display: flex; align-items: center; justify-content: space-between; font-size: 12.5px; }
.idle-val { font-family: ui-monospace, monospace; font-size: 11.5px; color: var(--muted); }
.idle-err { margin: 0; font-size: 12px; color: var(--err); }

.toggle {
  flex-shrink: 0;
  padding: 6px 14px; border-radius: 999px;
  border: 1px solid var(--border); background: transparent;
  color: var(--muted); font-size: 12px; font-family: inherit; cursor: pointer;
}
.toggle.on { border-color: var(--accent); background: var(--accent-soft); color: var(--accent); font-weight: 600; }

.slider { width: 100%; accent-color: var(--accent); }
</style>
