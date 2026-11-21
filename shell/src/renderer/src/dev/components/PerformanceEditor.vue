<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import type { Live2DManifest } from '@shared'
import { EMOTION_TO_SLOT } from '@shared'
import { api, type PerformanceItem } from '../api'
import type { AvatarIntentLike } from '../../avatar/avatarSlots'
import { useConfigStore } from '../stores/config'
import { fetchModelDetail, type MotionGroup } from '../modelDetail'

/**
 * 表演搭配编辑器（调试台「外观」页）
 *
 * 解决什么问题：内置表演包的表情是**按情绪**推出来的 —— celebrate / surprise /
 * excited 的 emotion 都是 excited，三者只能共用同一个表情（改一个动三个），
 * 所以「庆祝配了张惊讶的脸」这种不搭没法只修其中一个。
 *
 * 本卡片直接编辑 `[persona.performance_map]`（引擎侧 S48 新增）：
 *   · 每个表演可**独立**指定 表情 + 动作；
 *   · 还能自定新表演名（自动进表演库，可被 LLM 通过 avatar_perform 点播）；
 *   · 两项留空 = 沿用内置/情绪映射，不会把默认行为写死。
 *
 * 下拉选项来自**当前模型的 model3.json**（换模型自动跟着变），所以不必再手记
 * `expression5` / `TapBody#7` 这类名字；想确认某个表情/动作长什么样，
 * 用上方「桌宠形象」卡里的表情/动作按钮逐个预览。
 *
 * 保存走既有的 PUT /api/config：引擎会 config_apply → save_config → 人设热重载，
 * 因此点完保存立刻生效，无需重启引擎。
 */
const props=defineProps<{localPreview?:boolean}>()
const emit=defineEmits<{preview:[intent:AvatarIntentLike&{duration_ms?:number;performance?:string}];catalog:[items:PerformanceItem[]]}>()
const store = useConfigStore()

/* ── 当前模型能提供哪些可选资源 ── */
const motions = ref<MotionGroup[]>([])
const expressions = ref<string[]>([])
const detailError = ref('')

const modelPath = computed(() => String(store.sections?.persona?.model_path ?? ''))
const configReady = computed(() => !!store.sections?.persona)

async function reloadModelDetail(): Promise<void> {
  const path = modelPath.value
  const role = store.character?.active_id
  const detail = await fetchModelDetail(path)
  if (path !== modelPath.value || role !== store.character?.active_id) return
  motions.value = detail.motions
  expressions.value = detail.expressions
  detailError.value = detail.error
}

/* ── 表演库（引擎解析后的"当前实际搭配"，用来展示真相与试演） ── */
const performances = ref<PerformanceItem[]>([])
const lastPerf = ref('')

async function reloadPerformances(): Promise<void> {
  const role = store.character?.active_id
  const revision = store.character?.revision
  try {
    const r = await api.getPerformances()
    if (role !== store.character?.active_id || revision !== store.character?.revision) return
    performances.value = Array.isArray(r.performances) ? r.performances : []
    emit('catalog',performances.value)
  } catch {
    performances.value = [] // 引擎未启动：不报错，只是没有内容
  }
}

/* ── 编辑中的搭配（草稿；点保存才写回 config.toml） ── */
const draft = ref<Record<string, string>>({})
const exprDraft = ref<Record<string, string>>({})
const saving = ref(false)
const saveError = ref('')
const savedAt = ref(0)
const newName = ref('')

/** 情绪列表：与引擎 expression_map / emotion_hints 的键一致。 */
const EMOTIONS: { key: string; label: string }[] = [
  { key: 'happy', label: '开心' },
  { key: 'sad', label: '难过' },
  { key: 'angry', label: '生气' },
  { key: 'excited', label: '兴奋' },
  { key: 'bored', label: '无聊' },
  { key: 'thinking', label: '思考' },
]

/** 对象字段安全读取（配置值类型是联合类型，这里只接受「字符串 → 字符串」的对象）。 */
function asStringMap(v: unknown): Record<string, string> {
  if (!v || typeof v !== 'object' || Array.isArray(v)) return {}
  return { ...(v as Record<string, string>) }
}

