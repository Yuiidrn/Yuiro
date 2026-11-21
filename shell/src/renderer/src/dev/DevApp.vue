<script setup lang="ts">
import { watchSpeechSettings } from '../utils/speechSettingsSignal'
import AppearanceStudio from './components/AppearanceStudio.vue'
import AvatarClickCard from './components/AvatarClickCard.vue'
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { Icon } from '@iconify/vue'
import { useConfigStore } from './stores/config'
import { useStatusStore } from './stores/status'
import { useLogStore } from './stores/logs'
import { api } from './api'
import SectionForm from './components/SectionForm.vue'
import ProviderCard from './components/ProviderCard.vue'
import LogViewer from './components/LogViewer.vue'
import VoiceDebug from './components/VoiceDebug.vue'
import PersonaForm from './components/PersonaForm.vue'
import CharacterPicker from './components/CharacterPicker.vue'
import VoicePicker from './components/VoicePicker.vue'
import ModelPicker from './components/ModelPicker.vue'
import ModelHealth from './components/ModelHealth.vue'
import PerformanceEditor from './components/PerformanceEditor.vue'
import AvatarIdleCard from './components/AvatarIdleCard.vue'
import MemoryManager from './components/MemoryManager.vue'
import MemoryInsights from './components/MemoryInsights.vue'
import DiaryPanel from './components/DiaryPanel.vue'
import SearchStatus from './components/SearchStatus.vue'
import KnowledgePanel from './components/KnowledgePanel.vue'
import TaskPanel from './components/TaskPanel.vue'
import BaselinePanel from './components/BaselinePanel.vue'
import UiRange from './components/UiRange.vue'
import CharacterMotif from '../components/CharacterMotif.vue'
import DetachedUiSettings from './components/DetachedUiSettings.vue'
import { useUiAppearance } from '../composables/useUiAppearance'
import FadeOnHoverNotice from '../components/FadeOnHoverNotice.vue'
import { useFadeOnHoverPref } from '../composables/useFadeOnHoverPref'
import { useContourPref } from '../composables/useContourPref'
import { useSpeechBubblePref } from '../composables/useSpeechBubblePref'
import { useResultCardPref } from '../composables/useResultCardPref'
import { useChatDockPref } from '../composables/useChatDockPref'
import { DEV_TABS, LIMITATIONS, TAB_DESC, TAB_SECTIONS, type DevTab } from './configCatalog'

const configStore = useConfigStore()
const characterUi=useUiAppearance()
watch(()=>configStore.character?.active_id,id=>{if(id)characterUi.setCharacter(id)},{immediate:true})
const contourPref = useContourPref()
const statusStore = useStatusStore()
const logStore = useLogStore()

function onCharacterStorage(event: StorageEvent): void {
  if (event.key === 'yuiro-active-character') void configStore.load()
}
let offSpeechSettings:(()=>void)|null=null
onMounted(() => {
  window.addEventListener('storage', onCharacterStorage)
  offSpeechSettings=watchSpeechSettings(()=>configStore.character?.active_id||'',()=>{
    if(!configStore.hasDraftChanges&&!configStore.saving&&!configStore.switching)void configStore.load()
  })
})
onBeforeUnmount(() => {window.removeEventListener('storage', onCharacterStorage);offSpeechSettings?.()})

/** 拉平后的 tab 清单，用于查标题等。 */
const TAB_ITEMS = DEV_TABS.flatMap((g) => g.items)

/**
 * 组件自检清单。
 * 只保留「后端真有实现」的项 —— 记忆/VAD 两项自检在后端是空壳或与默认配置不匹配，
 * 把它们摆在界面上只会让人误以为功能坏了，故移除（真实检索在「记忆」页）。
 */
const SELF_TESTS: { key: string; title: string; description: string }[] = [
  { key: 'llm', title: 'LLM', description: '发一条测试消息，验证模型连通与响应。' },
  { key: 'asr', title: 'ASR', description: 'faster-whisper 就绪与模型缓存检查。' },
  { key: 'tts', title: 'TTS', description: '当前合成后端出声测试。' },
  { key: 'systemd', title: '系统操作', description: '执行后端与工具连通行检查。' },
]

/* ---------------------------------------------------------------------------
 * 主题：日间 / 夜间（米黄基调）
 * ------------------------------------------------------------------------- */
type Theme = 'light' | 'dark'
const THEME_KEY = 'yuiro-dev-theme'
const theme = ref<Theme>((localStorage.getItem(THEME_KEY) as Theme | null) ?? 'light')
watch(
  theme,
  (t) => {
    document.documentElement.dataset.theme = t
    localStorage.setItem(THEME_KEY, t)
  },
  { immediate: true },
)
function toggleTheme(): void {
  theme.value = theme.value === 'light' ? 'dark' : 'light'
}

/* ---------------------------------------------------------------------------
 * 分组折叠：低频分组（「其他」）默认折起，保持侧栏轻便
 * ------------------------------------------------------------------------- */
const NAV_STATE_KEY = 'yuiro-dev-nav-collapsed'

