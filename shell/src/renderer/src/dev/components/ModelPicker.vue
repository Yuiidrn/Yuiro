<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { Icon } from '@iconify/vue'
import { useConfigStore } from '../stores/config'
import { api } from '../api'
import { fetchModelDetail, type MotionGroup } from '../modelDetail'

/**
 * 桌宠形象（调试台「外观」页）
 *
 * 这一个卡片包办桌宠的全部形象调试，无需再记任何快捷键：
 *   · 选模型 —— 写入引擎配置 persona.model_path（唯一真相源）并让桌宠窗口立即换装
 *   · 试动作 / 预览表情 —— 从所选模型的 model3.json 动态解析
 *   · 表演库 —— 引擎配置驱动的成套表演，点一下即触发
 *
 * 模型列表有两个来源，合并展示：
 *   1) public/live2d/model_dict.json 注册表（有中文名 / 作者 / 授权信息）
 *   2) 主进程扫描 public/live2d 下所有 *.model3.json —— 用户自己丢进去的模型会自动出现
 */
const store = useConfigStore()

interface ModelEntry {
  key: string
  name: string
  author?: string
  modelPath: string
  license?: string
  /**
   * 隐藏的变体：仍登记在册（用于屏蔽磁盘扫描结果），但不出现在可选列表。
   * 典型场景：一个模型目录里放了 5 个外观变体，只希望暴露主模型。
   */
  hidden?: boolean
}

interface ModelDict {
  models?: Record<string, Omit<ModelEntry, 'key'>>
}

/** 合并后的模型选项（注册表 + 扫描结果）。 */
interface ModelOption {
  path: string
  name: string
  author?: string
  license?: string
  /** 是否在 model_dict.json 里登记过（未登记只显示路径，但一样能用） */
  registered: boolean
}

/* 模型明细（动作组 / 表情）的解析收在 ../modelDetail，与「表演搭配」编辑器共用同一份逻辑。 */

const registry = ref<ModelEntry[]>([])
const scanned = ref<{ path: string; registeredHint: string }[]>([])
const motions = ref<MotionGroup[]>([])
const expressions = ref<string[]>([])

const loading = ref(true)
const applying = ref(false)
const applied = ref(false)
const failed = ref('')
const error = ref('')
const showGuide = ref(false)
/** 软提示（不是失败）：比如"已换装但配置没写回去" */
const notice = ref('')
/** 最近一次试播的内容（点了没反馈最容易让人误判成"坏了"） */
const lastPreview = ref('')
/** 引擎是否在线（null = 还没测出来）。离线不影响试播/换装，但影响配置写回。 */
const engineOnline = ref<boolean | null>(null)
let retryTimer = 0
let lastCheckMs = 0
/** 离线时快速重试（恢复后立刻停）。 */
const OFFLINE_RETRY_MS = 5000
/** 窗口重新聚焦后，距上次探测超过这么久才复查一次（别让切窗口变成刷接口）。 */
const FOCUS_RECHECK_MS = 30000

/**
 * 探测引擎是否在线。
 *
 * ★ S54：**不再定时无条件轮询**。此前这里每 15s 发一次 `GET /api/status`，
 * 只要「外观」页开着就永远在刷 —— 实测把引擎日志刷满（用户反馈"不要这么频繁"）。
 * 现在：
 *   · **在线时完全不轮询**（真正需要它时请求会失败，界面自然能暴露掉线）；
 *   · 只有**离线**才每 5s 重试，恢复后立刻停；
 *   · 窗口重新聚焦/可见时按需复查一次（引擎可能在页面打开之后才启动）。
 */
async function checkEngine(): Promise<void> {
  lastCheckMs = Date.now()
  try {
    await api.getStatus()
    engineOnline.value = true
    if (retryTimer) { clearTimeout(retryTimer); retryTimer = 0 }
  } catch {
    engineOnline.value = false
    scheduleEngineRetry()
  }
}

function scheduleEngineRetry(): void {
  if (retryTimer) return
  retryTimer = window.setTimeout(() => {
    retryTimer = 0
    void checkEngine()
  }, OFFLINE_RETRY_MS)
}

/** 窗口重新可见/聚焦：隔一段时间才复查一次。 */
function onWindowFocus(): void {
  if (document.visibilityState === 'hidden') return
  if (Date.now() - lastCheckMs < FOCUS_RECHECK_MS) return
  void checkEngine()
}

const currentPath = computed(() => String(store.sections?.persona?.model_path ?? ''))

/**
 * 注册表优先（有友好名字），扫描到但未登记的补在后面。
 * `hidden: true` 的变体既不进列表，也要**屏蔽扫描结果**里的同一路径。
 */
