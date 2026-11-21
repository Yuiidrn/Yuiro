<script setup lang="ts">
import { computed, ref } from 'vue'
import type { Live2DManifest, ModelReport } from '@shared'
import { EXPRESSION_SLOTS, MOTION_SLOTS } from '@shared'
import { useConfigStore } from '../stores/config'

/**
 * 模型体检 / 导入（调试台「外观」页）
 *
 * 为什么需要：换模型出的问题有一半是**资源包本身不齐或命名不规范** —— 缺贴图、
 * 引用大小写不匹配（本机 Windows 能读、打包后 404）、中文/空格文件名（URL 未编码
 * → 404）、moc3 版本超出 SDK 支持范围。加载失败时这些只表现成一句含糊的报错甚至
 * 一片空白（shizuku 那次排查花了一整轮）。
 *
 * 这里把它们摊成可读报告，并支持把外部模型目录一键导入：
 *   体检 → 复制进 live2d 资源目录 → 登记 model_dict.json（写不了也不影响加载）。
 *
 * 纯读 + 复制，不改动已有模型；导入时目录名会被强制成 ASCII（就地消掉 404 隐患）。
 */
const store = useConfigStore()

const currentPath = computed(() => String(store.sections?.persona?.model_path ?? ''))
const report = ref<ModelReport | null>(null)
/** 语义槽位覆盖（S53）：这个模型能被 Agent 链路"用起来"多少 */
const manifest = ref<Live2DManifest | null>(null)
const busy = ref(false)
const error = ref('')
const importMsg = ref('')
const importOk = ref(false)

const errors = computed(() => report.value?.issues.filter(i => i.level === 'error') ?? [])
const warns = computed(() => report.value?.issues.filter(i => i.level === 'warn') ?? [])
const motionTotal = computed(
  () => report.value?.info.motionGroups.reduce((s, g) => s + g.count, 0) ?? 0,
)
const textureMb = computed(
  () => Number((report.value?.info.textures.reduce((s, t) => s + t.mb, 0) ?? 0).toFixed(1)),
)

/** 槽位覆盖：count > 0 表示该语义能被 Agent 链路触发（自动推断或档案配置）。 */
const exprSlots = computed(() =>
  EXPRESSION_SLOTS.map((slot) => ({ slot, count: manifest.value?.coverage.expression[slot] ?? 0 })),
)
const motionSlots = computed(() =>
  MOTION_SLOTS.map((slot) => ({ slot, count: manifest.value?.coverage.motion[slot] ?? 0 })),
)
const missingSlots = computed(
  () => [...exprSlots.value, ...motionSlots.value].filter((x) => !x.count).length,
)

async function validate(path: string): Promise<void> {
  const p = path.trim()
  if (!p) return
  busy.value = true
  error.value = ''
  importMsg.value = ''
  try {
    report.value = await window.yuiro.validatePetModel(p)
    manifest.value = await window.yuiro.inspectPetModel(p).catch(() => null)
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    busy.value = false
  }
}