/** 全部档案（persona.profiles）。 */
function readProfiles(): Record<string, Record<string, unknown>> {
  const v = store.sections?.persona?.profiles
  if (!v || typeof v !== 'object' || Array.isArray(v)) return {}
  return JSON.parse(JSON.stringify(v)) as Record<string, Record<string, unknown>>
}

/**
 * 当前模型命中的档案名（空串 = 没有档案）。
 * 规则与引擎 config.active_profile 一致：档案的 model 等于 model_path，或档案名本身就是路径。
 */
const profileKey = computed(() => {
  const path = modelPath.value.trim()
  if (!path) return ''
  const profiles = readProfiles()
  for (const [name, prof] of Object.entries(profiles)) {
    const m = String((prof as Record<string, unknown>)?.model ?? '').trim()
    if (m === path || name.trim() === path) return name
  }
  return ''
})

/** 正在编辑档案（否则编辑的是全局表，会影响所有模型）。 */
const editingProfile = computed(() => profileKey.value !== '')

/** 当前模型的可读名（取模型文件名，够用：上方「桌宠形象」卡里有完整名字）。 */
const modelLabel = computed(() => {
  const seg = modelPath.value.split('/').filter(Boolean)
  return seg.length ? seg[seg.length - 1] : '(未设置)'
})

/** 读出当前生效的 performance_map：有档案用档案的，否则用全局。 */
function readMap(): Record<string, string> {
  if (editingProfile.value) {
    const prof = readProfiles()[profileKey.value] ?? {}
    return asStringMap(prof.performance_map)
  }
  return asStringMap(store.sections?.persona?.performance_map)
}

/** 读出当前生效的 expression_map（情绪 → 表情）。 */
function readExprMap(): Record<string, string> {
  if (editingProfile.value) {
    const prof = readProfiles()[profileKey.value] ?? {}
    return asStringMap(prof.expression_map)
  }
  return asStringMap(store.sections?.persona?.expression_map)
}

/** 组合成引擎的取值文本："表情, 动作"（两段都空 → 空串 = 不要这条覆盖）。 */
function compose(expr: string, motion: string): string {
  const e = expr.trim()
  const m = motion.trim()
  if (!e && !m) return ''
  if (!m) return e
  return `${e}, ${m}`
}

/**【与引擎同规则】解析取值文本（engine/yuiro/avatar/performance.py 的 parse_performance_spec）。 */
function parse(text: string): { expr: string; motion: string } {
  const raw = (text ?? '').trim()
  if (!raw) return { expr: '', motion: '' }
  const i = raw.indexOf(',')
  if (i >= 0) return { expr: raw.slice(0, i).trim(), motion: raw.slice(i + 1).trim() }
  // 无逗号：含 # 说明写的是动作索引（表情名不含 #），否则当作表情
  if (raw.includes('#')) return { expr: '', motion: raw }
  return { expr: raw, motion: '' }
}

/** 丢掉空条目：新加的自定表演还没配内容时不该落库。 */
function clean(map: Record<string, string>): Record<string, string> {
  const out: Record<string, string> = {}
  for (const [name, text] of Object.entries(map)) {
    const { expr, motion } = parse(text)
    const combined = compose(expr, motion)
    if (combined) out[name] = combined
  }
  return out
}

/** 表情表也丢掉空值（留空 = 回落默认表情）。 */
function cleanExpr(map: Record<string, string>): Record<string, string> {
  const out: Record<string, string> = {}
  for (const [k, v] of Object.entries(map)) {
    const s = String(v ?? '').trim()
    if (s) out[k] = s
  }
  return out
}

const dirty = computed(
  () => JSON.stringify(clean(draft.value)) !== JSON.stringify(readMap())
    || JSON.stringify(cleanExpr(exprDraft.value)) !== JSON.stringify(readExprMap()),
)

function parts(name: string): { expr: string; motion: string } {
  return parse(draft.value[name] ?? '')
}

function configure(name: string, expr: string, motion: string): void {
  const text = compose(expr, motion)
  if (text) {
    draft.value = { ...draft.value, [name]: text }
    return
  }
  const next = { ...draft.value }
  delete next[name]
  draft.value = next
}

