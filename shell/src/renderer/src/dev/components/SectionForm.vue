<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { Icon } from '@iconify/vue'
import { useConfigStore } from '../stores/config'
import { api } from '../api'
import FishKeySettings from './FishKeySettings.vue'
import type { FieldMeta, FieldValue } from '@shared'
import {
  SECTION_CATALOG,
  essentialSummary,
  hasHiddenFields,
  resolveVisibleFields,
  summaryOfFields,
} from '../configCatalog'

const props = defineProps<{
  section: string
  /**
   * 只渲染这些字段（顺序即显示顺序）。
   * 用于把某个配置段里的个别字段分发到更贴切的页面，
   * 例如把 persona 的「音色」放到「声音」页、「记忆主体」放到「记忆」页。
   */
  only?: string[]
  /** 覆盖卡片标题 / 说明（不传则用目录里的） */
  title?: string
  subtitle?: string
}>()

const store = useConfigStore()

const meta = computed<Record<string, FieldMeta>>(() => store.schema[props.section] ?? {})
const remote = computed<Record<string, FieldValue>>(() => store.sections[props.section] ?? {})
const allKeys = computed(() => Object.keys(meta.value))

const cat = computed(() => SECTION_CATALOG[props.section])
const cardTitle = computed(() => props.title ?? cat.value?.title ?? props.section)
const cardSubtitle = computed(() => props.subtitle ?? cat.value?.subtitle ?? '')

/** 是否处于「只取个别字段」模式。 */
const partial = computed(() => !!props.only?.length)

/**
 * 单字段卡（如「记忆归属」只含 memory_subject）**不再重复显示字段名**。
 *
 * 实测反馈："有遗漏"—— 截图里卡标题是「记忆归属」，下面字段行又写着「记忆主体 /
 * L3 事实隔离键」，看起来像两张卡、像没改干净。其实卡标题已经把事情说清楚了，
 * 字段名纯属重复（而且它来自引擎 FIELD_META，不重启就是旧文案）。
 * 保留 hint（说明有用），只隐去重复的字段名。
 */
const hideRowLabel = computed(
  () => partial.value && (props.only?.length ?? 0) === 1 && Boolean(props.title),
)

/** LLM 提供商预设：切换 provider 时自动填充默认 base_url/model，省去手填。 */
const LLM_PRESETS: Record<string, { base_url: string; model: string }> = {
  openai: { base_url: 'https://api.openai.com/v1', model: 'gpt-4o-mini' },
  deepseek: { base_url: 'https://api.deepseek.com/v1', model: 'deepseek-chat' },
  ollama: { base_url: 'http://localhost:11434/v1', model: 'qwen2.5:7b' },
  qwen: { base_url: 'https://dashscope.aliyuncs.com/compatible-mode/v1', model: 'qwen-plus' },
}

const draft = reactive<Record<string, FieldValue>>({})
const dirty = ref(false)
const applying = ref(false)
const applyError = ref('')
const saved = ref(false)
// 默认展开：因为只显示 2~3 个关键字段，展开反而更「开箱即用」
const collapsed = ref(false)
const showAdvanced = ref(false)

function syncDraft(): void {
  for (const k of Object.keys(draft)) delete draft[k]
  for (const [k, v] of Object.entries(remote.value)) {
    const m = meta.value[k]
    draft[k] = m?.type === 'string_list' && Array.isArray(v) ? v.join(' ') : v
  }
  dirty.value = false
  saved.value = false
}

watch([remote, meta], syncDraft, { immediate: true, deep: true })

/** 当前应显示的字段（关键项 + 命中的条件项，高级项按需展开）。 */
const visibleKeys = computed(() => {
  if (props.only?.length) {
    // 只取指定字段：按 only 的顺序，忽略目录分级与「高级」开关
    const known = new Set(allKeys.value)
    return props.only.filter((k) => known.has(k))
  }
  return resolveVisibleFields(props.section, allKeys.value, draft, showAdvanced.value)
})
const hiddenCount = computed(() =>
  partial.value ? 0 : allKeys.value.length - visibleKeys.value.length,
)
const canShowAdvanced = computed(() =>
  partial.value ? false : hasHiddenFields(props.section, allKeys.value),
)

