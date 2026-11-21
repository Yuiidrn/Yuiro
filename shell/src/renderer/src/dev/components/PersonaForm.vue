<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { useConfigStore } from '../stores/config'
import type { FieldValue } from '@shared'

const store = useConfigStore()

/** persona 段当前值（标量字段；emotion_hints/expression_map 不在本页编辑）。 */
const remote = computed<Record<string, FieldValue>>(() => store.sections.persona ?? {})

/**
 * 本页只管「她是谁、怎么说话」——
 * 音色(voice) 已移入「声音」页、模型(model_path) 移入「外观」页、
 * 记忆主体(memory_subject) 移入「记忆」页，避免同一段配置散落在不相关的地方。
 */
const draft = reactive({
  name: '',
  display_name: '',
  system_prompt: '',
  persona_prompt: '',
})
const dirty = ref(false)
const applying = ref(false)
const applyError = ref('')
const saved = ref(false)

/**
 * 提示词的**实际生效内容**：配置里写了就用配置的，留空则回退引擎内置默认
 * （内置文案由引擎通过 /api/config 的 text_defaults 一并回传）。
 *
 * 以前这里直接读配置值：`system_prompt` 在 config.toml 里是空串，于是输入框一片空白，
 * 看起来像"没加载出来"——用户根本没法在"当前实际在用的那份"上调整。
 * 现在字段里显示的就是引擎真正在用的文案，来源另用角标标明。
 */
function effective(field: 'system_prompt' | 'persona_prompt'): string {
  return store.effectiveText('persona', field)
}

function sourceOf(field: 'system_prompt' | 'persona_prompt'): 'config' | 'builtin' | 'none' {
  return store.textSource('persona', field)
}

/** 清空该字段 → 保存后引擎回退内置默认（角标会重新显示回内置来源）。 */
function resetToBuiltin(field: 'system_prompt' | 'persona_prompt'): void {
  draft[field] = ''
  markDirty()
}

function syncDraft(): void {
  draft.name = String(remote.value.name ?? '')
  draft.display_name = String(remote.value.display_name ?? '')
  draft.system_prompt = effective('system_prompt')
  draft.persona_prompt = effective('persona_prompt')
  dirty.value = false
  saved.value = false
}

watch(remote, syncDraft, { immediate: true, deep: true })

function markDirty(): void {
  dirty.value = true
  saved.value = false
}

async function apply(): Promise<void> {
  applying.value = true
  applyError.value = ''
  try {
    await store.applySection('persona', {
      name: draft.name,
      display_name: draft.display_name,
      system_prompt: draft.system_prompt,
      persona_prompt: draft.persona_prompt,
    })
    saved.value = true
    setTimeout(() => { saved.value = false }, 2000)
  } catch (e) {
    applyError.value = e instanceof Error ? e.message : String(e)
  } finally {
    applying.value = false
  }
}
</script>