function onExpr(name: string, e: Event): void {
  configure(name, (e.target as HTMLSelectElement).value, parts(name).motion)
}

function onMotion(name: string, e: Event): void {
  configure(name, parts(name).expr, (e.target as HTMLSelectElement).value)
}

/** 移除这条覆盖 → 回落内置表演包 / 情绪映射。 */
function reset(name: string): void {
  const next = { ...draft.value }
  delete next[name]
  draft.value = next
}

function clearAll(): void {
  draft.value = {}
}

const canAdd = computed(() => {
  const n = newName.value.trim().toLowerCase()
  return !!n && /^[a-z][a-z0-9_-]*$/.test(n) && draft.value[n] === undefined
})

function addCustom(): void {
  if (!canAdd.value) return
  const n = newName.value.trim().toLowerCase()
  draft.value = { ...draft.value, [n]: '' } // 空值：配好内容才会落库
  newName.value = ''
}

/** 由模型文件名推一个档案名（hiyori / feiniu / natori…），并保证不与现有档案重名。 */
function suggestKey(): string {
  const seg = modelPath.value.split('/').filter(Boolean)
  const file = (seg[seg.length - 1] || 'model').replace(/\.model3\.json$/i, '')
  const folder = seg.length > 1 ? seg[seg.length - 2] : ''
  const base = [file, folder, 'model']
    .map(s => s.toLowerCase().replace(/[^a-z0-9_-]+/g, '-').replace(/^-+|-+$/g, ''))
    .find(s => !!s) ?? 'model'
  const existing = new Set(Object.keys(readProfiles()))
  if (!existing.has(base)) return base
  for (let i = 2; i < 99; i++) {
    if (!existing.has(`${base}-${i}`)) return `${base}-${i}`
  }
  return `${base}-x`
}

/** 为当前模型新建档案：把当前生效的表复制进去当起点，之后改的就只影响这个模型。 */
async function createProfile(): Promise<void> {
  const key = suggestKey()
  const profiles = readProfiles()
  profiles[key] = {
    model: modelPath.value.trim(),
    note: '由调试台创建',
    expression_map: cleanExpr(exprDraft.value),
    performance_map: clean(draft.value),
  }
  saving.value = true
  saveError.value = ''
  try {
    await store.applySection('persona', { profiles })
    draft.value = readMap()
    exprDraft.value = readExprMap()
    savedAt.value = Date.now()
    await reloadPerformances()
  } catch (e) {
    saveError.value = e instanceof Error ? e.message : String(e)
  } finally {
    saving.value = false
  }
}

/** 删除档案 → 该模型回落全局表。 */
async function deleteProfile(): Promise<void> {
  const key = profileKey.value
  if (!key) return
  const profiles = readProfiles()
  delete profiles[key]
  saving.value = true
  saveError.value = ''
  try {
    await store.applySection('persona', { profiles })
    draft.value = readMap()
    exprDraft.value = readExprMap()
    savedAt.value = Date.now()
    await reloadPerformances()
  } catch (e) {
    saveError.value = e instanceof Error ? e.message : String(e)
  } finally {
    saving.value = false
  }
}

/**
 * 按当前模型的资产**自动生成档案**（S53）。
 *
 * 用途：给文件名无语义的模型（Hiyori / 肥牛）一键落地语义绑定 ——
 * 表情按槽位取第一个候选，动作按槽位取（优先 `_C` 正面变体）。
 * 生成后仍可在下方逐项手改，档案永远优先于自动推断。
 */