/** 分组折叠状态：记住上次的展开/收起，避免每次启动都重新点开。 */
function loadCollapsedGroups(): Record<string, boolean> {
  const base = Object.fromEntries(
    DEV_TABS.map((g) => [g.title, !!g.collapsedByDefault]),
  ) as Record<string, boolean>
  try {
    const saved = JSON.parse(localStorage.getItem(NAV_STATE_KEY) ?? '{}') as Record<string, boolean>
    for (const g of DEV_TABS) {
      if (typeof saved[g.title] === 'boolean') base[g.title] = saved[g.title]
    }
  } catch { /* 脏数据 → 用默认折叠状态 */ }
  return base
}

const collapsedGroups = reactive<Record<string, boolean>>(loadCollapsedGroups())

watch(collapsedGroups, () => {
  try { localStorage.setItem(NAV_STATE_KEY, JSON.stringify(collapsedGroups)) } catch { /* ignore */ }
})

function toggleGroup(title: string): void {
  collapsedGroups[title] = !collapsedGroups[title]
}

/* ---------------------------------------------------------------------------
 * 页面切换
 * ------------------------------------------------------------------------- */
/**
 * 主进程用 ?section= 深链打开：settings→大脑、logs→日志、status→总览。
 * 兜底落在「大脑」而不是「总览」——这样「其他」分组能保持默认折起（侧栏轻便），
 * 而总览本身只需一次点击即可到达。
 */
function initialTab(): DevTab {
  const q = new URLSearchParams(window.location.search).get('section')
  if (q === 'logs') return 'logs'
  if (q === 'status') return 'overview'
  return 'brain'
}

const active = ref<DevTab>(initialTab())
const activeLabel = computed(() => TAB_ITEMS.find((i) => i.key === active.value)?.label ?? '')
const activeSections = computed(() => TAB_SECTIONS[active.value] ?? [])
const engineOnline = computed(() => !statusStore.error && statusStore.status !== null)

// 当前页所在的组必须展开，否则会出现「页面已打开、侧栏里却看不到它」的困惑
const activeGroupTitle = computed(
  () => DEV_TABS.find((g) => g.items.some((i) => i.key === active.value))?.title ?? '',
)
watch(activeGroupTitle, (t) => { if (t) collapsedGroups[t] = false }, { immediate: true })

async function refreshAll(): Promise<void> {
  await Promise.all([statusStore.refresh(), configStore.load()])
  if (active.value === 'logs') await logStore.refresh()
}

/* ---------------------------------------------------------------------------
 * 桌宠主题
 *
 * 与 pet 窗口共用同一个 localStorage 键（'yuiro-theme'，pet 窗口的 useTheme 读写它）。
 * 写入后 pet 窗口会收到 storage 事件并即时跟随 —— 该事件只在「别的窗口」触发，
 * 所以两边各监听一次即可双向同步。
 * ------------------------------------------------------------------------- */
const PET_THEME_KEY = 'yuiro-theme'
type PetTheme = 'light' | 'dark'
const petTheme = ref<PetTheme>((localStorage.getItem(PET_THEME_KEY) as PetTheme | null) ?? 'light')

function setPetTheme(t: PetTheme): void {
  petTheme.value = t
  useUiAppearance().petTheme.value=t
  try { localStorage.setItem(PET_THEME_KEY, t) } catch { /* 私隐模式等场景忽略 */ }
}

function onPetThemeStorage(e: StorageEvent): void {
  if (e.key !== PET_THEME_KEY) return
  if (e.newValue === 'light' || e.newValue === 'dark') petTheme.value = e.newValue
}

onMounted(() => {
  void refreshAll()
  window.addEventListener('storage', onPetThemeStorage)
})

onBeforeUnmount(() => {
  window.removeEventListener('storage', onPetThemeStorage)
})

function switchTab(t: DevTab): void {
  active.value = t
  if (t === 'overview') statusStore.refresh()
  if (t === 'logs') logStore.refresh()
  // 窗口几何卡片在「UI」页（原先在「外观」页，2026-09 迁移）
  if (t === 'ui') loadLayout()
  // 配置类页面重载远端值，避免覆盖别处的改动
  if (TAB_SECTIONS[t]) configStore.load()
}

/* ---------------------------------------------------------------------------
 * 桌宠窗口几何（「UI」页）
 *
 * 约定：本页所有调整都是**热重载** —— 改完回车即生效，没有"保存 / 应用"按钮。
 * 窗口几何的真相源在主进程（petLayout 落盘），所以这里提交后要回读一次：
 * 主进程会把越界值夹紧，回读才能让输入框显示真实生效值。
 * ------------------------------------------------------------------------- */
const layout = reactive({ width: 420, height: 560, fillRatio: 0.55, xOffset: 0, yOffset: 0.45 })
const layoutApplied = ref(false)
let layoutFlashTimer = 0

/** 锁定窗口宽高比：拖一边时另一边按比例跟随（比例在"开启锁定"那一刻捕获）。 */
const lockRatio = ref(false)
let lockedRatio = 1

function toggleLockRatio(on: boolean): void {
  lockRatio.value = on
  if (on && layout.height > 0) lockedRatio = layout.width / layout.height
}

async function loadLayout(): Promise<void> {
  try {
    const l = await window.yuiro?.getPetLayout()
    if (l) Object.assign(layout, l)
  } catch { /* 读取失败保持现值 */ }
}

