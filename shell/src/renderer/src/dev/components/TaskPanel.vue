<script setup lang="ts">
/**
 * S31：任务面板——看它在做什么、批准它想做的事、手动推它一把。
 *
 * 对应引擎 API：GET /api/task/list、POST /api/task/{id}/approve|reject|retry。
 * "待批准计划"是 spec 的 plan approval（LEVEL 4）：批准前它是不会动手的。
 */
import { computed, onMounted, ref } from 'vue'
import { api, type TaskView } from '../api'

const tasks = ref<TaskView[]>([])
const loading = ref(false)
const error = ref('')
const includeDone = ref(false)
const busyId = ref('')

const pending = computed(() => tasks.value.filter((t) => t.task_status === 'pending_approval'))
const active = computed(() =>
  tasks.value.filter((t) => t.task_status !== 'pending_approval' && t.task_status !== 'completed'),
)
const finished = computed(() => tasks.value.filter((t) => t.task_status === 'completed'))

async function load(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    const r = await api.listTasks(includeDone.value)
    tasks.value = r.tasks ?? []
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    loading.value = false
  }
}

async function act(kind: 'approve' | 'reject' | 'retry', t: TaskView): Promise<void> {
  busyId.value = t.task_id
  error.value = ''
  try {
    if (kind === 'approve') await api.approveTask(t.task_id)
    else if (kind === 'reject') await api.rejectTask(t.task_id, '用户在调试台拒绝')
    else await api.retryTask(t.task_id, '用户在调试台手动重试')
    await load()
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    busyId.value = ''
  }
}

function statusLabel(s: string): string {
  const map: Record<string, string> = {
    pending_approval: '待批准',
    running: '进行中',
    created: '已创建',
    completed: '已完成',
    cancelled: '已取消',
    failed: '已失败',
  }
  return map[s] ?? s
}

onMounted(load)
</script>

<template>
  <div class="task-panel">
    <div v-if="error" class="alert alert-err">{{ error }}</div>

    <div class="bubble task-head">
      <div>
        <h3 class="bubble-title">它在做什么</h3>
        <p class="hint">
          待批准的计划会停在这里等你点头；批准前它不会动手（plan approval）。
        </p>
      </div>
      <div class="task-head-actions">
        <label class="task-check">
          <input v-model="includeDone" type="checkbox" @change="load" />
          含已完成
        </label>
        <button class="btn" :disabled="loading" @click="load">
          {{ loading ? '刷新中…' : '刷新' }}
        </button>
      </div>
    </div>

    <!-- 待批准：最显眼 -->
    <div v-if="pending.length" class="task-group">
      <h3 class="section-h">待你确认（{{ pending.length }}）</h3>
      <div v-for="t in pending" :key="t.task_id" class="bubble task-card pending">
        <div class="task-card-head">
          <span class="task-goal">{{ t.goal }}</span>
          <span class="task-badge">{{ statusLabel(t.task_status) }}</span>
        </div>
        <ol class="task-steps">
          <li v-for="(s, i) in t.steps" :key="i">{{ s }}</li>
        </ol>
        <div class="task-actions">
          <button
            class="btn btn-primary"
            :disabled="busyId === t.task_id"
            @click="act('approve', t)">
            按这个来
          </button>
          <button class="btn" :disabled="busyId === t.task_id" @click="act('reject', t)">
            先别做
          </button>
        </div>
      </div>
    </div>

    <div v-if="active.length" class="task-group">
      <h3 class="section-h">进行中（{{ active.length }}）</h3>
      <div v-for="t in active" :key="t.task_id" class="bubble task-card">
        <div class="task-card-head">
          <span class="task-goal">{{ t.goal }}</span>
          <span class="task-badge">{{ statusLabel(t.task_status) }} · {{ t.progress }}</span>
        </div>
        <p class="task-current">
          当前：{{ t.current_step || '—' }}
          <span v-if="t.attempts" class="task-attempts">（已尝试 {{ t.attempts }} 次）</span>
        </p>
        <ol class="task-steps">
          <li v-for="(s, i) in t.steps" :key="i">{{ s }}</li>
        </ol>
        <div class="task-actions">
          <button class="btn" :disabled="busyId === t.task_id" @click="act('retry', t)">
            标记一次失败并重试
          </button>
        </div>
      </div>
    </div>

    <div v-if="finished.length" class="task-group">
      <h3 class="section-h">已完成（{{ finished.length }}）</h3>
      <div v-for="t in finished" :key="t.task_id" class="task-line">
        <span class="task-goal-soft">{{ t.goal }}</span>
        <span class="task-badge">{{ t.progress }}</span>
      </div>
    </div>

    <p v-if="!tasks.length && !loading" class="task-empty">
      还没有任务。对它说一句需要好几步才能做完的事试试。
    </p>
  </div>
</template>

<style scoped>
.task-panel { display: flex; flex-direction: column; }
.task-head {
  display: flex; align-items: flex-start; justify-content: space-between; gap: 18px;
  margin-bottom: 8px;
}
.task-head-actions { display: flex; align-items: center; gap: 12px; flex-shrink: 0; }
.task-check { display: flex; align-items: center; gap: 6px; font-size: 12.5px; color: var(--muted); }
.task-group { margin-top: 18px; }
.task-card { display: flex; flex-direction: column; gap: 8px; margin-bottom: 12px; }
.task-card.pending { border-left: 3px solid var(--accent); }
.task-card-head { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.task-goal { font-weight: 600; font-size: 13.5px; }
.task-goal-soft { font-size: 13px; color: var(--text-soft); }
.task-badge {
  font-size: 11px; color: var(--muted);
  padding: 2px 8px; border-radius: 999px; background: var(--card-head);
  white-space: nowrap;
}
.task-current { margin: 0; font-size: 12.5px; color: var(--muted); }
.task-attempts { color: var(--warn); }
.task-steps { margin: 0; padding-left: 20px; font-size: 12.5px; color: var(--text-soft); line-height: 1.7; }
.task-actions { display: flex; gap: 10px; }
.task-line {
  display: flex; align-items: center; justify-content: space-between;
  padding: 7px 0; border-bottom: 1px dashed var(--border); font-size: 13px;
}
.task-empty { margin-top: 20px; font-size: 12.5px; color: var(--muted); }
</style>