<template>
  <div class="persona">
    <div class="persona-head">
      <div>
        <h3 class="persona-title">人设</h3>
        <p class="persona-hint">
          身份、音色、情绪文案与 Live2D 模型统一由此处配置，保存后即时生效（记忆主体需重启引擎生效）。
        </p>
      </div>
    </div>

    <div class="persona-card">
      <div class="field-row">
        <label class="field-label">
          内部名
          <code class="field-key">name</code>
          <span class="field-hint">提示词中自称的名字（英文）</span>
        </label>
        <div class="field-control">
          <input v-model="draft.name" class="input" @input="markDirty" />
        </div>
      </div>

      <div class="field-row">
        <label class="field-label">
          展示名
          <code class="field-key">display_name</code>
          <span class="field-hint">调试台 / 图鉴展示用中文名</span>
        </label>
        <div class="field-control">
          <input v-model="draft.display_name" class="input" @input="markDirty" />
        </div>
      </div>

      <div class="field-row field-row-col">
        <label class="field-label">
          系统提示词
          <code class="field-key">system_prompt</code>
          <span class="field-hint">身份锚定 + 行为红线 + 工具调用铁律（不含性格/语气）</span>
        </label>
        <div class="field-meta">
          <span v-if="!draft.system_prompt" class="pill pill-warn">空 → 保存后回退内置默认</span>
          <template v-else-if="sourceOf('system_prompt') === 'builtin'">
            <span class="pill pill-mute">当前显示的是引擎内置默认文案</span>
            <span v-if="dirty" class="pill pill-warn">已修改，保存后写入配置</span>
          </template>
          <span v-else class="pill pill-ok">已写入 config.toml</span>
          <button
            v-if="sourceOf('system_prompt') === 'config'"
            class="src-btn"
            title="清空该字段：保存后引擎回退为内置默认文案"
            @click="resetToBuiltin('system_prompt')">
            清空并回退内置
          </button>
        </div>
        <textarea
          v-model="draft.system_prompt"
          class="input textarea"
          rows="4"
          @input="markDirty" />
      </div>

      <div class="field-row field-row-col">
        <label class="field-label">
          人设提示词
          <code class="field-key">persona_prompt</code>
          <span class="field-hint">性格、语气、说话风格、emoji 铁律等角色扮演内容</span>
        </label>
        <div class="field-meta">
          <span v-if="!draft.persona_prompt" class="pill pill-warn">空 → 保存后回退内置默认</span>
          <template v-else-if="sourceOf('persona_prompt') === 'builtin'">
            <span class="pill pill-mute">当前显示的是引擎内置默认文案</span>
            <span v-if="dirty" class="pill pill-warn">已修改，保存后写入配置</span>
          </template>
          <span v-else class="pill pill-ok">已写入 config.toml</span>
          <button
            v-if="sourceOf('persona_prompt') === 'config'"
            class="src-btn"
            title="清空该字段：保存后引擎回退为内置默认文案"
            @click="resetToBuiltin('persona_prompt')">
            清空并回退内置
          </button>
        </div>
        <textarea
          v-model="draft.persona_prompt"
          class="input textarea"
          rows="6"
          @input="markDirty" />
      </div>

      <div class="persona-foot">
        <span v-if="dirty" class="dirty-hint">● 有未保存修改</span>
        <span v-else-if="saved" class="saved-hint">✓ 已保存并即时生效</span>
        <span v-else></span>
        <span v-if="applyError" class="apply-error">{{ applyError }}</span>
        <button class="btn btn-primary" :disabled="!dirty || applying || store.saving" @click="apply">
          {{ applying ? '保存中…' : '应用并保存' }}
        </button>
      </div>
    </div>

    <p class="persona-note">
      <strong>关于提示词：</strong>两个输入框里显示的都是<strong>当前实际生效</strong>的文案。
      配置里留空时引擎会用它自带的默认文案 —— 这时字段里显示的就是那份内置文案（角标标明来源），
      你可以直接在上面改。一旦保存，内容就写进 <code>config.toml</code>，
      之后引擎内置默认再有更新也不再影响你（配置优先）；想退回内置文案点「清空并回退内置」。
    </p>

    <p class="persona-note">
      情绪文案（emotion_hints）与情绪→表情映射（expression_map）以 TOML 子表存储，仅引擎读取；
      如需修改请编辑 <code>engine/config.toml</code> 的 <code>[persona.emotion_hints]</code> /
      <code>[persona.expression_map]</code>。
      想把某个<strong>表演</strong>（庆祝 / 惊讶 / 打招呼…）的表情与动作单独搭配，请到「外观」页的
      「表现档案」卡片里点选，无需手改 TOML。
    </p>
  </div>
</template>

<style scoped>
.persona { max-width: 760px; margin: 0 auto; }
.persona-head { margin-bottom: 16px; }
.persona-title { margin: 0 0 4px; font-size: 16px; font-weight: 600; }
.persona-hint { margin: 0; font-size: 12px; color: var(--muted); line-height: 1.5; }

.persona-card {
  border: 1px solid var(--border);
  border-radius: 14px;
  background: var(--card);
  overflow: hidden;
}

.field-row {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 12px 16px;
  border-bottom: 1px solid var(--border-soft);
}
.field-row:last-of-type { border-bottom: none; }
.field-row-col { flex-direction: column; align-items: stretch; }
.field-label { flex: 1; display: flex; flex-direction: column; gap: 2px; font-size: 13px; }

/* 提示词字段的来源角标行（显示的是配置值还是引擎内置默认） */
.field-meta { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin: 4px 0 2px; }
.src-btn {
  padding: 3px 10px; border-radius: 999px;
  border: 1px dashed var(--border); background: transparent;
  color: var(--muted); font-size: 11.5px; font-family: inherit; cursor: pointer;
}
.src-btn:hover { background: var(--btn-hover-bg); color: var(--text); border-color: var(--accent); }
.field-key { font-size: 11px; color: var(--muted); font-family: ui-monospace, monospace; }
.field-hint { font-size: 11px; color: var(--muted); line-height: 1.4; }
.field-control { width: 320px; flex-shrink: 0; }
.field-row-col .field-control { width: 100%; }

.input {
  width: 100%;
  padding: 8px 10px;
  border-radius: 8px;
  border: 1px solid var(--border);
  background: var(--input);
  color: var(--text);
  font-size: 13px;
  outline: none;
  font-family: inherit;
}
.input:focus { border-color: var(--accent); }
.textarea { resize: vertical; line-height: 1.5; }

.persona-foot {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 16px;
  border-top: 1px solid var(--border);
}
.dirty-hint { color: var(--warn); font-size: 12px; }
.saved-hint { color: var(--ok); font-size: 12px; }
.apply-error { color: var(--err); font-size: 12px; flex: 1; }

.btn { padding: 7px 14px; border-radius: 8px; border: none; cursor: pointer; font-size: 13px; }
.btn-primary { background: var(--accent); color: #fff; }
.btn-primary:disabled { opacity: 0.4; cursor: default; }

.persona-note { margin-top: 14px; font-size: 12px; color: var(--muted); line-height: 1.5; }
.persona-note code { font-family: ui-monospace, monospace; color: var(--text); }
</style>