/*
 * 提交窗口几何（滑杆拖动 = 热重载）：
 *   input（拖动中）→ persist=false：窗口要跟手，但不落盘，且按帧合并，避免每秒上百次 IPC；
 *   change（松手）→ persist=true：落盘一次并回读夹紧后的真实值。
 */
let rafId = 0
let pendingPersist = false

function scheduleLayoutCommit(persist: boolean): void {
  pendingPersist = pendingPersist || persist
  if (rafId) return
  rafId = requestAnimationFrame(() => {
    rafId = 0
    const p = pendingPersist
    pendingPersist = false
    void pushLayout(p)
  })
}

/** 松手 / 回车：取消未执行的合并帧，立刻提交。 */
function commitLayout(persist = true): void {
  if (rafId) { cancelAnimationFrame(rafId); rafId = 0 }
  pendingPersist = false
  void pushLayout(persist)
}

async function pushLayout(persist: boolean): Promise<void> {
  try {
    const l = await window.yuiro?.setPetLayout({ ...layout }, persist)
    // 只在落盘那次回读：主进程会把越界值夹紧，回读才是真实生效值；
    // 拖动过程中不回读，否则夹紧值会把滑杆"顶回去"，手感会跳。
    if (persist && l) Object.assign(layout, l)
    if (persist) {
      layoutApplied.value = true
      if (layoutFlashTimer) clearTimeout(layoutFlashTimer)
      layoutFlashTimer = window.setTimeout(() => { layoutApplied.value = false }, 1500)
    }
  } catch { /* 提交失败保持现值：窗口尺寸由主进程兜底，不会因此坏掉 */ }
}

/** 宽度：锁定比例时联动高度。 */
function onWidthInput(persist: boolean): void {
  if (lockRatio.value && lockedRatio > 0) layout.height = Math.round(layout.width / lockedRatio)
  if (persist) commitLayout(true)
  else scheduleLayoutCommit(false)
}

/** 高度：锁定比例时联动宽度。 */
function onHeightInput(persist: boolean): void {
  if (lockRatio.value && lockedRatio > 0) layout.width = Math.round(layout.height * lockedRatio)
  if (persist) commitLayout(true)
  else scheduleLayoutCommit(false)
}

/** 其余参数（模型缩放 / 水平·垂直偏移）：不涉及比例，直接提交。 */
function onLayoutInput(persist: boolean): void {
  if (persist) commitLayout(true)
  else scheduleLayoutCommit(false)
}

/* ---------------------------------------------------------------------------
 * 聊天坞（脚底输入胶囊）外观：宽度 / 通透度 / 按钮显隐
 * 仍是 localStorage 偏好（跨窗口共享），改完即时生效，无需提交
 * ------------------------------------------------------------------------- */
const {
  width: dockWidth,
  height:dockHeight,
  offsetX:dockX,offsetY:dockY,radius:dockRadius,fontSize:dockFontSize,
  alpha: dockAlpha,
  showMic: dockShowMic,
  showSend: dockShowSend,
  reset: resetDock,
} = useChatDockPref()

/* ---------------------------------------------------------------------------
 * 悬停渐隐偏好（跨窗口共享 localStorage，pet 窗口据其生效）
 * ------------------------------------------------------------------------- */
const {
  fadeEnabled,
  nearRange: fadeNearRange,
  showNotice,
  requestEnable,
  confirmNotice,
  cancelNotice,
} = useFadeOnHoverPref()

/** 回复气泡外观（与桌宠窗口共享 localStorage，改完即时生效）。 */
const {
  maxWidth: bubbleMaxWidth,
  alpha: bubbleAlpha,
  offsetX: bubbleOffsetX,
  offsetY: bubbleOffsetY,
  reset: resetBubble,
} = useSpeechBubblePref()

/** 歌单 / 候选结果卡外观（同样跨窗口共享 localStorage）。 */
const {
  side: cardSide,
  offsetX: cardOffsetX,
  offsetY: cardOffsetY,
  maxWidth: cardMaxWidth,
  alpha: cardAlpha,
  reset: resetCard,
} = useResultCardPref()

const showLimitations = ref(false)
</script>