async function generateProfile(): Promise<void> {
  if (!manifest.value) await loadManifest()
  const m = manifest.value
  if (!m) {
    saveError.value = '读不到当前模型的清单，无法自动生成'
    return
  }
  const exprMap: Record<string, string> = {}
  for (const [emotion, slot] of Object.entries(EMOTION_TO_SLOT)) {
    const name = m.index.expression[slot]?.[0]
    if (name) exprMap[emotion] = name
  }
  const slots: Record<string, string> = {}
  for (const slot of ['greet', 'celebrate', 'comfort', 'surprise', 'thinking', 'sing', 'look', 'idle']) {
    const candidates = m.index.motion[slot] ?? []
    if (!candidates.length) continue
    const pick = candidates.find((c) =>
      m.motions.some((x) => x.group === c.group && x.index === c.index && x.direction === 'C'),
    ) ?? candidates[0]
    slots[slot] = `${pick.group}#${pick.index}`
  }

  const key = profileKey.value || suggestKey()
  const profiles = readProfiles()
  profiles[key] = {
    ...(profiles[key] ?? {}),
    model: modelPath.value.trim(),
    note: '按模型资产自动推断（可继续手改）',
    expression_map: exprMap,
    motion_slots: slots,
  }
  saving.value = true
  saveError.value = ''
  try {
    await store.applySection('persona', { profiles })
    syncDraft()
    savedAt.value = Date.now()
    await reloadPerformances()
    previewInfo.value = `已生成档案「${key}」：表情 ${Object.keys(exprMap).length} 项 · 动作槽位 ${Object.keys(slots).length} 项`
  } catch (e) {
    saveError.value = e instanceof Error ? e.message : String(e)
  } finally {
    saving.value = false
  }
}

function onEmotion(key: string, e: Event): void {
  const v = (e.target as HTMLSelectElement).value
  const next = { ...exprDraft.value }
  if (v) next[key] = v
  else delete next[key]
  exprDraft.value = next
}

async function save(): Promise<void> {
  saving.value = true
  saveError.value = ''
  try {
    if (editingProfile.value) {
      // 写进当前模型的档案（只影响这一个模型）
      const profiles = readProfiles()
      profiles[profileKey.value] = {
        ...(profiles[profileKey.value] ?? {}),
        model: modelPath.value.trim(),
        expression_map: cleanExpr(exprDraft.value),
        performance_map: clean(draft.value),
      }
      await store.applySection('persona', { profiles })
    } else {
      // 没有档案 → 写全局表（会影响所有没配档案的模型，界面上有明确提示）
      await store.applySection('persona', {
        expression_map: cleanExpr(exprDraft.value),
        performance_map: clean(draft.value),
      })
    }
    draft.value = readMap() // 与落库结果对齐（空条目已被丢弃）
    exprDraft.value = readExprMap()
    savedAt.value = Date.now()
    await reloadPerformances() // 引擎已热重载，列表里的"当前"要跟着更新
  } catch (e) {
    saveError.value = e instanceof Error ? e.message : String(e)
  } finally {
    saving.value = false
  }
}

/** 「组名#索引」→ { group, index }（无 # 或索引非法 → index = null，即该组随机）。 */
function splitMotion(text: string): { group: string; index: number | null } {
  const t = (text ?? '').trim()
  if (!t) return { group: '', index: null }
  const i = t.lastIndexOf('#')
  if (i < 0) return { group: t, index: null }
  const n = Number(t.slice(i + 1))
  return { group: t.slice(0, i).trim(), index: Number.isInteger(n) ? n : null }
}

/**
 * 逐行体检：这个表演在**当前模型**上能不能真的跑起来？
 *
 * 为什么需要：「表演不生效」这类问题排过很多次，最后都发现是换模型后旧的
 * 组名/表情名还留在配置里 —— TapBody#5 在没有 TapBody 的模型上点了没反应，
 * 且**不报错**。这里把每个表演的 表情 / 动作组 / 索引 与当前模型实际拥有的
 * 资源对照，试演之前就告诉你缺什么，而不是点了没反应再猜。
 */
/** 当前模型的语义清单（与渲染层同源：主进程推断 + 缓存）。 */
const manifest = ref<Live2DManifest | null>(null)

async function loadManifest(): Promise<void> {
  const path = modelPath.value
  const role = store.character?.active_id
  try {
    const result = await window.yuiro.inspectPetModel(path)
    if (path !== modelPath.value || role !== store.character?.active_id) return
    manifest.value = result
  } catch {
    manifest.value = null
  }
}