/** 导入外部目录（后端会再体检一次；不通过不会复制）。 */
async function importDir(): Promise<void> {
  busy.value = true
  error.value = ''
  importMsg.value = ''
  try {
    const picked = await window.yuiro.pickModelDir()
    if (picked.canceled || !picked.path) return
    const res = await window.yuiro.importPetModel(picked.path)
    report.value = res.report
    importOk.value = res.ok
    importMsg.value = res.message
    if (res.ok) {
      // 通知上方「桌宠形象」卡重新扫盘，新模型立刻出现在列表里
      window.dispatchEvent(new CustomEvent('yuiro:models-changed'))
    }
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div class="bubble card-narrow mh">
    <div class="row-between">
      <div>
        <h3 class="bubble-title">模型体检 / 导入</h3>
        <p class="hint">
          检查模型资源是否完整规范（引用缺失、大小写不匹配、中文文件名、moc3 版本），
          并把外部模型目录一键接入。导入后模型会出现在上方的「桌宠形象」列表里。
        </p>
      </div>
      <div class="mh-actions">
        <button class="btn" :disabled="busy || !currentPath" @click="validate(currentPath)">
          体检当前模型
        </button>
        <button class="btn btn-primary" :disabled="busy" @click="importDir">
          导入模型目录…
        </button>
      </div>
    </div>

    <p v-if="error" class="mh-msg mh-err">{{ error }}</p>
    <p v-if="importMsg" class="mh-msg" :class="importOk ? 'mh-ok' : 'mh-err'">{{ importMsg }}</p>

    <template v-if="report">
      <div class="mh-head">
        <span class="pill" :class="report.ok ? 'pill-ok' : 'pill-err'">
          {{ report.ok ? '通过' : '有问题' }}
        </span>
        <span class="mh-path" :title="report.model3">{{ report.model3 || report.dir }}</span>
      </div>

      <div class="mh-grid">
        <div><span class="mh-k">moc3</span><span class="mh-v">v{{ report.info.mocVersion }} · {{ report.info.moc || '—' }}</span></div>
        <div><span class="mh-k">贴图</span><span class="mh-v">{{ report.info.textures.length }} 张 / {{ textureMb }} MB</span></div>
        <div><span class="mh-k">表情</span><span class="mh-v">{{ report.info.expressions.length ? report.info.expressions.join('、') : '无' }}</span></div>
        <div><span class="mh-k">动作</span><span class="mh-v">{{ motionTotal }} 个 · {{ report.info.motionGroups.map(g => `${g.group}(${g.count})`).join(' ') || '无' }}</span></div>
        <div><span class="mh-k">参数</span><span class="mh-v">{{ report.info.params || '—' }}</span></div>
        <div><span class="mh-k">物理/姿势</span><span class="mh-v">{{ report.info.physics ? '有' : '无' }} / {{ report.info.pose ? '有' : '无' }}</span></div>
      </div>

      <!-- 语义槽位覆盖：能不能被 Agent 链路正确驱动，看这一块 -->
      <div v-if="manifest" class="mh-slots">
        <div class="mh-slot-group">
          <span class="mh-k">表情槽位</span>
          <div class="mh-chips">
            <span
              v-for="x in exprSlots"
              :key="x.slot"
              class="mh-chip"
              :class="{ miss: !x.count }"
              :title="x.count ? `${x.count} 个候选` : '没有可映射的表情'">
              {{ x.slot }}<em v-if="x.count">{{ x.count }}</em>
            </span>
          </div>
        </div>
        <div class="mh-slot-group">
          <span class="mh-k">动作槽位</span>
          <div class="mh-chips">
            <span
              v-for="x in motionSlots"
              :key="x.slot"
              class="mh-chip"
              :class="{ miss: !x.count }"
              :title="x.count ? `${x.count} 个候选` : '没有可映射的动作'">
              {{ x.slot }}<em v-if="x.count">{{ x.count }}</em>
            </span>
          </div>
        </div>
        <p class="hint">
          <template v-if="missingSlots">
            {{ missingSlots }} 个槽位没有候选 —— 该语义在当前模型上会"只演表情"或跳过；
            可在「表现档案」点「按模型自动生成」或手配档案补上。
          </template>
          <template v-else>10 个动作槽位 / 8 个表情槽位都有候选，Agent 链路可完整驱动。</template>
          <template v-if="manifest.coverage.unmappedExpressionCount || manifest.coverage.unmappedMotionCount">
            <br />另有 {{ manifest.coverage.unmappedExpressionCount }} 个表情 /
            {{ manifest.coverage.unmappedMotionCount }} 个动作未能从名字推断语义（不影响其它槽位）。
          </template>
        </p>
      </div>

      <ul v-if="errors.length" class="mh-issues">
        <li v-for="(it, i) in errors" :key="'e' + i" class="mh-issue mh-err">✕ {{ it.text }}</li>
      </ul>
      <ul v-if="warns.length" class="mh-issues">
        <li v-for="(it, i) in warns" :key="'w' + i" class="mh-issue mh-warn">! {{ it.text }}</li>
      </ul>
      <p v-if="!errors.length && !warns.length" class="hint">没有发现问题。</p>
    </template>
  </div>
</template>

<style scoped>
.mh { max-width: 760px; }
.mh-actions { display: flex; gap: 8px; flex-shrink: 0; }
.mh-msg { margin: 10px 0 0; font-size: 12px; }
.mh-err { color: var(--err); }
.mh-ok { color: var(--ok); }

.mh-head { display: flex; align-items: center; gap: 8px; margin: 12px 0 8px; }
.mh-path {
  font-size: 11.5px;
  color: var(--muted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.mh-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 6px 12px;
  padding: 10px;
  border-radius: var(--radius-md);
  background: var(--card-head);
  font-size: 12px;
}
.mh-grid > div { display: flex; gap: 8px; min-width: 0; }
.mh-k { flex: none; width: 56px; color: var(--muted); }
.mh-v { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

/* 语义槽位覆盖 */
.mh-slots {
  margin-top: 10px;
  padding: 10px;
  border-radius: var(--radius-md);
  background: var(--card-head);
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.mh-slot-group { display: flex; gap: 8px; align-items: flex-start; }
.mh-chips { display: flex; flex-wrap: wrap; gap: 4px; flex: 1; min-width: 0; }
.mh-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 7px;
  border-radius: 999px;
  border: 1px solid var(--border);
  font-size: 11px;
}
.mh-chip em { font-style: normal; font-weight: 600; color: var(--accent); }
.mh-chip.miss { opacity: 0.45; border-style: dashed; }

.mh-issues { margin: 10px 0 0; padding: 0; list-style: none; display: flex; flex-direction: column; gap: 4px; }
.mh-issue { font-size: 12px; line-height: 1.5; }
.mh-warn { color: var(--muted); }

@media (max-width: 720px) {
  .mh-grid { grid-template-columns: 1fr; }
}
</style>