<template>
  <div class="dev-shell">
    <!-- ── 侧边栏 ── -->
    <aside class="sidebar">
      <div class="brand">
        <span class="brand-dot"></span>
        <div class="brand-text">
          <span class="brand-name">Yuiro</span>
          <span class="brand-sub">调试台</span>
        </div>
      </div>

      <nav class="nav">
        <div v-for="g in DEV_TABS" :key="g.title" class="nav-group">
          <button class="nav-group-title" @click="toggleGroup(g.title)">
            <Icon
              :icon="collapsedGroups[g.title]
                ? 'solar:alt-arrow-right-bold'
                : 'solar:alt-arrow-down-bold'"
              width="11" />
            <span>{{ g.title }}</span>
          </button>
          <template v-if="!collapsedGroups[g.title]">
            <button
              v-for="item in g.items"
              :key="item.key"
              class="nav-item"
              :class="{ active: active === item.key }"
              @click="switchTab(item.key)">
              <Icon :icon="item.icon" width="17" />
              <span>{{ item.label }}</span>
            </button>
          </template>
        </div>
      </nav>

      <div class="side-foot">
        <span class="conn" :class="engineOnline ? 'ok' : 'err'">
          <span class="conn-dot"></span>
          {{ engineOnline ? '引擎已连接' : '引擎未连接' }}
        </span>
      </div>
    </aside>

    <!-- ── 主区 ── -->
    <main class="main">
      <header class="topbar">
        <div class="topbar-text">
          <h2>{{ activeLabel }}<CharacterMotif :skin="characterUi.resolvedSkin.value" class="topbar-motif" /></h2>
          <p class="topbar-desc">{{ TAB_DESC[active] }}</p>
        </div>
        <div class="topbar-actions">
            <CharacterPicker />
          <span
            v-if="configStore.backend"
            class="pill pill-mute backend-pill"
            :title="configStore.backend">
            <span class="backend-text">{{ configStore.backend }}</span>
          </span>
          <button
            class="icon-btn"
            :title="theme === 'light' ? '切到夜间' : '切到日间'"
            @click="toggleTheme">
            <Icon :icon="theme === 'light' ? 'solar:moon-bold' : 'solar:sun-bold'" width="17" />
          </button>
          <button class="btn" @click="refreshAll">刷新</button>
        </div>
      </header>

      <div :key="`${configStore.character?.active_id}:${configStore.character?.revision}`" class="content" @input="configStore.hasDraftChanges = true">
        <!-- ═══ 总览 ═══ -->
        <section v-if="active === 'overview'" :key="'overview'" class="page">
          <div v-if="statusStore.error" class="alert alert-err">{{ statusStore.error }}</div>

          <div class="stat-grid">
            <div class="bubble stat">
              <span class="stat-label">引擎版本</span>
              <span class="stat-value">{{ statusStore.status?.engine.version ?? '—' }}</span>
            </div>
            <div class="bubble stat">
              <span class="stat-label">聊天后端</span>
              <span class="stat-value">{{ statusStore.status?.engine.chat_backend ?? '—' }}</span>
            </div>
            <div class="bubble stat">
              <span class="stat-label">执行通道</span>
              <span class="stat-value">{{ statusStore.status?.systemd.transport ?? '—' }}</span>
            </div>
            <div class="bubble stat">
              <span class="stat-label">可用工具</span>
              <span class="stat-value">{{ statusStore.status?.systemd.tool_count ?? 0 }}</span>
            </div>
          </div>

          <h3 class="section-h">组件自检</h3>
          <div class="provider-grid">
            <ProviderCard
              v-for="p in SELF_TESTS"
              :key="p.key"
              :provider="p.key"
              :title="p.title"
              :description="p.description" />
          </div>

          <button class="limitations-toggle" @click="showLimitations = !showLimitations">
            <Icon
              :icon="showLimitations ? 'solar:alt-arrow-down-bold' : 'solar:alt-arrow-right-bold'"
              width="13" />
            已知限制（{{ LIMITATIONS.length }}）
          </button>
          <ul v-if="showLimitations" class="limitations">
            <li v-for="(l, i) in LIMITATIONS" :key="i">{{ l }}</li>
          </ul>
        </section>

        <!-- ═══ 任务 ═══ -->
        <section v-else-if="active === 'task'" :key="'task'" class="page">
          <TaskPanel />
        </section>

        <!-- ═══ 语音联调 ═══ -->
        <section v-else-if="active === 'voiceDebug'" :key="'voiceDebug'" class="page page-voice">
          <VoiceDebug />
        </section>

        <!-- ═══ 日志 ═══ -->
        <section v-else-if="active === 'logs'" :key="'logs'" class="page page-logs">
          <LogViewer />
        </section>

        <!-- ═══ 人格基线 ═══ -->
        <section v-else-if="active === 'baseline'" :key="'baseline'" class="page">
          <BaselinePanel />
        </section>

        <!-- ═══ 记忆：按「先看 → 再看你给的 → 再管 → 最后调参」排序 ═══
             此前顺序是"洞察 → 参数 → 管理"，参数夹在中间：用户想查一条记忆，
             得先滚过一堆数字输入框。参数是给愿意折腾的人准备的，放最后。 -->
        <section v-else-if="active === 'memory'" :key="'memory'" class="page page-memory">
          <div v-if="configStore.error" class="alert alert-err">{{ configStore.error }}</div>

          <!-- ① 概览：她记得多少、你们的关系、你让她记住的事 -->
          <MemoryInsights />

          <!-- ② 你给她的资料（此前后端有、界面没有 → 里面装了什么无人知道） -->
          <KnowledgePanel />

          <!-- ③ 具体内容：她记住的你 / 聊过的片段 / 检索观测（说了记不住时来这查） -->
          <MemoryManager />

          <!-- ④ 最后才是「怎么记」的参数与归属 -->
          <div class="config-list">
            <SectionForm v-for="s in activeSections" :key="s" :section="s" />
            <SectionForm
              section="persona"
              :only="['memory_subject']"
              title="记忆归属"
              subtitle="这些记忆算在谁名下 —— 换人使用时可区分（改动需重启引擎生效）" />
          </div>
        </section>

        <!-- 日记：博客式归档入口，与独立编辑器复用阅读组件。 -->
        <section v-else-if="active === 'diary'" :key="'diary'" class="page page-diary">
          <DiaryPanel />
        </section>

        <!-- ═══ 性格 ═══ -->
        <section v-else-if="active === 'persona'" :key="'persona'" class="page">
          <div v-if="configStore.error" class="alert alert-err">{{ configStore.error }}</div>
          <PersonaForm />
        </section>

        <!-- ═══ 联网检索（S51：引擎侧生效状态 + 总开关 + 搜索服务 Key）═══ -->
        <section v-else-if="active === 'search'" :key="'search'" class="page">
          <div v-if="configStore.error" class="alert alert-err">{{ configStore.error }}</div>
          <!-- 状态卡在配置卡**之前**：先看引擎实际状态，再改草稿 ——
               避免"打开开关却没保存，回来一看还是不可用"的困惑 -->
          <SearchStatus />
          <div class="config-list">
            <SectionForm v-for="s in activeSections" :key="s" :section="s" />
          </div>
        </section>

        <!-- ═══ 外观 ═══ -->
        <section v-else-if="active === 'appearance'" :key="'appearance'" class="page">
          <AppearanceStudio />
        </section>

        <!-- ═══ UI：桌宠的界面表现 ═══ -->
        <section v-else-if="active === 'ui'" :key="'ui'" class="page">
          <!-- 免打扰 -->
          <div class="bubble card-narrow">
            <h3 class="bubble-title">免打扰</h3>
            <div class="row-between">
              <div class="row-text">
                <span class="row-title">悬停渐隐</span>
                <span class="hint">
                  开启后光标靠近模型即整体淡出并穿透，不挡下层点击；
                  离开范围或贴边拖动即恢复。也可右键托盘图标切换。
                </span>
              </div>
              <button
                class="btn"
                :class="fadeEnabled ? 'btn-danger' : 'btn-primary'"
                @click="fadeEnabled ? (fadeEnabled = false) : requestEnable()">
                {{ fadeEnabled ? '关闭' : '开启' }}
              </button>
            </div>

            <div class="slider-row">
              <label class="slider-label" for="fade-range">
                靠近触发范围
                <span class="slider-val">{{ Math.round(fadeNearRange) }} px</span>
              </label>
              <input
                id="fade-range"
                v-model.number="fadeNearRange"
                type="range" min="0" max="300" step="5"
                class="slider" />
            </div>
            <p class="hint">
              以<strong>模型 Alpha 轮廓</strong>为基准往外扩这么多像素就算「靠近」：
              0 = 贴到模型才淡出，调大可以<strong>在窗口外</strong>就开始淡出（提前让位）。
              透明区域始终让出点击；渐隐中的模型也让出点击，独立卡片和输入控件保留交互。
            </p>
          </div>

          <div class="bubble card-narrow">
            <h3 class="bubble-title">动态轮廓命中（最小验证）</h3>
            <label><input v-model="contourPref.debug.value" type="checkbox" /> 显示 Alpha 遮罩（绿色，非矩形）</label>
            <div class="slider-row"><label>Alpha 阈值 {{ contourPref.threshold.value }}</label>
              <input v-model.number="contourPref.threshold.value" type="range" min="1" max="254" /></div>
            <div class="slider-row"><label>命中容差 {{ contourPref.tolerance.value }} px</label>
              <input v-model.number="contourPref.tolerance.value" type="range" min="0" max="16" /></div>
            <p class="hint">8Hz 采样模型画布；透明处穿透。数值即时生效，阈值越高越忽略半透明边缘。渐隐不改变 Alpha 遮罩；常驻功能岛入口已移除，可从聊天输入或托盘进入相关功能。</p>
          </div>
          <!-- 桌宠主题：与调试台自身的主题是两个独立设置 -->

          <DetachedUiSettings />

          <!-- 聊天坞：脚底输入胶囊 -->
          <div class="bubble card-narrow">
            <div class="row-between">
              <h3 class="bubble-title">聊天坞</h3>
              <button class="btn" @click="resetDock">恢复默认</button>
            </div>
            <p class="hint">脚底输入胶囊的宽度、高度、通透度与按钮显隐，改动即时生效。</p>

            <div class="slider-row">
              <label class="slider-label" for="dock-w">
                最大宽度
                <span class="slider-val">{{ Math.round(dockWidth) }} px</span>
              </label>
              <input
                id="dock-w"
                v-model.number="dockWidth"
                type="range" min="180" max="640" step="10"
                class="slider" />
            </div>

            <div class="slider-row">
              <label class="slider-label" for="dock-h">输入条高度 <span class="slider-val">{{ Math.round(dockHeight) }} px</span></label>
              <input id="dock-h" v-model.number="dockHeight" type="range" min="36" max="80" step="2" class="slider" />
            </div>
            <UiRange v-model="dockX" label="聊天坞左右偏移" :min="-1000" :max="1000" unit=" px" />
            <UiRange v-model="dockY" label="聊天坞离底部偏移（正数上移）" :min="-50" :max="400" unit=" px" />
            <UiRange v-model="dockRadius" label="输入条圆角" :min="0" :max="40" unit=" px" />
            <UiRange v-model="dockFontSize" label="输入文字字号" :min="11" :max="24" unit=" px" />
            <div class="slider-row">
              <label class="slider-label" for="dock-a">
                不透明度
                <span class="slider-val">{{ Math.round(dockAlpha * 100) }}%</span>
              </label>
              <input
                id="dock-a"
                v-model.number="dockAlpha"
                type="range" min="0.3" max="1" step="0.02"
                class="slider" />
            </div>

            <div class="row-between">
              <div class="row-text">
                <span class="row-title">麦克风按钮</span>
                <span class="hint">收掉后仍可从括号菜单的「语音」进入，不影响语音链路。</span>
              </div>
              <div class="seg">
                <button class="seg-btn" :class="{ on: dockShowMic }" @click="dockShowMic = true">显示</button>
                <button class="seg-btn" :class="{ on: !dockShowMic }" @click="dockShowMic = false">隐藏</button>
              </div>
            </div>

            <div class="row-between">
              <div class="row-text">
                <span class="row-title">发送按钮</span>
                <span class="hint">收掉后仍可回车发送（Enter 始终生效）。</span>
              </div>
              <div class="seg">
                <button class="seg-btn" :class="{ on: dockShowSend }" @click="dockShowSend = true">显示</button>
                <button class="seg-btn" :class="{ on: !dockShowSend }" @click="dockShowSend = false">隐藏</button>
              </div>
            </div>
          </div>

          <!-- 桌宠窗口与模型（原「外观」页卡片，2026-09 迁入 UI 页）
               约定：本页所有调整都是热重载 —— 拖滑杆即时生效，没有"应用"按钮。 -->
          <div class="bubble card-narrow">
            <div class="row-between">
              <h3 class="bubble-title">桌宠窗口与模型</h3>
              <span v-if="layoutApplied" class="pill pill-ok">已应用</span>
            </div>
            <p class="hint">
              拖滑杆即时生效，无需保存。窗口可调到当前屏幕工作区内，仅保留安全边距；超限会夹紧。模型等比适配，同时受窗口宽度限制，想整体放大可锁定窗口比例。
            </p>

            <div class="slider-row">
              <label class="slider-label" for="win-w">
                窗口宽度
                <span class="slider-val">{{ layout.width }} px</span>
              </label>
              <input
                id="win-w"
                v-model.number="layout.width"
                type="range" min="200" max="1400" step="10"
                class="slider"
                @input="onWidthInput(false)" @change="onWidthInput(true)" />
            </div>

            <div class="slider-row">
              <label class="slider-label" for="win-h">
                窗口高度
                <span class="slider-val">{{ layout.height }} px</span>
              </label>
              <input
                id="win-h"
                v-model.number="layout.height"
                type="range" min="200" max="2000" step="10"
                class="slider"
                @input="onHeightInput(false)" @change="onHeightInput(true)" />
              <input id="win-h-number" v-model.number="layout.height" type="number" min="200" max="2000" step="10" aria-label="窗口高度数值" class="height-number" @change="onHeightInput(true)" />
            </div>

            <div class="row-between">
              <div class="row-text">
                <span class="row-title">锁定窗口比例</span>
                <span class="hint">
                  锁定后拖宽度会带着高度按比例一起变（比例取开启锁定那一刻的宽高比）。
                </span>
              </div>
              <div class="seg">
                <button class="seg-btn" :class="{ on: lockRatio }" @click="toggleLockRatio(true)">锁定</button>
                <button class="seg-btn" :class="{ on: !lockRatio }" @click="toggleLockRatio(false)">自由</button>
              </div>
            </div>

            <div class="slider-row">
              <label class="slider-label" for="model-scale">
                模型缩放
                <span class="slider-val">{{ layout.fillRatio.toFixed(2) }}×</span>
              </label>
              <input
                id="model-scale"
                v-model.number="layout.fillRatio"
                type="range" min="0.1" max="2" step="0.05"
                class="slider"
                @input="onLayoutInput(false)" @change="onLayoutInput(true)" />
            </div>

            <div class="slider-row">
              <label class="slider-label" for="model-x">
                模型水平偏移
                <span class="slider-val">{{ layout.xOffset }} px</span>
              </label>
              <input
                id="model-x"
                v-model.number="layout.xOffset"
                type="range" min="-400" max="400" step="5"
                class="slider"
                @input="onLayoutInput(false)" @change="onLayoutInput(true)" />
            </div>

            <div class="slider-row">
              <label class="slider-label" for="model-y">
                模型垂直偏移
                <span class="slider-val">{{ layout.yOffset.toFixed(2) }}</span>
              </label>
              <input
                id="model-y"
                v-model.number="layout.yOffset"
                type="range" min="0" max="1" step="0.05"
                class="slider"
                @input="onLayoutInput(false)" @change="onLayoutInput(true)" />
            </div>
          </div>
        </section>

        <!-- ═══ 配置类页面：大脑 / 声音 / 主动性 / 能力与安全 / 运行环境 ═══ -->
        <section v-else-if="activeSections.length" :key="active" class="page page-config">
          <div v-if="configStore.error" class="alert alert-err">{{ configStore.error }}</div>
          <!-- 「声音」页：音色属于 persona 段，但归到声音链路更贴切，故单独成卡 -->
          <VoicePicker v-if="active === 'speech' && configStore.sections.tts?.provider === 'edge-tts'" />
          <ProviderCard v-if="active === 'speech'" provider="tts" title="当前角色语音试听" description="按当前已保存配置合成；中文、日文可分别试听。切换角色会停止旧试听。" />
          <div class="config-list">
            <SectionForm v-for="s in activeSections" :key="s" :section="s" />
          </div>
          <div class="config-foot">
            <button class="btn" @click="configStore.reload()">从磁盘重载</button>
          </div>
        </section>
      </div>
    </main>

    <!-- 首次开启悬停渐隐的确认层 -->
    <FadeOnHoverNotice
      v-if="showNotice"
      @confirm="confirmNotice"
      @cancel="cancelNotice" />
  </div>