/** 收起时在标题右侧露出的关键值摘要，不展开也能确认配置。 */
const summary = computed(() =>
  partial.value
    ? summaryOfFields(props.only ?? [], meta.value, draft)
    : essentialSummary(props.section, meta.value, draft),
)

/** API Key 块只属于完整的 LLM 卡片，别跟着字段级拆分跑到别处 */
const isLlm = computed(() => props.section === 'llm' && !partial.value)

/**
 * 联网检索卡片也要 key（Tavily），同 LLM 的"只写不读明文"范式。
 *
 * 此前这块只认 `llm` —— 而 `[search]` 段连界面都没有，用户**无处配置搜索 key**，
 * 于是"联网检索不可用"永远无解（有实现、无入口）。
 */
const isSearchKey = computed(() => props.section === 'search' && !partial.value)

// 切换 LLM 提供商时，若 base_url/model 为空或仍是 openai 默认值则自动填充预设
watch(
  () => (isLlm.value ? String(draft.provider ?? '') : ''),
  (provider, prev) => {
    if (!provider || provider === prev) return
    const preset = LLM_PRESETS[provider]
    if (!preset) return
    const openaiDefault = LLM_PRESETS.openai
    let changed = false
    const fill = (k: 'base_url' | 'model') => {
      const v = draft[k]
      if (typeof v !== 'string') return
      if (v !== '' && v !== openaiDefault[k]) return
      if (v === preset[k]) return
      draft[k] = preset[k]
      changed = true
    }
    fill('base_url')
    fill('model')
    if (changed) markDirty()
  },
)

// ── S54：文件路径字段 → 系统选择框 ─────────────────────────────────────────
/** 正在选择文件的字段 key（避免重复点、也给按钮一个 busy 态）。 */
const picking = ref('')

/**
 * 为「文件路径」字段调起系统文件框（TTS 参考音频 / 参考转写）。
 *
 * 这些字段此前是纯文本框，用户得手敲绝对路径（还得记斜杠方向），实测极易填错；
 * 现在点一下就能选，路径天然正确。手填仍然可用（选择失败不影响已有值）。
 */
async function pickFile(key: string): Promise<void> {
  const field = meta.value[key]
  const kind = field?.file ?? 'audio'
  picking.value = key
  try {
    const res = await window.yuiro?.pickFiles({
      kind,
      multiple: false,
      title: `选择${field?.label ?? '文件'}`,
    })
    if (res && !res.canceled && res.paths.length) {
      draft[key] = res.paths[0]
      markDirty()
    }
  } catch {
    // 系统对话框异常（极少见）：保留原值，让用户继续手填
  } finally {
    picking.value = ''
  }
}

function markDirty(): void {
  dirty.value = true
  saved.value = false
}

function buildPatch(): Record<string, unknown> {
  const patch: Record<string, unknown> = {}
  for (const [k, m] of Object.entries(meta.value)) {
    const v = draft[k]
    if (m.type === 'int') patch[k] = Math.round(Number(v) || 0)
    else if (m.type === 'float') patch[k] = Number(v) || 0
    else if (m.type === 'bool') patch[k] = Boolean(v)
    else if (m.type === 'string_list') patch[k] = String(v ?? '').split(/\s+/).filter(Boolean)
    else patch[k] = String(v ?? '')
  }
  return patch
}

async function apply(): Promise<void> {
  applying.value = true
  applyError.value = ''
  try {
    await store.applySection(props.section, buildPatch())
    saved.value = true
    setTimeout(() => { saved.value = false }, 2000)
  } catch (e) {
    applyError.value = e instanceof Error ? e.message : String(e)
  } finally {
    applying.value = false
  }
}

