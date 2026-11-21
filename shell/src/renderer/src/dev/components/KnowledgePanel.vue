<script setup lang="ts">
/**
 * S51 知识库面板：让“她看过什么资料”变得**可见、可控**。
 *
 * 为什么必须做：知识库此前**后端有、界面没有** —— 里面装了什么、每轮注入多少
 * token，用户完全看不见。实测后果：一份 `docs/init/milestones.md`（里程碑路线图）
 * 在里面躺了很久，每轮对话都在注入（286 tokens），她会冒出“我们在 M4→M5 阶段”
 * 这类项目术语 —— 用户原话是“当知识库有些出戏了”。
 *
 * 定位提醒：知识库是「**你自己想让她知道的资料**」（说明书、专业资料、你喜欢的书…），
 * 不是仓库里的开发过程文档 —— 开发文档会被她当成常识在闲聊里说出来。
 */
import { onMounted, ref } from 'vue'
import { Icon } from '@iconify/vue'
import { api, type KnowledgeView } from '../api'

const data = ref<KnowledgeView | null>(null)
const error = ref('')
const notice = ref('')
const loading = ref(false)
const busy = ref(false)

const text = ref('')
const source = ref('')
/**
 * S54：待导入的资料路径（**多选**）。
 *
 * 与 TTS 参考字段的区别就在这里：参考音频/转写只能有一个，而知识库是"资料集合"，
 * 用户经常要一次导入一批笔记 —— 所以用系统文件框的多选，而不是手敲一个路径。
 * 目录也允许（引擎侧 `isdir` → `ingest_dir`）。
 */
const picked = ref<string[]>([])
/** 被“开发文档防线”拦下、等待用户二次确认（force）的路径。 */
const pendingForcePaths = ref<string[]>([])
/** 多文件导入时的进度文案（"导入中…（2/5）"）。 */
const busyText = ref('')
/** 被“开发文档防线”拦下时的说明（用户可选择仍然导入）。 */
const blocked = ref('')

async function load(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    data.value = await api.getKnowledge()
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    loading.value = false
  }
}

/** 取路径最后一段（兼容 `\` 与 `/`）。 */
function basename(p: string): string {
  const parts = p.split(/[\\/]+/).filter(Boolean)
  return parts[parts.length - 1] || p
}

/** S54：打开系统文件框（多选）——知识库与 TTS 参考的差别就在这个 multiple。 */
async function pickFiles(): Promise<void> {
  try {
    const res = await window.yuiro?.pickFiles({
      kind: 'any',
      multiple: true,
      title: '选择要导入的资料（可多选）',
    })
    if (!res || res.canceled) return
    for (const p of res.paths) {
      if (!picked.value.includes(p)) picked.value.push(p)
    }
  } catch (e) {
    notice.value = e instanceof Error ? e.message : String(e)
  }
}

/** 选一个目录（引擎支持递归导入整个目录）。 */
async function pickDir(): Promise<void> {
  try {
    const res = await window.yuiro?.pickFiles({ directory: true, title: '选择资料目录' })
    if (!res || res.canceled || !res.paths.length) return
    const dir = res.paths[0]
    if (!picked.value.includes(dir)) picked.value.push(dir)
  } catch (e) {
    notice.value = e instanceof Error ? e.message : String(e)
  }
}

function removePicked(p: string): void {
  picked.value = picked.value.filter((x) => x !== p)
}