const problems = computed<Record<string, string>>(() => {
  const m = manifest.value
  const exprSet = new Set(expressions.value)
  const groups = new Map(motions.value.map((g) => [g.group, g.count]))
  const slotExpr = (slot: string): boolean => !!slot && (m?.index.expression[slot]?.length ?? 0) > 0
  const slotMotion = (slot: string): boolean => !!slot && (m?.index.motion[slot]?.length ?? 0) > 0
  const out: Record<string, string> = {}
  for (const row of rows.value) {
    const spec = parse(draft.value[row.name] ?? '')
    const expr = spec.expr || row.expression || ''
    const motionText = splitMotion(spec.motion || row.motion || '')
    const idx = motionText.index !== null ? motionText.index : (row.motionIndex ?? null)
    const exprSlot = row.expressionSlot || EMOTION_TO_SLOT[row.name] || ''
    const list: string[] = []

    if (expr && exprSet.size && !exprSet.has(expr) && !slotExpr(exprSlot)) {
      list.push(`表情「${expr}」当前模型没有，且槽位 ${exprSlot || '(无)'} 无候选`)
    }
    if (motionText.group) {
      const count = groups.get(motionText.group)
      if (count === undefined) {
        // 具体组不存在 → 只要槽位还有候选就能兜住，不算问题
        if (!slotMotion(row.motionSlot)) {
          list.push(`动作组「${motionText.group}」当前模型没有，且槽位 ${row.motionSlot || '(无)'} 无候选`)
        }
      } else if (idx !== null && (idx < 0 || idx >= count)) {
        list.push(`动作索引越界：${motionText.group}#${idx}（该组共 ${count} 个）`)
      }
    }
    out[row.name] = list.join('；')
  }
  return out
})

const problemCount = computed(() => Object.values(problems.value).filter(Boolean).length)

/** 试演反馈（点击后显示"演了什么"，否则点了没动静像坏了）。 */
const previewInfo = ref('')

/**
 * 试演：**直推桌宠**（表情 + 动作 + 时长一次下发），不依赖引擎在线。
 *
 * 以前这里调引擎 HTTP —— 引擎没起就完全点不动，也分不清是"表演配错了"
 * 还是"引擎不在"。现在调试台自己解析（参数优先取本地草稿，可以先试还没保存
 * 的搭配），引擎在不在都能演。
 */
async function run(name: string): Promise<void> {
  const row = rows.value.find((r) => r.name === name)
  lastPerf.value = name
  previewInfo.value = ''
  if (!row) return
  const spec = parse(draft.value[name] ?? '')
  const mt = splitMotion(spec.motion || row.motion || '')
  let expr = spec.expr || row.expression || ''
  let group = mt.group
  let index = mt.index !== null ? mt.index : (row.motionIndex ?? null)

  // 具体名不可用 → 按语义槽位解析（与渲染层同规则），让试演结果与真实链路一致
  if (!expr && row.expressionSlot) {
    expr = manifest.value?.index.expression[row.expressionSlot]?.[0] ?? ''
  }
  if (!group && row.motionSlot) {
    const candidates = manifest.value?.index.motion[row.motionSlot] ?? []
    if (candidates.length) {
      group = candidates[0].group
      index = candidates[0].index
    }
  }

  if(props.localPreview){
    emit('preview',{expression:expr,motion:group,motion_index:index,duration_ms:row.durationMs??undefined,performance:name})
    previewInfo.value=`正在舞台预览「${name}」`;return
  }
  try {
    await window.yuiro?.applyPetIntent?.({
      characterId: store.character?.active_id,
      modelPath: modelPath.value,
      name,
      expression: expr,
      motion: group,
      motionIndex: index,
      durationMs: row.durationMs ?? undefined,
    })
    previewInfo.value = `已试演「${name}」：表情 ${expr || '(默认)'} · 动作 ${
      group ? `${group}${index === null ? '' : '#' + index}` : '(无)'
    }`
  } catch (e) {
    saveError.value = e instanceof Error ? e.message : String(e)
  }
}