</template>

<style scoped>
.dev-shell { display: flex; height: 100vh; background: var(--bg); color: var(--text); }

/* ══════════════ 侧边栏 ══════════════ */
.sidebar {
  width: 210px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  border-right: 1px solid var(--border);
  background: var(--card);
}
.brand {
  display: flex; align-items: center; gap: 10px;
  padding: 18px; border-bottom: 1px solid var(--border);
}
.brand-dot {
  width: 11px; height: 11px; border-radius: 50%;
  background: var(--accent);
  box-shadow: 0 0 0 4px var(--accent-soft);
  flex-shrink: 0;
}
.brand-text { display: flex; flex-direction: column; line-height: 1.2; }
.brand-name { font-size: 15px; font-weight: 700; letter-spacing: 0.01em; }
.brand-sub { font-size: 11px; color: var(--muted); }

.nav { flex: 1; overflow-y: auto; padding: 12px 10px; display: flex; flex-direction: column; gap: 13px; }
.nav-group { display: flex; flex-direction: column; gap: 2px; }
.nav-group-title {
  display: flex; align-items: center; gap: 5px;
  padding: 0 10px 6px;
  border: none; background: transparent;
  font-family: inherit; font-size: 10.5px; font-weight: 700;
  color: var(--muted); text-transform: uppercase; letter-spacing: 0.08em;
  cursor: pointer; text-align: left;
}
.nav-group-title:hover { color: var(--text-soft); }
.nav-item {
  display: flex; align-items: center; gap: 10px;
  padding: 8px 12px; border-radius: 999px; border: none;
  background: transparent; color: var(--text-soft);
  cursor: pointer; font-size: 13px; text-align: left;
  font-family: inherit;
  transition: background var(--dur-fast) ease, color var(--dur-fast) ease;
}
.nav-item:hover { background: var(--btn-hover-bg); color: var(--text); }
.nav-item.active { background: var(--accent-soft); color: var(--accent); font-weight: 600; }