async function ingest(force = false): Promise<void> {
  notice.value = ''
  blocked.value = ''
  // 二次确认（force）只重跑被拦下的那几个；否则导入当前选中项
  const targets = force && pendingForcePaths.value.length
    ? [...pendingForcePaths.value]
    : [...picked.value]
  if (!targets.length && !text.value.trim()) {
    notice.value = '先选文件（可多选），或粘贴一段内容'
    return
  }
  busy.value = true
  busyText.value = ''
  const okItems: string[] = []
  const okPaths: string[] = []
  const failed: string[] = []
  const blockedNow: string[] = []
  let blockedNote = ''
  try {
    if (!targets.length) {
      // 粘贴内容：单条，无路径
      const res = await api.ingestKnowledge({
        text: text.value.trim(),
        source: source.value.trim() || '手动导入',
      })
      if (res.blocked) {
        blocked.value = res.note ?? '这看起来是开发文档'
        pendingForcePaths.value = []
        return
      }
      if (res.ok) {
        notice.value = `已导入 ${res.chunks ?? 0} 块`
        text.value = ''
        source.value = ''
      } else {
        notice.value = res.note ?? '导入失败'
      }
    } else {
      // 逐个导入：单个失败/被拦不影响其它文件（也能给出逐个结果）
      for (let i = 0; i < targets.length; i++) {
        const p = targets[i]
        busyText.value = `导入中…（${i + 1}/${targets.length}）${basename(p)}`
        try {
          const res = await api.ingestKnowledge({ path: p, force })
          if (res.blocked) {
            blockedNow.push(p)
            blockedNote = res.note ?? ''
            continue
          }
          if (res.ok) {
            okItems.push(`${basename(p)}（${res.chunks ?? 0} 块）`)
            okPaths.push(p)
          } else {
            failed.push(`${basename(p)}：${res.note ?? '导入失败'}`)
          }
        } catch (e) {
          failed.push(`${basename(p)}：${e instanceof Error ? e.message : String(e)}`)
        }
      }
      // 成功的不再留在待导入列表；失败/被拦的留着，便于重试
      picked.value = picked.value.filter((p) => !okPaths.includes(p))
      pendingForcePaths.value = blockedNow
      if (blockedNow.length) {
        blocked.value = `${blockedNote}\n被拦下的：${blockedNow.map(basename).join('、')}`
      }
      if (okItems.length) notice.value = `已导入 ${okItems.length} 个：${okItems.join('、')}`
      if (failed.length) {
        notice.value += `${notice.value ? '；' : ''}失败 ${failed.length} 个：${failed.join('；')}`
      }
      if (okItems.length) {
        text.value = ''
        source.value = ''
      }
    }
    await load()
  } catch (e) {
    notice.value = e instanceof Error ? e.message : String(e)
  } finally {
    busy.value = false
    busyText.value = ''
  }
}

const confirmClear = ref(false)

async function clearAll(): Promise<void> {
  if (!confirmClear.value) {
    confirmClear.value = true
    notice.value = '再点一次确认清空（她将不再"看过"这些资料）'
    return
  }
  confirmClear.value = false
  notice.value = ''
  busy.value = true
  try {
    const res = await api.clearKnowledge()
    notice.value = res.ok ? '知识库已清空' : (res.note ?? '清空失败')
    await load()
  } catch (e) {
    notice.value = e instanceof Error ? e.message : String(e)
  } finally {
    busy.value = false
  }
}

onMounted(load)
defineExpose({ load })
</script>

<template>
  <div class="bubble kp">
    <div class="kp-head">
      <div>
        <h3 class="bubble-title">知识库</h3>
        <p class="hint">
          你给她的资料 —— 她会当成<b>已经看过的东西</b>，回答时可以引用。
          <span v-if="data?.stats?.chunks" class="kp-count">{{ data.stats.chunks }} 块</span>
        </p>
      </div>
      <button class="btn" :disabled="loading" @click="load">
        <Icon icon="solar:refresh-bold" width="12" /> 刷新
      </button>
    </div>

    <div v-if="error" class="notice notice-err">{{ error }}</div>
    <div v-if="notice" class="hint">{{ notice }}</div>

    <!-- 来源清单：这是"可见"的核心 —— 没有它，用户不知道装了什么 -->
    <template v-if="data?.sources?.length">
      <div class="kp-sources">
        <div v-for="s in data.sources" :key="s.source" class="kp-src">
          <div class="kp-src-top">
            <span class="kp-src-name" :title="s.source">{{ s.source }}</span>
            <span class="kp-src-n">{{ s.chunks }} 块</span>
          </div>
          <p class="kp-src-sample">{{ s.sample }}</p>
        </div>
      </div>
      <div class="kp-actions">
        <button class="btn kp-danger" :class="{ armed: confirmClear }" :disabled="busy" @click="clearAll">
          {{ confirmClear ? '确认清空？' : '清空知识库' }}
        </button>
      </div>
    </template>

    <!-- 空状态：说清它该装什么（正确定位），避免又变成"仓库文档收纳盒" -->
    <div v-else-if="!loading" class="kp-empty">
      <p class="kp-empty-title">还是空的</p>
      <p class="kp-empty-hint">
        这里适合放<b>你想让她知道的资料</b>：说明书、专业资料、你写的笔记、喜欢的书摘。
        放这里的每一段都会在对话前带上（占上下文），所以别放开发文档 / 路线图这类东西 ——
        她会当成常识在闲聊里说出来。
      </p>
    </div>

    <div class="kp-form">
      <!-- S54：改为系统选择框（知识库**支持多文件**，与 TTS 参考的单选不同） -->
      <div class="kp-pick-row">
        <button class="btn" :disabled="busy" @click="pickFiles">
          <Icon icon="solar:folder-open-bold" width="12" /> 选择文件（可多选）
        </button>
        <button class="btn" :disabled="busy" @click="pickDir">
          <Icon icon="solar:folder-bold" width="12" /> 选择目录
        </button>
        <span class="kp-pick-hint">选文件可一次选多个；目录会递归导入</span>
      </div>

      <!-- 已选清单：看得见"这次要导入什么"，也能逐个移除 -->
      <ul v-if="picked.length" class="kp-picked">
        <li v-for="p in picked" :key="p" class="kp-picked-item">
          <Icon icon="solar:document-bold" width="12" class="kp-picked-icon" />
          <span class="kp-picked-name" :title="p">{{ basename(p) }}</span>
          <button class="kp-picked-x" title="移除" :disabled="busy" @click="removePicked(p)">✕</button>
        </li>
      </ul>

      <input v-model="text" class="input kp-text" placeholder="或直接粘贴一段内容…" />
      <input v-model="source" class="input kp-source" placeholder="来源名（可选，仅粘贴内容时生效）" />
      <div class="kp-form-actions">
        <button class="btn btn-primary" :disabled="busy" @click="ingest(false)">
          {{ busy ? (busyText || '导入中…') : (picked.length ? `导入 ${picked.length} 项` : '导入') }}
        </button>
      </div>
    </div>

    <!-- 开发文档防线：默认拦住，给"确实要导入"的出口 -->
    <div v-if="blocked" class="kp-blocked">
      <p class="kp-blocked-text">{{ blocked }}</p>
      <button
        v-if="pendingForcePaths.length"
        class="btn kp-danger"
        :disabled="busy"
        @click="ingest(true)">
        仍然导入这 {{ pendingForcePaths.length }} 项
      </button>
    </div>
  </div>