/* ── 列表行：引擎表演库 ∪ 草稿里新加还没保存的自定名 ── */
interface Row {
  name: string
  builtin: boolean
  note: string
  expression: string
  /** 表情语义槽位（S53）：具体名不可用时由模型清单解析 */
  expressionSlot: string
  motion: string
  motionIndex: number | null
  /** 动作语义槽位（S53） */
  motionSlot: string
  /** 引擎解析出的表演时长（ms；null = 未知） */
  durationMs: number | null
}

const rows = computed<Row[]>(() => {
  const list: Row[] = performances.value.map((p) => ({
    name: p.name,
    builtin: p.builtin !== false,
    note: p.note ?? '',
    expression: p.expression ?? '',
    expressionSlot: p.expression_slot ?? '',
    motion: p.motion ?? '',
    motionIndex: p.motion_index ?? null,
    motionSlot: p.motion_slot ?? '',
    durationMs: p.duration_ms ?? null,
  }))
  const known = new Set(list.map((r) => r.name))
  for (const name of Object.keys(draft.value)) {
    if (known.has(name)) continue
    list.push({
      name,
      builtin: false,
      note: '刚新增，保存后生效',
      expression: '',
      expressionSlot: '',
      motion: '',
      motionIndex: null,
      motionSlot: '',
      durationMs: null,
    })
  }
  return list
})

/** 动作选项：每个组的每个索引各一条。
 *  只提供"指定索引"，不提供随机 —— 随机会让同一表演时好时坏（S34 的结论）。 */
const motionOptions = computed(() =>
  motions.value.flatMap((g) =>
    Array.from({ length: g.count }, (_, i) => ({
      value: `${g.group}#${i}`,
      label: `${g.group} #${i}`,
    })),
  ),
)

/* ── 生命周期 ── */
/** 把草稿对齐到"当前生效"的那一套（有档案 = 档案的，没有 = 全局的）。 */
function syncDraft(): void {
  draft.value = readMap()
  exprDraft.value = readExprMap()
}

onMounted(() => {
  syncDraft()
  void loadManifest()
  void reloadModelDetail()
  void reloadPerformances()
})

// 换模型 → 可选的表情/动作跟着换，草稿也切到新模型对应的那一套
// （未保存的编辑会被丢弃：宁可丢，也不能拿着旧模型的表去改新模型的档案）
watch(modelPath, () => {
  syncDraft()
  void loadManifest()
  void reloadModelDetail()
})

// 配置在别处被改（切换模型 / 从磁盘重载 / 删档案）→ 未编辑时同步草稿，不覆盖正在改的内容
watch(
  () => [store.sections?.persona?.performance_map, store.sections?.persona?.profiles],
  () => { if (!dirty.value) syncDraft() },
)

// 保存成功提示几秒后自动收起
watch(savedAt, (v) => {
  if (!v) return
  window.setTimeout(() => { if (savedAt.value === v) savedAt.value = 0 }, 3000)
})
</script>