.side-foot { padding: 14px 18px; border-top: 1px solid var(--border); }
.conn { display: flex; align-items: center; gap: 7px; font-size: 12px; }
.conn-dot { width: 7px; height: 7px; border-radius: 50%; flex-shrink: 0; }
.conn.ok .conn-dot { background: var(--ok); box-shadow: 0 0 0 3px color-mix(in srgb, var(--ok) 20%, transparent); }
.conn.err .conn-dot { background: var(--err); box-shadow: 0 0 0 3px color-mix(in srgb, var(--err) 20%, transparent); }

/* ══════════════ 主区 ══════════════ */
.main { flex: 1; display: flex; flex-direction: column; min-width: 0; }
.topbar {
  display: flex; align-items: center; justify-content: space-between;
  /* 关键：空间不足时让右侧操作换行，而不是把标题压成一字一列 */
  flex-wrap: wrap;
  gap: 10px 20px;
  padding: 14px 24px; border-bottom: 1px solid var(--border); background: var(--card);
}
.topbar-text {
  /* 给标题一个不可再缩的下限：宁可操作区换行，也不让中文竖排 */
  flex: 1 1 260px;
  min-width: 260px;
}
.topbar-text h2 {
  margin: 0; font-size: 16px; font-weight: 700;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.topbar-desc {
  margin: 3px 0 0; font-size: 12px; color: var(--muted); line-height: 1.5;
  /* 说明最多两行，超出省略，避免顶栏被长文案撑高 */
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical;
  overflow: hidden;
}
.topbar-actions { display: flex; align-items: center; gap: 10px; margin-left: auto; }

/* 后端名可能很长（带版本号等），限制宽度并省略，免得把标题挤走 */
.backend-pill { max-width: 200px; }
.backend-text { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.icon-btn {
  display: inline-flex; align-items: center; justify-content: center;
  width: 34px; height: 34px; border-radius: 50%;
  border: 1px solid var(--border); background: transparent;
  color: var(--text-soft); cursor: pointer;
  transition: background var(--dur-fast) ease, color var(--dur-fast) ease;
}
.icon-btn:hover { background: var(--btn-hover-bg); color: var(--accent); }

.content { flex: 1; overflow-y: auto; padding: 22px 24px 40px; }
/* 页面统一样式：限宽居中 + 轻微上浮入场，切页有「翻页」感 */
.page {
  max-width: 900px; margin: 0 auto;
  display: flex; flex-direction: column; gap: 16px;
  animation: page-in 180ms var(--ease-out);
}
@keyframes page-in {
  from { opacity: 0; transform: translateY(6px); }
  to { opacity: 1; transform: translateY(0); }
}
.page-config { max-width: 760px; }
/* 「日记」页：**不限宽**（它自己是一本书，宽度由书决定）+ 去掉通用堆叠间距 ——
   用户要求"脱离并与其他的设置格式编排不同"：这一页不该长得像配置页。 */
.page-diary {
  max-width: none; gap: 0;
  /* ⚠ 必须关掉 `.page` 的通用入场（`page-in`：translateY(6px)）——
     日记这一页有自己的"封面 → 翻开"仪式，再叠一层"整页从下往上 6px"
     只会让人觉得封面是"被顶上来"的（用户反馈）。 */
  animation: none;
}
.page-memory { max-width: 1000px; }
.page-voice { max-width: 1280px; }
.page-logs { max-width: none; height: 100%; gap: 0; }

/* ══════════════ 通用块 ══════════════ */
.alert { padding: 11px 15px; border-radius: var(--radius-md); font-size: 13px; }
.alert-err { background: color-mix(in srgb, var(--err) 12%, transparent); color: var(--err); }

.bubble-title { margin: 0; font-size: 14px; font-weight: 600; }
.card-narrow { max-width: 560px; }

.section-h {
  font-size: 12px; font-weight: 700; color: var(--muted);
  text-transform: uppercase; letter-spacing: 0.07em;
  margin: 6px 0 0;
}

/* ══════════════ 总览 ══════════════ */
.stat-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 14px; }
.stat { display: flex; flex-direction: column; gap: 6px; padding: 15px 17px; }
.stat-label { font-size: 11.5px; color: var(--muted); }
.stat-value { font-size: 19px; font-weight: 700; color: var(--accent); word-break: break-all; }

.provider-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; }

