<script setup lang="ts">
/**
 * 记忆管理页：统一管理与观测三层记忆。
 *
 * - L3 用户事实：查看 / 新增 / 编辑 / 删除（写入走服务端的同义 key 归并，
 *   与 LLM 自动抽取保持同一口径，避免出现"籍贯"与"家乡"两个 key 各存一份）。
 * - L2 情景记忆：查看最近条目、按 rowid 删除。
 * - 检索观测：输入一句话，跑一次真实检索，看哪些记忆会被注入上下文——
 *   这是排查"说了却记不住 / 记忆没呼出"最直接的手段。
 */
import { computed, onMounted, ref } from 'vue'
import { api, type Fact } from '../api'

const loading = ref(false)
const error = ref('')
const facts = ref<Fact[]>([])
const episodes = ref<{ rowid: number; text: string; ts: number; salience: number }[]>([])

// ── 新增/编辑表单 ──
const formKey = ref('')
const formValue = ref('')
const editingKey = ref('') // 非空表示处于编辑态
const saving = ref(false)

// ── 检索观测 ──
const searchQuery = ref('')
const searching = ref(false)
const searchResults = ref<{ kind: string; text: string; score: number }[]>([])
const searchNote = ref('')

async function load(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    const snap = await api.getMemory()
    facts.value = (snap.facts ?? []).filter((f) => !('error' in (f as object)))
    episodes.value = snap.episodes ?? []
    if (snap.note) error.value = snap.note
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    loading.value = false
  }
}

function beginEdit(f: Fact): void {
  editingKey.value = f.key
  formKey.value = f.key
  formValue.value = f.value
}

function cancelEdit(): void {
  editingKey.value = ''
  formKey.value = ''
  formValue.value = ''
}

async function submitFact(): Promise<void> {
  if (!formKey.value.trim() || !formValue.value.trim()) return
  saving.value = true
  try {
    await api.upsertFact(formKey.value.trim(), formValue.value.trim())
    cancelEdit()
    await load()
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    saving.value = false
  }
}

async function removeFact(key: string): Promise<void> {
  if (!confirm(`确定不再记住「${key}」？`)) return
  try {
    await api.deleteFact(key)
    if (editingKey.value === key) cancelEdit()
    await load()
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  }
}

async function removeEpisode(rowid: number): Promise<void> {
  if (!confirm('确定删掉这条记忆？此操作不可撤销。')) return
  try {
    await api.deleteEpisode(rowid)
    await load()
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  }
}

async function runSearch(): Promise<void> {
  if (!searchQuery.value.trim()) return
  searching.value = true
  searchNote.value = ''
  searchResults.value = []
  try {
    const r = await api.searchMemory(searchQuery.value.trim(), 8)
    searchResults.value = r.results ?? []
    if (r.note) searchNote.value = r.note
  } catch (e) {
    searchNote.value = e instanceof Error ? e.message : String(e)
  } finally {
    searching.value = false
  }
}

async function clearAll(): Promise<void> {
  if (!confirm('确定清空全部记忆？（她记住的你、聊过的片段、你让她记住的事都会删掉，不可撤销）')) return
  try {
    await api.clearMemory()
    await load()
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  }
}

function fmtTime(ts: number): string {
  if (!ts) return '—'
  const d = new Date(ts * 1000)
  return d.toLocaleString('zh-CN', { hour12: false })
}

const factCount = computed(() => facts.value.length)
const episodeCount = computed(() => episodes.value.length)

onMounted(load)
</script>