<template>
  <div class="bubble card-narrow pe">
    <div class="row-between">
      <div>
        <h3 class="bubble-title">表现档案（情绪 / 表演 → 表情 + 动作）</h3>
        <p class="hint">
          桌宠每次"表演"都是「一个表情 + 一个动作」的组合。这里可以逐个表演自己配、
          也能自定新表演名；留空即沿用内置。保存后**即时生效**（引擎热重载，无需重启）。
        </p>
      </div>
      <div class="pe-actions">
        <span v-if="dirty" class="pill pill-warn">未保存</span>
        <button class="btn" :disabled="saving || !dirty" @click="clearAll">全部还原</button>
        <button class="btn btn-primary" :disabled="saving || !dirty" @click="save">
          {{ saving ? '保存中…' : '保存' }}
        </button>
      </div>
    </div>

    <p v-if="saveError" class="pe-msg pe-err">{{ saveError }}</p>
    <p v-else-if="savedAt" class="pe-msg pe-ok">已保存并热重载，点 ▶ 可立刻试演。</p>

    <p v-if="detailError" class="pe-msg pe-err">{{ detailError }}</p>
    <p v-if="!configReady" class="hint">配置加载中…</p>

    <template v-else>
      <!-- 当前模型 + 档案状态：说清下面编辑的是"这个模型自己的表"还是全局表 -->
      <div class="pe-profile">
        <div class="pe-profile-info">
          <span class="pe-model">{{ modelLabel }}</span>
          <span v-if="editingProfile" class="pill pill-ok">档案 {{ profileKey }}</span>
          <span v-else class="pill pill-warn">无档案 · 正在改全局表</span>
        </div>
        <button class="btn" :disabled="saving" title="按当前模型的表情/动作名推断槽位并写入档案" @click="generateProfile">
          按模型自动生成
        </button>
        <button v-if="!editingProfile" class="btn" :disabled="saving" @click="createProfile">
          为它新建档案
        </button>
        <button v-else class="btn btn-danger" :disabled="saving" @click="deleteProfile">
          删除档案
        </button>
      </div>
      <p class="hint">
        <template v-if="editingProfile">
          下面的改动<strong>只作用于 {{ modelLabel }}</strong>；换回别的模型会自动套用它们各自的档案
          （没配档案的仍走全局表）。
        </template>
        <template v-else>
          当前模型还没有档案，下面的改动会写进<strong>全局表</strong>（所有没配档案的模型共用）。
          点「为它新建档案」可把当前这套存成它专属的，之后互不干扰。
        </template>
      </p>

      <!-- 情绪 → 表情 -->
      <div class="pe-section-title">情绪 → 表情</div>
      <div class="pe-emotions">
        <label v-for="e in EMOTIONS" :key="e.key" class="pe-emo">
          <span class="pe-emo-label">{{ e.label }}</span>
          <select
            class="pe-select"
            :value="exprDraft[e.key] ?? ''"
            @change="onEmotion(e.key, $event)">
            <option value="">回落默认</option>
            <option v-for="x in expressions" :key="x" :value="x">{{ x }}</option>
          </select>
        </label>
      </div>
      <p v-if="!expressions.length" class="hint">
        该模型没有声明表情（无 exp3.json）→ 情绪只能靠动作与语气表现。
        想要表情可手写 exp3.json 放进模型的 expressions/ 目录再登记到 model3.json。
      </p>

      <div class="pe-section-title">表演 → 表情 + 动作</div>
      <p v-if="problemCount" class="pe-msg pe-err">
        ⚠ {{ problemCount }} 个表演在当前模型上跑不起来（行首 ✗ 悬停看原因）——
        多半是换模型后旧的组名 / 表情名还留在配置里。
      </p>
      <p v-if="previewInfo" class="pe-msg pe-ok">{{ previewInfo }}</p>

      <div class="pe-list">
        <div v-for="row in rows" :key="row.name" class="pe-row">
          <div class="pe-info">
            <span class="pe-name">
              {{ row.name }}
              <span v-if="!row.builtin" class="pill pill-mute">自定</span>
              <span
                v-if="problems[row.name]"
                class="pill pill-err"
                :title="problems[row.name]">✗</span>
            </span>
            <span class="pe-effective" :title="row.note">
              当前：{{ row.expression || '默认表情'
              }}<template v-if="row.motion"> + {{ row.motion
                }}<template v-if="row.motionIndex !== null">#{{ row.motionIndex }}</template></template>
            </span>
          </div>

          <select
            class="pe-select"
            :value="parts(row.name).expr"
            title="表情（留空 = 由该表演的情绪经 expression_map 决定）"
            @change="onExpr(row.name, $event)">
            <option value="">跟随情绪</option>
            <option v-for="e in expressions" :key="e" :value="e">{{ e }}</option>
          </select>

          <select
            class="pe-select"
            :value="parts(row.name).motion"
            title="动作（留空 = 用内置表演包的动作）"
            @change="onMotion(row.name, $event)">
            <option value="">沿用内置动作</option>
            <option v-for="o in motionOptions" :key="o.value" :value="o.value">{{ o.label }}</option>
          </select>

          <div class="pe-btns">
            <button
              class="pe-icon"
              :class="{ on: lastPerf === row.name }"
              title="试演一次（直推桌宠，不需要引擎在线；先试未保存的草稿）"
              @click="run(row.name)">▶</button>
            <button
              v-if="draft[row.name] !== undefined"
              class="pe-icon"
              title="移除这条覆盖，回落到内置"
              @click="reset(row.name)">✕</button>
          </div>
        </div>
      </div>

      <p v-if="!rows.length" class="hint">引擎未启动，拿不到表演库。启动后再回来配置即可。</p>

      <div class="pe-add">
        <input
          v-model="newName"
          class="pe-input"
          placeholder="新表演名（英文，如 shy / wave）"
          @keydown.enter="addCustom" />
        <button class="btn" :disabled="!canAdd" @click="addCustom">新增自定表演</button>
        <span class="hint">保存后它就在表演库里，可被 LLM 点播。</span>
      </div>

      <p class="hint pe-foot">
        表情/动作到底长什么样？用上方「桌宠形象」卡里的表情与动作按钮逐个预览确认。
        <code>[persona.motion_map]</code> 仍然有效，但本页的搭配优先级更高。
      </p>
    </template>
  </div>
