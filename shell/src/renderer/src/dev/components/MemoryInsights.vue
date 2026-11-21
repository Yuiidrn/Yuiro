<script setup lang="ts">
/**
 * S31：记忆洞察——把 S17/S26/S28 的能力搬到界面上：
 * - 三通道计数（显式 / 事实 / 情景）；
 * - 关系记忆（认识多久 / 聊过多少次 / 一起做成过什么）；
 * - 显式记忆列表（可删除）；
 * - 归纳按钮（Episode → 稳定画像）。
 */
import { onMounted, ref } from 'vue'
import { api, type ConsolidationReport, type ExplicitItem, type MemoryShowcase, type RelationshipView } from '../api'

const showcase = ref<MemoryShowcase | null>(null)
const relationship = ref<RelationshipView | null>(null)
const explicit = ref<ExplicitItem[]>([])
const report = ref<ConsolidationReport | null>(null)
const loading = ref(false)
const consolidating = ref(false)
const error = ref('')

async function load(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    const [sc, rel, ex] = await Promise.all([
      api.getMemoryShowcase(),
      api.getRelationship(),
      api.listExplicit(),
    ])
    showcase.value = sc
    relationship.value = rel
    explicit.value = ex.items ?? []
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    loading.value = false
  }
}

async function consolidate(): Promise<void> {
  consolidating.value = true
  error.value = ''
  try {
    report.value = await api.consolidateMemory(3, false)
    await load()
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    consolidating.value = false
  }
}

async function removeExplicit(rowid: number): Promise<void> {
  try {
    await api.deleteExplicit(rowid)
    await load()
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  }
}

function fmtTime(ts: number): string {
  if (!ts) return '—'
  const d = new Date(ts * 1000)
  const p = (n: number): string => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`
}

onMounted(load)
</script>

<template>
  <div class="insights">
    <div v-if="error" class="alert alert-err">{{ error }}</div>

    <div class="bubble ins-head">
      <div>
        <h3 class="bubble-title">记忆洞察</h3>
        <p class="hint">它在"记得什么"，以及它对自己与你的关系的理解。</p>
      </div>
      <div class="ins-actions">
        <button class="btn" :disabled="loading" @click="load">
          {{ loading ? '读取中…' : '刷新' }}
        </button>
        <button class="btn btn-primary" :disabled="consolidating" @click="consolidate">
          {{ consolidating ? '归纳中…' : '归纳一次' }}
        </button>
      </div>
    </div>

    <!-- 三类记忆的计数：说人话，不写 L2/L3（界面上的术语没人看得懂） -->
    <div v-if="showcase" class="ins-counts">
      <div class="bubble ins-count">
        <span class="ins-count-num">{{ showcase.counts.explicit }}</span>
        <span class="ins-count-label">你让她记住的</span>
      </div>
      <div class="bubble ins-count">
        <span class="ins-count-num">{{ showcase.counts.facts }}</span>
        <span class="ins-count-label">她记住的你</span>
      </div>
      <div class="bubble ins-count">
        <span class="ins-count-num">{{ showcase.counts.episodes }}</span>
        <span class="ins-count-label">聊过的片段</span>
      </div>
    </div>

    <!-- 关系记忆 -->
    <div v-if="relationship && relationship.summary" class="bubble ins-rel">
      <h3 class="bubble-title">我们的关系</h3>
      <p class="ins-rel-summary">{{ relationship.summary }}</p>
      <div class="ins-rel-grid">
        <span>认识 <b>{{ relationship.days_known }}</b> 天</span>
        <span>聊过 <b>{{ relationship.interactions }}</b> 次</span>
        <span>一起完成 <b>{{ relationship.tasks_completed }}</b> 件事</span>
      </div>
      <ul v-if="relationship.milestones?.length" class="ins-milestones">
        <li v-for="(m, i) in relationship.milestones.slice(-5)" :key="i">{{ m }}</li>
      </ul>
    </div>

    <!-- 归纳结果（说人话：不写"支持度/候选"这类内部词） -->
    <div v-if="report" class="bubble ins-report">
      <h3 class="bubble-title">上次归纳</h3>
      <p class="hint">
        翻看了 {{ report.scanned }} 条聊过的片段，归纳出 {{ report.written }} 条新的印象
        （{{ report.skipped_low_support + report.skipped_existing }} 条因为"只提过一次"或
        "已有更确定的说法"没有采纳）
      </p>
      <ul v-if="report.details?.length" class="ins-details">
        <li v-for="(d, i) in report.details" :key="i">
          {{ d.key }}：{{ d.value }} <span class="ins-support">（提到过 {{ d.support }} 次）</span>
        </li>
      </ul>
    </div>

    <!-- 显式记忆列表 -->
    <h3 class="section-h">你要求它记住的事（{{ explicit.length }}）</h3>
    <div v-if="explicit.length" class="ins-explicit">
      <div v-for="e in explicit" :key="e.rowid" class="ins-explicit-row">
        <div class="ins-explicit-text">
          <span>{{ e.text }}</span>
          <span class="ins-explicit-ts">{{ fmtTime(e.ts) }}</span>
        </div>
        <button class="btn" @click="removeExplicit(e.rowid)">忘掉</button>
      </div>
    </div>
    <p v-else class="hint">还没有 —— 对它说「记住：……」试试。</p>
  </div>
</template>

<style scoped>
.insights { display: flex; flex-direction: column; }
.ins-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 18px; }
.ins-actions { display: flex; gap: 10px; flex-shrink: 0; }
.ins-counts { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 14px; margin-top: 14px; }
.ins-count { display: flex; flex-direction: column; gap: 4px; padding: 14px 16px; }
.ins-count-num { font-size: 22px; font-weight: 700; color: var(--accent); }
.ins-count-label { font-size: 11.5px; color: var(--muted); }
.ins-rel { margin-top: 14px; }
.ins-rel-summary { margin: 8px 0; font-size: 13px; line-height: 1.7; color: var(--text); }
.ins-rel-grid { display: flex; gap: 20px; font-size: 12px; color: var(--muted); }
.ins-rel-grid b { color: var(--accent); }
.ins-milestones { margin: 10px 0 0; padding-left: 20px; font-size: 12px; color: var(--text-soft); line-height: 1.7; }
.ins-report { margin-top: 14px; }
.ins-details { margin: 8px 0 0; padding-left: 20px; font-size: 12.5px; color: var(--text-soft); line-height: 1.7; }
.ins-support { color: var(--muted); }
.section-h { margin: 22px 0 10px; font-size: 13px; font-weight: 700; color: var(--muted); }
.ins-explicit { display: flex; flex-direction: column; gap: 8px; }
.ins-explicit-row {
  display: flex; align-items: center; justify-content: space-between; gap: 14px;
  padding: 10px 14px; border-radius: var(--radius-md);
  border: 1px solid var(--border); background: var(--card);
}
.ins-explicit-text { display: flex; flex-direction: column; gap: 3px; min-width: 0; }
.ins-explicit-text span:first-child { font-size: 12.5px; word-break: break-all; }
.ins-explicit-ts { font-size: 11px; color: var(--muted); }
</style>