// —— LLM API key 设置（只写，绝不显示已保存的明文）——
const keyInput = ref('')
const keyStatus = ref<'set' | 'unset' | 'failed' | null>(null)
const keySaving = ref(false)
const keyError = ref('')

async function refreshKeyStatus(): Promise<void> {
  if (!isLlm.value && !isSearchKey.value) return
  try {
    keyStatus.value = isLlm.value
      ? (await api.getLlmKey()).status
      : (await api.getSearchKey()).status
    keyError.value = ''
  } catch (e) {
    keyError.value = e instanceof Error ? e.message : String(e)
    // S54：失败也要给出**结论**。此前只写 keyError，徽标停在「读取中…」——
    // 用户看到的是"一直在读"而不是"读取失败"，无从判断是引擎没连上还是鉴权被拒。
    keyStatus.value = 'failed'
  }
}

async function saveKey(): Promise<void> {
  const key = keyInput.value.trim()
  if (!key) return
  keySaving.value = true
  keyError.value = ''
  try {
    keyStatus.value = isLlm.value
      ? (await api.setLlmKey(key)).status
      : (await api.setSearchKey(key)).status
    keyInput.value = ''
  } catch (e) {
    keyError.value = e instanceof Error ? e.message : String(e)
  } finally {
    keySaving.value = false
  }
}

onMounted(refreshKeyStatus)

/**
 * hint 来自引擎 FIELD_META，这里是**纯文本插值**（本组件不解析 markdown）。
 * 若文案里带了 `**加粗**` 或反引号，页面上会直接露出星号（很突兀）。
 * 引擎侧已统一改成纯文本，这里再兜一层：剥掉强调标记，
 * 这样连着没重启的旧引擎 / 以后误写 markdown 也不会变丑。
 */