const options = computed<ModelOption[]>(() => {
  const hiddenPaths = new Set(registry.value.filter((m) => m.hidden).map((m) => m.modelPath))
  const list: ModelOption[] = registry.value
    .filter((m) => !m.hidden && scanned.value.some(s=>s.path===m.modelPath))
    .map((m) => ({
      path: m.modelPath,
      name: m.name,
      author: m.author,
      license: m.license,
      registered: true,
    }))
  const known = new Set(list.map((o) => o.path))
  for (const s of scanned.value) {
    if (known.has(s.path) || hiddenPaths.has(s.path)) continue
    list.push({ path: s.path, name: s.path.split('/').slice(-2).join('/'), registered: false })
  }
  return list
})

const currentOption = computed(() => options.value.find((o) => o.path === currentPath.value))

/* ---------------------------------------------------------------------------
 * 数据加载
 * ------------------------------------------------------------------------- */

async function loadRegistry(): Promise<void> {
  try {
    const res = await fetch('/live2d/model_dict.json')
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    const data = (await res.json()) as ModelDict
    registry.value = Object.entries(data.models ?? {}).map(([key, v]) => ({ key, ...v }))
  } catch {
    registry.value = []
  }
}

/** 重新扫描磁盘上的模型（用户新丢进来的文件夹会被发现）。 */
async function rescan(): Promise<void> {
  try {
    scanned.value = (await window.yuiro?.scanLive2dModels?.()) ?? []
  } catch {
    scanned.value = []
  }
}

/**
 * 「模型体检 / 导入」卡导入完新模型后会派发这个同窗口事件 —— 收到就重扫磁盘，
 * 免得用户还得手动刷新调试台才能看到刚导入的模型。
 */
function onModelsChanged(): void {
  void rescan()
}

onMounted(async () => {
  window.addEventListener('yuiro:models-changed', onModelsChanged)
  window.addEventListener('focus', onWindowFocus)
  document.addEventListener('visibilitychange', onWindowFocus)
  await Promise.all([loadRegistry(), rescan()])
  loading.value = false
  // 引擎在线状态：进页面探一次（离线才重试）—— 不做周期性轮询，见 checkEngine 的说明
  void checkEngine()
})

onBeforeUnmount(() => {
  window.removeEventListener('yuiro:models-changed', onModelsChanged)
  window.removeEventListener('focus', onWindowFocus)
  document.removeEventListener('visibilitychange', onWindowFocus)
  if (retryTimer) { clearTimeout(retryTimer); retryTimer = 0 }
})

/** 解析所选模型的 model3.json，列出它自己声明的动作组与表情。 */
async function loadModelDetail(): Promise<void> {
  motions.value = []
  expressions.value = []
  const path = currentPath.value
  const detail = await fetchModelDetail(path)
  if (path !== currentPath.value) return
  motions.value = detail.motions
  expressions.value = detail.expressions
  if (detail.error) error.value = detail.error
}

watch(currentPath, () => { void loadModelDetail() }, { immediate: true })

/* ---------------------------------------------------------------------------
 * 操作
 * ------------------------------------------------------------------------- */

/**
 * 切换模型：通知桌宠窗口立即换装（不依赖引擎）+ 写回配置（持久化 + 让引擎的表现档案跟着切）。
 *
 * 顺序很关键：**先换装，再写配置**。以前是先写配置（PUT 引擎），引擎没启动就直接抛错，
 * 于是整条链路一起判死 —— 表现为"引擎没起时连模型都换不了"。现在换装是硬要求，
 * 写配置是尽力而为：失败只给软提示，不回滚已经换好的模型。
 */
async function chooseModel(path: string): Promise<void> {
  if (!path || path === currentPath.value) return
  applying.value = true
  error.value = ''
  failed.value = ''
  notice.value = ''
  try {
    if (store.character) {
      // 角色模式下先通过 id/revision 校验；旧窗口不能先换新角色外观再保存失败。
      await store.applySection('persona', { model_path: path })
      await window.yuiro?.setPetModel?.(path, store.character.active_id)
      applied.value = true
      return
    }
    await window.yuiro?.setPetModel?.(path)
    applied.value = true
    setTimeout(() => { applied.value = false }, 1800)
    try {
      await store.applySection('persona', { model_path: path })
      engineOnline.value = true
    } catch (e) {
      engineOnline.value = false
      notice.value = `已在桌宠上换装，但没能写回配置（引擎未启动？）：${e instanceof Error ? e.message : String(e)}。引擎重启后可能回落成旧模型。`
    }
  } catch (e) {
    failed.value = e instanceof Error ? e.message : String(e)
  } finally {
    applying.value = false
  }
}

function previewMotion(group: string, index: number): void {
  lastPreview.value = `动作 ${group} #${index}`
  void window.yuiro?.playPetMotion?.(group, index, { characterId: store.character?.active_id, modelPath: currentPath.value })
}