</template>

<style scoped>
.kp { display: flex; flex-direction: column; gap: 10px; }
.kp-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 10px; }
.kp-count { margin-left: 8px; color: var(--muted, #94a3b8); font-variant-numeric: tabular-nums; }

.kp-sources { display: flex; flex-direction: column; gap: 6px; }
.kp-src {
  padding: 8px 10px; border-radius: 8px;
  background: var(--card-head, rgba(148, 163, 184, 0.08));
}
.kp-src-top { display: flex; align-items: baseline; justify-content: space-between; gap: 8px; }
.kp-src-name {
  font-size: 12.5px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  direction: rtl; text-align: left;
}
.kp-src-n { flex-shrink: 0; font-size: 11.5px; color: var(--muted, #94a3b8); }
.kp-src-sample {
  margin: 4px 0 0; font-size: 11.5px; color: var(--muted, #94a3b8);
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden;
}

.kp-empty { padding: 12px 2px; }
.kp-empty-title { margin: 0 0 4px; font-weight: 600; }
.kp-empty-hint { margin: 0; font-size: 12.5px; line-height: 1.8; color: var(--muted, #94a3b8); }

.kp-form { display: flex; flex-wrap: wrap; gap: 6px; }
.kp-form .input { flex: 1; min-width: 200px; }

/* S54：系统选择框 + 已选清单（多文件） */
.kp-pick-row { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; width: 100%; }
.kp-pick-row .btn { display: inline-flex; align-items: center; gap: 5px; font-size: 12.5px; }
.kp-pick-hint { font-size: 11.5px; color: var(--muted, #94a3b8); }
.kp-picked {
  list-style: none; margin: 2px 0 0; padding: 8px 10px; width: 100%;
  display: flex; flex-direction: column; gap: 4px;
  border: 1px dashed var(--border, rgba(148, 163, 184, 0.35));
  border-radius: 8px;
}
.kp-picked-item { display: flex; align-items: center; gap: 6px; font-size: 12.5px; }
.kp-picked-icon { flex-shrink: 0; color: var(--muted, #94a3b8); }
.kp-picked-name {
  flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  direction: rtl; text-align: left;
}
.kp-picked-x {
  flex-shrink: 0; padding: 0 5px; border: none; background: none; cursor: pointer;
  color: var(--muted, #94a3b8); font-size: 12px; line-height: 1.6;
}
.kp-picked-x:hover:not(:disabled) { color: #c47b7b; }
.kp-picked-x:disabled { opacity: 0.4; cursor: default; }
.kp-text { min-width: 100% !important; }
.kp-source { max-width: 160px; }
.kp-form-actions { display: flex; justify-content: flex-end; width: 100%; }

.kp-actions { display: flex; justify-content: flex-end; }
.kp-danger { color: #c47b7b; border-color: rgba(196, 123, 123, 0.4); }
.kp-danger.armed { background: rgba(196, 123, 123, 0.16); color: #e08a8a; }

.kp-blocked {
  padding: 10px 12px; border-radius: 8px;
  background: rgba(214, 158, 92, 0.1);
  border: 1px solid rgba(214, 158, 92, 0.35);
}
.kp-blocked-text { margin: 0 0 8px; font-size: 12.5px; line-height: 1.75; color: #d6a35c; }
</style>