function plainHint(text: string): string {
  return text.replace(/\*\*|`/g, '')
}
</script>

<template>
  <div class="sf-card">
    <div class="sf-head" @click="!dirty && (collapsed = !collapsed)">
      <Icon
        class="sf-chevron"
        :class="{ open: !collapsed }"
        icon="solar:alt-arrow-right-bold"
        width="14" />
      <div class="sf-heading">
        <h3 class="sf-title">{{ cardTitle }}</h3>
        <p v-if="cardSubtitle" class="sf-subtitle">{{ cardSubtitle }}</p>
      </div>
      <span v-if="dirty" class="pill pill-warn">未保存</span>
      <span v-else-if="saved" class="pill pill-ok">已保存</span>
      <span v-else-if="collapsed && summary" class="sf-summary" :title="summary">{{ summary }}</span>
    </div>

    <template v-if="!collapsed">
      <div class="sf-body">
        <div v-for="key in visibleKeys" :key="key" class="sf-row">
          <label class="sf-label" :for="`${section}-${key}`">
            <!-- 单字段卡隐去与卡标题重复的字段名；但若连 hint 都没有，就必须留着
                 （否则整行一个字都没有，用户不知道该填什么） -->
            <span v-if="!hideRowLabel || !meta[key].hint" class="sf-label-text">{{ meta[key].label }}</span>
            <span v-if="meta[key].hint" class="sf-hint">{{ plainHint(meta[key].hint) }}</span>
          </label>

          <div class="sf-control">
            <!-- bool -->
            <button
              v-if="meta[key].type === 'bool'"
              type="button"
              class="sf-switch"
              :class="{ on: Boolean(draft[key]) }"
              @click="draft[key] = !draft[key]; markDirty()">
              <span class="sf-switch-thumb"></span>
            </button>

            <!-- select -->
            <select
              v-else-if="meta[key].type === 'select'"
              :id="`${section}-${key}`"
              v-model="draft[key]"
              class="sf-input"
              @change="markDirty">
              <option v-for="opt in meta[key].options" :key="opt" :value="opt">{{ opt }}</option>
            </select>

            <!-- number -->
            <input
              v-else-if="meta[key].type === 'int' || meta[key].type === 'float'"
              :id="`${section}-${key}`"
              v-model.number="draft[key]"
              type="number"
              class="sf-input sf-input-num"
              :min="meta[key].min"
              :max="meta[key].max"
              :step="meta[key].step ?? (meta[key].type === 'int' ? 1 : 0.05)"
              @input="markDirty" />

            <!-- S54：文件路径（TTS 参考音频 / 参考转写）→ 输入框 + 系统选择框 -->
            <div v-else-if="meta[key].file" class="sf-pick">
              <input
                :id="`${section}-${key}`"
                v-model="draft[key]"
                type="text"
                class="sf-input"
                placeholder="点右侧「选择文件」，也可手填路径"
                @input="markDirty" />
              <button
                type="button"
                class="btn sf-pick-btn"
                :disabled="picking === key"
                @click="pickFile(key)">
                <Icon icon="solar:folder-open-bold" width="12" />
                {{ picking === key ? '选择中…' : '选择文件' }}
              </button>
            </div>

            <!-- text / password / string_list -->
            <input
              v-else
              :id="`${section}-${key}`"
              v-model="draft[key]"
              :type="meta[key].secret ? 'password' : 'text'"
              class="sf-input"
              :placeholder="meta[key].type === 'string_list' ? '以空格分隔' : ''"
              @input="markDirty" />
          </div>
        </div>
      </div>

      <FishKeySettings v-if="section === 'tts' && draft.provider === 'fish'" />

      <!-- 高级字段开关：默认收起，避免参数淹没用户 -->
      <button
        v-if="canShowAdvanced"
        class="sf-advanced-toggle"
        @click="showAdvanced = !showAdvanced">
        {{ showAdvanced ? '收起高级项' : `显示高级项（${hiddenCount}）` }}
      </button>

      <!-- API Key：独立块，只写不读明文（LLM 与联网检索同范式，key 都进 keychain） -->
      <div v-if="isLlm || isSearchKey" class="sf-key">
        <div class="sf-key-head">
          <span class="sf-key-label">{{ isSearchKey ? 'DeepSeek Search API Key' : 'API Key' }}</span>
          <span
            class="pill"
            :class="keyStatus === 'set' ? 'pill-ok' : keyStatus === 'failed' ? 'pill-err' : 'pill-warn'">
            {{
              keyStatus === 'set'
                ? '已设置'
                : keyStatus === 'unset'
                  ? '未设置'
                  : keyStatus === 'failed'
                    ? '读取失败'
                    : '读取中…'
            }}
          </span>
        </div>
        <div class="sf-key-form">
          <input
            v-model="keyInput"
            type="password"
            class="sf-input"
            placeholder="粘贴 API Key"
            @keydown.enter="saveKey" />
          <button class="btn btn-primary" :disabled="keySaving || !keyInput.trim()" @click="saveKey">
            {{ keySaving ? '保存中…' : '保存' }}
          </button>
        </div>
        <p v-if="isSearchKey" class="sf-hint">
          key 只存系统凭据库（keychain），<b>不写进配置文件</b>；保存后会自动重建工具注册，
          之后聊天坞的联网开关才真正可用。
        </p>
        <p v-if="keyError" class="sf-error">{{ keyError }}</p>
      </div>

      <div class="sf-foot">
        <span v-if="applyError" class="sf-error">{{ applyError }}</span>
        <span v-else-if="dirty" class="sf-foot-hint">有改动未保存</span>
        <span v-else></span>
        <button class="btn btn-primary" :disabled="!dirty || applying || store.saving" @click="apply">
          {{ applying ? '保存中…' : '保存' }}
        </button>
      </div>
    </template>
  </div>
</template>

<style scoped>
.sf-card {
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  background: var(--card);
  overflow: hidden;
  box-shadow: var(--shadow-soft);
}

.sf-head {
  display: flex;
  align-items: flex-start;
  /* 空间不足时让徽标/摘要换行，避免把卡片标题压成一字一列 */
  flex-wrap: wrap;
  gap: 10px;
  padding: 14px 18px;
  border-bottom: 1px solid var(--border);
  background: var(--card-head);
  cursor: pointer;
  user-select: none;
}
.sf-chevron {
  color: var(--muted);
  flex-shrink: 0;
  margin-top: 3px;
  transition: transform var(--dur-fast) var(--ease-out);
}
.sf-chevron.open { transform: rotate(90deg); }
/* 给标题一个不可再缩的下限：宁可右侧徽标换行，也不让中文竖排 */
.sf-heading { flex: 1 1 200px; min-width: 200px; }

/* 收起时的关键值摘要：等宽小字 + 省略号，不抢标题的视觉重量 */
.sf-summary {
  flex-shrink: 0;
  max-width: 42%;
  font-size: 11.5px;
  color: var(--muted);
  font-family: ui-monospace, monospace;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.sf-title { margin: 0; font-size: 14px; font-weight: 600; }
.sf-subtitle {
  margin: 3px 0 0;
  font-size: 11.5px;
  color: var(--muted);
  line-height: 1.5;
}

.sf-body { padding: 4px 18px; }
.sf-row {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 11px 0;
  border-bottom: 1px solid var(--border-soft);
}
.sf-row:last-child { border-bottom: none; }

.sf-label { flex: 1; display: flex; flex-direction: column; gap: 3px; min-width: 0; }
.sf-label-text { font-size: 13px; }
.sf-hint { font-size: 11px; color: var(--muted); line-height: 1.45; }

.sf-control { width: 230px; display: flex; justify-content: flex-end; flex-shrink: 0; }
.sf-input {
  width: 100%;
  padding: 7px 11px;
  border-radius: var(--radius-sm);
  border: 1px solid var(--border);
  background: var(--input);
  color: var(--text);
  font-size: 13px;
  outline: none;
  font-family: inherit;
  transition: border-color var(--dur-fast) ease;
}
.sf-input:focus { border-color: var(--accent); }
.sf-input-num { width: 120px; text-align: right; }

/* S54：文件路径字段（输入框 + 选择按钮） */
.sf-pick { display: flex; align-items: center; gap: 8px; width: 100%; }
.sf-pick .sf-input { flex: 1; min-width: 0; }
.sf-pick-btn {
  display: inline-flex; align-items: center; gap: 5px; flex-shrink: 0;
  padding: 6px 11px; font-size: 12.5px; white-space: nowrap;
}
.sf-pick-btn:disabled { opacity: 0.55; cursor: default; }

.sf-switch {
  position: relative;
  width: 42px;
  height: 23px;
  border-radius: 999px;
  border: none;
  background: var(--border);
  cursor: pointer;
  transition: background var(--dur-fast);
}
.sf-switch.on { background: var(--accent); }
.sf-switch-thumb {
  position: absolute;
  top: 2px;
  left: 2px;
  width: 19px;
  height: 19px;
  border-radius: 50%;
  background: #fff;
  transition: transform var(--dur-fast);
}
.sf-switch.on .sf-switch-thumb { transform: translateX(19px); }

.sf-advanced-toggle {
  display: block;
  width: 100%;
  padding: 8px 18px;
  border: none;
  border-top: 1px solid var(--border-soft);
  background: transparent;
  color: var(--muted);
  font-size: 11.5px;
  font-family: inherit;
  text-align: left;
  cursor: pointer;
}
.sf-advanced-toggle:hover { background: var(--btn-hover-bg); color: var(--text); }

.sf-key { padding: 14px 18px; border-top: 1px solid var(--border-soft); }
.sf-key-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px; }
.sf-key-label { font-size: 12px; font-weight: 600; }
.sf-key-form { display: flex; gap: 8px; }
.sf-key-form .sf-input { flex: 1; }

.sf-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 12px 18px;
  border-top: 1px solid var(--border);
  background: var(--card-head);
}
.sf-foot-hint { font-size: 12px; color: var(--warn); }
.sf-error { font-size: 12px; color: var(--err); }
</style>