</template>

<style scoped>
.pe { max-width: 760px; }
.pe-actions { display: flex; align-items: center; gap: 8px; flex-shrink: 0; }

.pe-msg { margin: 10px 0 0; font-size: 12px; }
.pe-err { color: var(--err); }
.pe-ok { color: var(--ok); }

.pe-list { margin-top: 12px; display: flex; flex-direction: column; gap: 8px; }

/* 一行 = 名称 + 表情 + 动作 + 操作；窄屏退化成两列 */
.pe-row {
  display: grid;
  grid-template-columns: minmax(120px, 1.15fr) minmax(104px, 1fr) minmax(132px, 1.15fr) auto;
  align-items: center;
  gap: 8px;
  padding: 8px 10px;
  border-radius: var(--radius-md);
  background: var(--card-head);
}

.pe-info { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.pe-name {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  font-weight: 600;
}
.pe-effective {
  font-size: 11px;
  color: var(--muted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.pe-select,
.pe-input {
  width: 100%;
  padding: 6px 9px;
  border-radius: var(--radius-sm);
  border: 1px solid var(--border);
  background: var(--input);
  color: var(--text);
  font-size: 12px;
  font-family: inherit;
  outline: none;
}
.pe-select:focus,
.pe-input:focus { border-color: var(--accent); }

.pe-btns { display: flex; gap: 4px; }
.pe-icon {
  width: 26px;
  height: 26px;
  border-radius: 50%;
  border: 1px solid var(--border);
  background: transparent;
  color: var(--text-soft);
  cursor: pointer;
  font-size: 11px;
  line-height: 1;
  transition: background var(--dur-fast) ease, color var(--dur-fast) ease;
}
.pe-icon:hover { background: var(--btn-hover-bg); color: var(--accent); }
.pe-icon.on { background: var(--accent-soft); color: var(--accent); }

.pe-add { margin-top: 14px; display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.pe-add .pe-input { max-width: 220px; }

.pe-foot { margin-top: 12px; }
.pe-foot code {
  padding: 1px 5px;
  border-radius: 4px;
  background: var(--card-head);
}

/* ── 档案状态条 ── */
.pe-profile {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  margin: 12px 0 0;
  padding: 8px 10px;
  border-radius: var(--radius-md);
  background: var(--card-head);
}
.pe-profile-info { display: flex; align-items: center; gap: 8px; min-width: 0; }
.pe-model {
  font-size: 13px;
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* ── 分区标题 ── */
.pe-section-title {
  margin: 16px 0 8px;
  font-size: 12px;
  font-weight: 600;
  color: var(--text-soft);
  letter-spacing: 0.02em;
}

/* ── 情绪 → 表情（两列网格，省高度） ── */
.pe-emotions {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
}
.pe-emo {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 8px;
  border-radius: var(--radius-sm);
  background: var(--card-head);
}
.pe-emo-label { flex: none; width: 34px; font-size: 12px; color: var(--muted); }

@media (max-width: 720px) {
  .pe-row { grid-template-columns: 1fr 1fr; }
  .pe-emotions { grid-template-columns: 1fr; }
}
</style>