<template>
  <div class="mem">
    <div v-if="error" class="notice notice-err">{{ error }}</div>

    <!--
      这里不再重复展示「事实数 / 情景数」——
      同页上方的「记忆洞察」已给出三通道计数（显式 / L3 / L2），是记忆规模的唯一来源。
    -->

    <!-- 「她记住的你」：说人话，不写 L3 -->
    <h3 class="section-h">她记住的你</h3>
    <div class="card">
      <p class="hint">
        这些会在每轮对话前作为「关于{{ 'Yui' }}的事」交给她。
        相近的说法会自动归并（如“家乡”并入“籍贯”），不会散落成一堆重复条目。
      </p>

      <div v-if="!factCount" class="empty">暂无事实。可在下方新增，或直接与桌宠聊天让其自动抽取。</div>

      <table v-else class="table">
        <thead>
          <tr><th style="width:140px">键</th><th>值</th><th style="width:110px">置信度</th><th style="width:200px">更新时间</th><th style="width:120px">操作</th></tr>
        </thead>
        <tbody>
          <tr v-for="f in facts" :key="f.key">
            <td class="mono">{{ f.key }}</td>
            <td>{{ f.value }}</td>
            <td class="mono">{{ (f.effective_confidence ?? f.confidence).toFixed(2) }}</td>
            <td class="dim">{{ fmtTime(f.updated_at) }}</td>
            <td>
              <button class="btn-mini" @click="beginEdit(f)">编辑</button>
              <button class="btn-mini btn-mini-danger" @click="removeFact(f.key)">删除</button>
            </td>
          </tr>
        </tbody>
      </table>

      <div class="form-row">
        <input v-model="formKey" class="input" placeholder="键（如 籍贯）" :disabled="!!editingKey" />
        <input v-model="formValue" class="input" placeholder="值（如 广东人）" />
        <button class="btn btn-primary" :disabled="saving" @click="submitFact">
          {{ editingKey ? '保存修改' : '新增事实' }}
        </button>
        <button v-if="editingKey" class="btn" @click="cancelEdit">取消</button>
      </div>
    </div>

    <!-- 检索观测 -->
    <h3 class="section-h">检索观测</h3>
    <div class="card">
      <p class="hint">
        输入一句话（例如“我是哪里人”），查看实际会召回哪些记忆并注入上下文。
        若期望的内容没有出现，说明该记忆未被成功抽取或未被检索到。
      </p>
      <div class="form-row">
        <input
          v-model="searchQuery"
          class="input"
          placeholder="输入查询词，如：我是哪里人 / 我喜欢吃什么"
          @keyup.enter="runSearch" />
        <button class="btn btn-primary" :disabled="searching" @click="runSearch">
          {{ searching ? '检索中…' : '检索' }}
        </button>
      </div>

      <div v-if="searchNote" class="notice notice-err" style="margin-top:12px">{{ searchNote }}</div>

      <div v-if="searchResults.length" class="results">
        <div v-for="(r, i) in searchResults" :key="i" class="result-item">
          <span class="tag" :class="r.kind === 'fact' ? 'tag-fact' : 'tag-ep'">
            {{ r.kind === 'fact' ? '关于你' : '聊过' }}
          </span>
          <span class="result-text">{{ r.text }}</span>
          <span class="mono dim">{{ r.score }}</span>
        </div>
      </div>
      <div v-else-if="!searching && searchQuery" class="empty">没有召回任何记忆。</div>
    </div>

    <!-- 「聊过的片段」：说人话，不写 L2 -->
    <h3 class="section-h">聊过的片段（最近 {{ episodeCount }} 条）</h3>
    <div class="card">
      <div v-if="!episodeCount" class="empty">暂无情景记忆。</div>
      <div v-else class="ep-list">
        <div v-for="e in episodes" :key="e.rowid" class="ep-item">
          <div class="ep-text">{{ e.text }}</div>
          <div class="ep-meta">
            <span class="dim">{{ fmtTime(e.ts) }}</span>
            <span class="dim">显著性 {{ e.salience }}</span>
            <button class="btn-mini btn-mini-danger" @click="removeEpisode(e.rowid)">删除</button>
          </div>
        </div>
      </div>
    </div>

    <div class="foot">
      <button class="btn" :disabled="loading" @click="load">
        {{ loading ? '刷新中…' : '刷新' }}
      </button>
      <button class="btn btn-danger" @click="clearAll">清空全部记忆</button>
    </div>
  </div>
</template>

<style scoped>
.mem { max-width: 1000px; }
.notice { padding: 10px 14px; border-radius: 10px; font-size: 13px; margin-bottom: 16px; }
.notice-err { background: color-mix(in srgb, var(--err) 12%, transparent); color: var(--err); }

.card { border: 1px solid var(--border); border-radius: 14px; background: var(--card); padding: 16px; }

.section-h { font-size: 14px; font-weight: 600; margin: 24px 0 12px; }
.hint { font-size: 12px; color: var(--muted); margin: 0 0 14px; line-height: 1.6; }
.empty { font-size: 13px; color: var(--muted); padding: 16px 0; }

.table { width: 100%; border-collapse: collapse; font-size: 13px; }
.table th { text-align: left; color: var(--muted); font-weight: 600; padding: 8px 6px; border-bottom: 1px solid var(--border); }
.table td { padding: 8px 6px; border-bottom: 1px solid var(--border-soft); vertical-align: middle; }
.mono { font-family: ui-monospace, monospace; }
.dim { color: var(--muted); font-size: 12px; }

.form-row { display: flex; gap: 10px; margin-top: 14px; flex-wrap: wrap; }
.input {
  flex: 1; min-width: 160px; padding: 8px 10px; border-radius: 8px;
  border: 1px solid var(--border); background: var(--input); color: var(--text);
  font-size: 13px; outline: none;
}
.input:focus { border-color: var(--accent); }

.btn { padding: 7px 14px; border-radius: 8px; border: 1px solid var(--border); background: transparent; color: var(--text); cursor: pointer; font-size: 13px; }
.btn:hover { background: var(--card-head); }
.btn-primary { background: var(--accent); border-color: var(--accent); color: #fff; }
.btn-primary:disabled { opacity: 0.4; cursor: default; }
.btn-danger { background: #e0524d; border-color: #e0524d; color: #fff; }
.btn-mini {
  padding: 3px 9px; border-radius: 6px; border: 1px solid var(--border);
  background: transparent; color: var(--text); cursor: pointer; font-size: 12px; margin-right: 6px;
}
.btn-mini:hover { background: var(--card-head); }
.btn-mini-danger { color: var(--err); border-color: color-mix(in srgb, var(--err) 40%, transparent); }

.results { margin-top: 14px; display: flex; flex-direction: column; gap: 8px; }
.result-item {
  display: flex; align-items: center; gap: 10px; padding: 9px 12px;
  border: 1px solid var(--border-soft); border-radius: 9px; font-size: 13px;
}
.result-text { flex: 1; }
.tag { font-size: 11px; padding: 2px 8px; border-radius: 999px; flex-shrink: 0; }
.tag-fact { background: var(--accent-soft); color: var(--accent); }
.tag-ep { background: var(--card-head); color: var(--muted); }

.ep-list { display: flex; flex-direction: column; gap: 10px; }
.ep-item { border: 1px solid var(--border-soft); border-radius: 10px; padding: 10px 12px; }
.ep-text { font-size: 13px; white-space: pre-wrap; word-break: break-word; }
.ep-meta { display: flex; align-items: center; gap: 12px; margin-top: 6px; }

.foot { margin-top: 20px; display: flex; justify-content: flex-end; gap: 10px; }
</style>