.limitations-toggle {
  display: inline-flex; align-items: center; gap: 6px;
  align-self: flex-start;
  padding: 6px 12px; border-radius: 999px;
  border: 1px dashed var(--border); background: transparent;
  color: var(--muted); font-size: 11.5px; font-family: inherit;
  cursor: pointer;
}
.limitations-toggle:hover { background: var(--btn-hover-bg); color: var(--text); }
.limitations {
  margin: 0; padding: 12px 16px 12px 32px;
  border-radius: var(--radius-md); background: var(--card-head);
  font-size: 12px; color: var(--text-soft); line-height: 1.8;
}

/* ══════════════ 配置页 ══════════════ */
.config-list { display: flex; flex-direction: column; gap: 14px; }
.config-foot { display: flex; justify-content: flex-end; }

/* ══════════════ 通用行 / 分段控件 ══════════════ */
.row-between {
  display: flex; align-items: center; justify-content: space-between;
  /* 同样：空间不足让控件换行，而不是挤压说明文字 */
  flex-wrap: wrap;
  gap: 12px 18px;
}
.row-text { display: flex; flex-direction: column; gap: 4px; flex: 1 1 220px; min-width: 220px; }
.row-title { font-size: 13px; font-weight: 600; }

/* ── UI 页：分段控件 ── */
.seg {
  display: inline-flex; flex-shrink: 0;
  padding: 3px; gap: 3px;
  border: 1px solid var(--border); border-radius: 999px;
  background: var(--input);
}
.seg-btn {
  padding: 5px 14px; border: none; border-radius: 999px;
  background: transparent; color: var(--text-soft);
  font-family: inherit; font-size: 12px; cursor: pointer;
  transition: background var(--dur-fast) ease, color var(--dur-fast) ease;
}
.seg-btn:hover { color: var(--text); }
.seg-btn.on { background: var(--accent); color: #fff; font-weight: 600; }

/* ── UI 页：滑块 ── */
.slider-row { margin-top: 14px; }
.slider-label {
  display: flex; align-items: baseline; justify-content: space-between;
  font-size: 12.5px; color: var(--text-soft); margin-bottom: 7px;
}
.slider-val { font-family: ui-monospace, monospace; font-size: 11.5px; color: var(--muted); }
.slider {
  width: 100%; height: 4px; margin: 0;
  border-radius: 999px; background: var(--border);
  appearance: none; -webkit-appearance: none; outline: none; cursor: pointer;
}
.slider::-webkit-slider-thumb {
  -webkit-appearance: none; appearance: none;
  width: 15px; height: 15px; border-radius: 50%;
  background: var(--accent); border: 2px solid var(--card);
  box-shadow: var(--shadow-soft); cursor: pointer;
}

.hint { font-size: 12px; color: var(--muted); line-height: 1.6; margin: 0; }
</style>

<style scoped>.topbar{position:relative}.topbar-text h2{display:flex;align-items:center;gap:12px}.topbar-motif{width:56px;height:30px;opacity:.35}.topbar-text{position:relative;z-index:1}@media(max-width:900px){.topbar-motif{display:none}}</style>

<style scoped>.height-number{width:100px;padding:6px 8px;margin-top:6px;border:1px solid var(--border);border-radius:8px;background:var(--input);color:var(--text)}</style>