function previewExpression(name: string): void {
  lastPreview.value = `表情 ${name}`
  void window.yuiro?.previewPetExpression?.(name, { characterId: store.character?.active_id, modelPath: currentPath.value })
}
</script>

<template>
  <div class="bubble model-picker">
    <!-- ── 模型选择 ── -->
    <div class="mp-head">
      <div>
        <h3 class="mp-title">桌宠形象</h3>
        <p class="hint">这里只调整当前角色的外观与资源；切换整套大脑、声音和人设请用顶部角色选择器。</p>
      </div>
      <div class="mp-head-pills">
        <span
          class="pill"
          :class="engineOnline === false ? 'pill-warn' : 'pill-mute'"
          :title="engineOnline === false
            ? '引擎未启动：换模型 / 试演 / 试播仍可用，但配置写不回去（重启引擎后可能回落）'
            : '引擎在线：配置修改会即时热重载'">
          {{ engineOnline === false ? '引擎离线' : engineOnline === true ? '引擎在线' : '检测引擎…' }}
        </span>
        <span v-if="applied" class="pill pill-ok">已切换</span>
        <span v-else-if="applying" class="pill pill-mute">切换中…</span>
      </div>
    </div>

    <p v-if="failed" class="mp-err">{{ failed }}</p>
    <p v-else-if="notice" class="mp-notice">{{ notice }}</p>
    <p v-if="error" class="mp-err">{{ error }}</p>
    <p v-if="lastPreview" class="mp-preview">
      正在试：<strong>{{ lastPreview }}</strong>
    </p>

    <div v-if="loading" class="hint">读取模型清单…</div>

    <template v-else>
      <div class="mp-models">
        <button
          v-for="o in options"
          :key="o.path"
          class="mp-model"
          :class="{ on: o.path === currentPath }"
          :disabled="applying"
          @click="chooseModel(o.path)">
          <span class="mp-model-name">{{ o.name }}</span>
          <span v-if="o.author" class="mp-model-author">{{ o.author }}</span>
          <span v-else-if="!o.registered" class="mp-model-author mp-unreg">未登记</span>
          <span v-if="o.path === currentPath" class="mp-model-flag">使用中</span>
        </button>
      </div>

      <p v-if="!options.length" class="hint">
        没有发现任何模型。请把模型文件夹放进 <code>public/live2d/</code> 后点「重新扫描」。
      </p>

      <div class="mp-tools">
        <button class="btn" @click="rescan">
          <Icon icon="solar:refresh-bold" width="13" /> 重新扫描
        </button>
        <button class="mp-guide-toggle" @click="showGuide = !showGuide">
          <Icon
            :icon="showGuide ? 'solar:alt-arrow-down-bold' : 'solar:alt-arrow-right-bold'"
            width="12" />
          如何添加自己的模型
        </button>
      </div>

      <div v-if="showGuide" class="mp-guide">
        <ol>
          <li>
            把模型文件夹放到
            <code>shell/src/renderer/public/live2d/&lt;你的模型名&gt;/</code>
          </li>
          <li>
            文件夹里必须有 <code>*.model3.json</code>，以及它引用的
            <code>.moc3</code>、贴图、动作、表情等文件（保持原目录结构即可）
          </li>
          <li>回到本页点「重新扫描」，新模型会出现在上方列表并可直接选用</li>
          <li>
            （可选）想让列表显示中文名与作者，在
            <code>public/live2d/model_dict.json</code> 里补一条登记；不登记也能用
          </li>
        </ol>
        <p class="mp-guide-note">
          温馨提示：模型请在授权允许的范围内使用，当前列表里的模型授权信息见下方。
        </p>
      </div>

      <p v-if="currentOption?.license" class="mp-license">授权：{{ currentOption.license }}</p>

      <!-- ── 动作 ── -->
      <div class="mp-section">
        <span class="mp-section-title">动作</span>
        <div v-if="motions.length" class="mp-groups">
          <div v-for="g in motions" :key="g.group" class="mp-group">
            <span class="mp-group-name">{{ g.group }}</span>
            <span class="mp-group-count">{{ g.count }} 个</span>
            <div class="mp-chips">
              <button
                v-for="i in g.count"
                :key="i"
                class="mp-chip"
                :title="`试播 ${g.group} #${i}`"
                @click="previewMotion(g.group, i - 1)">
                {{ i }}
              </button>
            </div>
          </div>
        </div>
        <p v-else class="hint">该模型未声明动作。</p>
      </div>

      <!-- ── 表情 ── -->
      <div class="mp-section">
        <span class="mp-section-title">表情</span>
        <div v-if="expressions.length" class="mp-chips">
          <button
            v-for="name in expressions"
            :key="name"
            class="mp-chip mp-chip-wide"
            :title="`预览表情 ${name}`"
            @click="previewExpression(name)">
            {{ name }}
          </button>
        </div>
        <p v-else class="hint">该模型未声明表情。</p>
      </div>

      <!-- 表演（成套的「表情+动作」）统一放在下方「表现档案」卡里编辑与试演。
           这里不再重复一份：两处各渲染一遍列表，改一处漏一处（本项目踩过多次）。 -->
      <p class="hint">
        想配或试<strong>成套表演</strong>（庆祝 / 打招呼…）？用下方「表现档案」卡 ——
        它会按当前模型逐项检查表情与动作是否存在，点不动的表演会直接告诉你缺什么。
      </p>
    </template>
  </div>
