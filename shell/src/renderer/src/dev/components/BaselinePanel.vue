<script setup lang="ts">
/**
 * S31：人格基线面板（PB0）—— 跑一遍固定场景，得到可对比的人格通过率。
 *
 * 对应引擎 API：GET /api/eval/personality/scenarios、POST /api/eval/personality。
 * 报告带 model + prompt_hash：换模型/改 Prompt 后，两份报告可直接比。
 * 默认「离线自检」不调模型（只验证评测链路）；「真跑」会逐场景请求 LLM。
 */
import { onMounted, ref } from 'vue'
import { api, type EvalReport, type EvalScenarios } from '../api'

const meta = ref<EvalScenarios | null>(null)
const report = ref<EvalReport | null>(null)
const loading = ref(false)
const error = ref('')
const live = ref(false)
const limit = ref(0)

async function loadScenarios(): Promise<void> {
  try {
    meta.value = await api.getEvalScenarios()
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  }
}

async function run(): Promise<void> {
  loading.value = true
  error.value = ''
  report.value = null
  try {
    report.value = await api.runEval(limit.value, live.value)
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    loading.value = false
  }
}

function pct(v: number): string {
  return `${Math.round(v * 100)}%`
}

onMounted(loadScenarios)
</script>

<template>
  <div class="baseline-panel">
    <div v-if="error" class="alert alert-err">{{ error }}</div>

    <div class="bubble bl-head">
      <div>
        <h3 class="bubble-title">人格基线（{{ meta?.total ?? 0 }} 个固定场景）</h3>
        <p class="hint">
          这是"尺子"：同一批场景反复跑，比较改 Prompt / 换模型后的人格变化。
          主观维度（像不像她）暂未覆盖，这里只抓可判定的下限。
        </p>
      </div>
      <div class="bl-actions">
        <label class="bl-limit">
          只跑
          <input v-model.number="limit" type="number" min="0" max="99" class="bl-input" />
          条（0 = 全部）
        </label>
        <label class="bl-check">
          <input v-model="live" type="checkbox" />
          真跑（调用模型）
        </label>
        <button class="btn btn-primary" :disabled="loading" @click="run">
          {{ loading ? '跑批中…' : '开始跑' }}
        </button>
      </div>
    </div>

    <div v-if="meta" class="bl-cats">
      <span v-for="(n, cat) in meta.by_category" :key="cat" class="bl-cat">
        {{ cat }} <b>{{ n }}</b>
      </span>
    </div>

    <div v-if="report && report.status === 'warn'" class="alert alert-err">{{ report.detail }}</div>

    <template v-if="report && report.status === 'ok'">
      <div class="bubble bl-report">
        <div class="bl-report-head">
          <div>
            <span class="bl-rate">{{ pct(report.pass_rate) }}</span>
            <span class="bl-rate-sub">{{ report.passed }}/{{ report.total }} 通过</span>
          </div>
          <div class="bl-meta">
            <span>model：{{ report.model || '—' }}</span>
            <span>prompt：{{ report.prompt_hash || '—' }}</span>
          </div>
        </div>
        <div class="bl-bycat">
          <div v-for="(s, cat) in report.by_category" :key="cat" class="bl-bycat-row">
            <span class="bl-bycat-name">{{ cat }}</span>
            <span class="bl-bycat-bar">
              <i :style="{ width: pct(s.pass_rate) }"></i>
            </span>
            <span class="bl-bycat-num">{{ s.passed }}/{{ s.total }}</span>
          </div>
        </div>
      </div>

      <div v-if="report.failures.length" class="task-group">
        <h3 class="section-h">未通过（{{ report.failures.length }}）</h3>
        <div v-for="f in report.failures" :key="f.id" class="bubble bl-fail">
          <div class="bl-fail-head">
            <span class="bl-fail-id">{{ f.id }}</span>
            <span class="bl-fail-cat">{{ f.category }}</span>
          </div>
          <p class="bl-fail-input">用户：{{ f.input }}</p>
          <p class="bl-fail-reply">她：{{ f.reply || '（空）' }}</p>
          <ul class="bl-fail-reasons">
            <li v-for="(r, i) in f.reasons" :key="i">{{ r }}</li>
          </ul>
        </div>
      </div>
      <p v-else class="bl-allpass">全部通过 —— 这批场景下没有人格退化迹象。</p>
    </template>

    <p v-if="!live && report" class="todo-note">
      离线模式用「回声 responder」：它只会证明**评测链路**通，不代表真实人格表现。
      勾选「真跑」才会真的调用模型（默认跳过工具类场景，避免真实操作系统）。
    </p>
  </div>
</template>

<style scoped>
.baseline-panel { display: flex; flex-direction: column; }
.bl-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 18px; }
.bl-actions { display: flex; align-items: center; gap: 12px; flex-shrink: 0; flex-wrap: wrap; }
.bl-limit, .bl-check { display: flex; align-items: center; gap: 6px; font-size: 12.5px; color: var(--muted); }
.bl-input {
  width: 52px; padding: 4px 6px; border-radius: var(--radius-sm);
  border: 1px solid var(--border); background: var(--input); color: var(--text);
  font-size: 12.5px; font-family: inherit; outline: none;
}
.bl-cats { display: flex; flex-wrap: wrap; gap: 8px; margin: 14px 0 4px; }
.bl-cat {
  font-size: 11.5px; color: var(--muted);
  padding: 3px 9px; border-radius: 999px; background: var(--card-head);
}
.bl-report { margin-top: 16px; }
.bl-report-head { display: flex; align-items: center; justify-content: space-between; gap: 16px; }
.bl-rate { font-size: 26px; font-weight: 700; color: var(--accent); margin-right: 8px; }
.bl-rate-sub { font-size: 12.5px; color: var(--muted); }
.bl-meta { display: flex; flex-direction: column; gap: 3px; font-size: 11.5px; color: var(--muted); text-align: right; }
.bl-bycat { margin-top: 14px; display: flex; flex-direction: column; gap: 7px; }
.bl-bycat-row { display: grid; grid-template-columns: 90px 1fr 52px; align-items: center; gap: 10px; font-size: 12px; }
.bl-bycat-name { color: var(--text-soft); }
.bl-bycat-bar { height: 7px; border-radius: 999px; background: var(--card-head); overflow: hidden; }
.bl-bycat-bar i { display: block; height: 100%; background: var(--accent); }
.bl-bycat-num { text-align: right; color: var(--muted); }
.task-group { margin-top: 18px; }
.bl-fail { margin-bottom: 12px; display: flex; flex-direction: column; gap: 5px; }
.bl-fail-head { display: flex; align-items: center; gap: 10px; }
.bl-fail-id { font-weight: 600; font-size: 13px; }
.bl-fail-cat { font-size: 11px; color: var(--muted); }
.bl-fail-input { margin: 0; font-size: 12.5px; color: var(--text-soft); }
.bl-fail-reply { margin: 0; font-size: 12.5px; color: var(--text); }
.bl-fail-reasons { margin: 2px 0 0; padding-left: 20px; font-size: 12px; color: var(--warn); line-height: 1.6; }
.bl-allpass { margin-top: 16px; font-size: 12.5px; color: var(--ok); }
</style>