</template>

<style scoped>
.model-picker { display: flex; flex-direction: column; gap: 14px; }

.mp-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; }
.mp-head-pills { display: flex; flex-direction: column; align-items: flex-end; gap: 6px; flex-shrink: 0; }
.mp-title { margin: 0 0 4px; font-size: 14px; font-weight: 600; }
.mp-err { margin: 0; font-size: 12px; color: var(--err); }
.mp-notice {
  margin: 0; padding: 8px 10px; border-radius: var(--radius-sm);
  background: color-mix(in srgb, var(--warn) 12%, transparent);
  color: var(--text-soft); font-size: 12px; line-height: 1.6;
}
.mp-preview { margin: 0; font-size: 12px; color: var(--muted); }
.mp-preview strong { color: var(--accent); font-weight: 600; }

/* 模型卡片 */
.mp-models { display: flex; flex-wrap: wrap; gap: 10px; }
.mp-model {
  display: flex; flex-direction: column; gap: 2px; align-items: flex-start;
  padding: 10px 14px; min-width: 150px;
  border: 1px solid var(--border); border-radius: var(--radius-md);
  background: var(--input); color: var(--text);
  font-family: inherit; text-align: left; cursor: pointer;
  transition: border-color var(--dur-fast) ease, background var(--dur-fast) ease;
}
.mp-model:hover:not(:disabled) { border-color: var(--accent); }
.mp-model.on { border-color: var(--accent); background: var(--accent-soft); }
.mp-model:disabled { opacity: 0.6; cursor: default; }
.mp-model-name { font-size: 13px; font-weight: 600; }
.mp-model-author { font-size: 11px; color: var(--muted); }
.mp-unreg { font-style: italic; }
.mp-model-flag { font-size: 10.5px; color: var(--accent); font-weight: 600; }

.mp-tools { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.mp-guide-toggle {
  display: inline-flex; align-items: center; gap: 6px;
  padding: 6px 12px; border-radius: 999px;
  border: 1px dashed var(--border); background: transparent;
  color: var(--muted); font-size: 11.5px; font-family: inherit; cursor: pointer;
}
.mp-guide-toggle:hover { background: var(--btn-hover-bg); color: var(--text); }

.mp-guide {
  padding: 12px 16px; border-radius: var(--radius-md);
  background: var(--card-head); font-size: 12px; color: var(--text-soft); line-height: 1.8;
}
.mp-guide ol { margin: 0; padding-left: 20px; }
.mp-guide code {
  padding: 1px 5px; border-radius: 4px;
  background: var(--input); font-size: 11.5px;
}
.mp-guide-note { margin: 8px 0 0; font-size: 11px; color: var(--muted); }

.mp-license { margin: 0; font-size: 11.5px; color: var(--muted); }

.mp-section { display: flex; flex-direction: column; gap: 8px; }
.mp-section-title {
  font-size: 11.5px; font-weight: 700; color: var(--muted);
  text-transform: uppercase; letter-spacing: 0.07em;
}
.mp-groups { display: flex; flex-direction: column; gap: 8px; }
.mp-group {
  display: flex; align-items: center; flex-wrap: wrap; gap: 8px;
  padding: 8px 10px; border-radius: var(--radius-sm); background: var(--card-head);
}
.mp-group-name { font-size: 12.5px; font-weight: 600; }
.mp-group-count { font-size: 11px; color: var(--muted); }

.mp-chips { display: flex; flex-wrap: wrap; gap: 5px; }
.mp-chip {
  min-width: 24px; padding: 3px 8px;
  border: 1px solid var(--border); border-radius: 999px;
  background: transparent; color: var(--text-soft);
  font-family: ui-monospace, monospace; font-size: 11px; cursor: pointer;
  transition: background var(--dur-fast) ease, color var(--dur-fast) ease;
}
.mp-chip:hover { background: var(--accent-soft); color: var(--accent); border-color: var(--accent); }
.mp-chip-wide { font-family: inherit; }
</style>
