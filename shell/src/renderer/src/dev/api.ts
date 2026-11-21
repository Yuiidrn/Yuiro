/**
 * 引擎 debug API 客户端 + 类型（开发调试窗口专用）。
 */
import { ENGINE_DEBUG_BASE } from '@shared'
import { notifySpeechSettings } from '../utils/speechSettingsSignal'
import type {
  ConfigResponse,
  CharacterView,
  KeyStatusResponse,
  LogsResponse,
  ProviderTestResult,
  StatusResponse,
} from '@shared'

/** L3 用户事实（含置信度衰减后的有效置信度） */
export interface Fact {
  subject: string
  key: string
  value: string
  confidence: number
  decay: number
  updated_at: number
  effective_confidence?: number
}

/** L2 情景记忆条目 */
export interface Episode {
  rowid: number
  text: string
  ts: number
  salience: number
}

/** 联网检索生效状态（GET /api/search/status，S51） */
export interface SearchStatusView {
  status: string
  /** 总开关在**引擎侧**的真实值（配置草稿未保存时为 false） */
  enabled: boolean
  /** enabled + key 都满足 → 工具对模型可见 */
  available: boolean
  /** 不可用时的**人话原因**（"已在设置中关闭" / "未配置密钥"） */
  hint: string
  provider: string
}

/** 知识库视图（GET /api/knowledge，S51） */
export interface KnowledgeView {
  ok: boolean
  stats: { chunks: number }
  /** 来源清单：让用户看得见"知识库里到底装了什么"（此前只有块数一个数字） */
  sources: { source: string; chunks: number; sample: string }[]
  note?: string
}

/** 记忆快照（GET /api/memory） */
export interface MemorySnapshot {
  facts: Fact[]
  episodes: Episode[]
  note?: string
}

/** 检索观测结果（GET /api/memory/search） */
export interface MemorySearchResponse {
  ok: boolean
  count: number
  note?: string
  results: { kind: string; text: string; score: number }[]
}

/** 记忆三通道快照（GET /api/memory/showcase，S17/S31） */
export interface MemoryShowcase {
  status: string
  detail?: string
  counts: { explicit: number; facts: number; episodes: number }
  explicit: Episode[]
  facts: Fact[]
  episodes: Episode[]
}

/** 关系记忆（GET /api/memory/relationship，S26） */
export interface RelationshipView {
  status: string
  detail?: string
  first_seen: number
  last_seen: number
  interactions: number
  tasks_completed: number
  explicit_memories: number
  milestones: string[]
  days_known: number
  summary: string
}

/** 归纳报告（POST /api/memory/consolidate，S28） */
export interface ConsolidationReport {
  status: string
  scanned: number
  candidates: number
  accepted: number
  written: number
  skipped_low_support: number
  skipped_existing: number
  llm_used: boolean
  details: { key: string; value: string; support: number }[]
}

/** 显式记忆（用户要求记住的事） */
export interface ExplicitItem {
  rowid: number
  text: string
  ts: number
  salience: number
}

export interface ExplicitList {
  status: string
  detail?: string
  items?: ExplicitItem[]
  count?: number
}

/** 任务视图（GET /api/task/list，S29；注意字段是 task_status，避免与外层 status 冲突） */
export interface TaskView {
  task_id: string
  goal: string
  task_status: string
  progress: string
  current_step: string
  attempts: number
  steps: string[]
  summary: string
}

export interface TaskList {
  status: string
  detail?: string
  count: number
  tasks: TaskView[]
}

/** 表演库条目（引擎侧配置驱动；expression/motion 为已解析出的具体资源） */
export interface PerformanceItem {
  name: string
  note?: string
  expression?: string
  /** 表情语义槽位（S53）：具体名不可用时由模型清单解析 */
  expression_slot?: string
  motion?: string
  /** 动作索引（null/undefined = 该组随机；引擎内置表演包已明确索引） */
  motion_index?: number | null
  /** 动作语义槽位（S53）：具体组不可用时由模型清单解析 */
  motion_slot?: string
  /** 该表演归属的情绪（表情默认由它经 expression_map 推出） */
  emotion?: string
  duration_ms?: number
  /** 是否内置表演包（false = [persona.performance_map] 里自定的） */
  builtin?: boolean
}

export interface PerformanceList {
  performances: PerformanceItem[]
}

/** 人格基线（S30） */
export interface EvalScenario {
  id: string
  category: string
  input: string
  expect: Record<string, unknown>
  note?: string
}

export interface EvalScenarios {
  status: string
  total: number
  by_category: Record<string, number>
  scenarios: EvalScenario[]
}

export interface EvalFailure {
  id: string
  category: string
  input: string
  reply: string
  tool_calls: string[]
  reasons: string[]
}

export interface EvalReport {
  status: string
  detail?: string
  model: string
  prompt_hash: string
  total: number
  passed: number
  failed: number
  pass_rate: number
  by_category: Record<string, { total: number; passed: number; pass_rate: number }>
  failures: EvalFailure[]
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const character = localStorage.getItem('yuiro-active-character')||''
  const secret = await window.yuiro?.getEngineSecret?.() || ''
  // ★ 防呆：引擎的接口**全都在 `/api` 前缀下**（router = APIRouter(prefix="/api")）。
  // 漏写前缀的后果很难查：后端只回 `404 Not Found`，前端页面就是一片空白
  // （实测踩过：日记页整页 Not Found，因为写成了 `/diary/list`）。
  // 这里在控制台直接点出来，让下一个漏写的人立刻看到，而不是靠对着日志猜。
  if (!path.startsWith('/api/')) {
    console.warn(`[api] 路径缺少 /api 前缀，必然 404：${path}`)
  }
  const res = await fetch(`${ENGINE_DEBUG_BASE}${path}`, {
    ...init,
    headers: { 'Content-Type': 'application/json', 'x-yuiro-secret': secret, 'x-yuiro-character':character, ...init?.headers },
  })
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`
    try {
      const body = await res.json()
      if (body?.detail) detail = body.detail
    } catch { /* ignore */ }
    throw new Error(detail)
  }
  return (await res.json()) as T
}

/* ── S51：日记（结构化保存 + 回顾）────────────────────────────────────────
 * 回顾走**独立于记忆库**的日记库（"仅保存"的日记也要能被用户看到）。
 * 搜索支持 2 字中文词（后端对短词回退子串匹配 —— trigram 索引对 <3 字无效）。
 */
export interface DiaryAsset {id:string;name:string;mime:string;size:number}

export interface DiaryBrief {
  title?:string
  id: number
  created_at: string
  summary: string
  mood_tags: string[]
  topics: string[]
  privacy: string
  memory_written: boolean
  has_review: boolean
}

export interface DiaryDetail {
  status: string
  diary: {
    title:string
    updated_at?:string
    revision:number
    attachments:DiaryAsset[]
    id: number
    created_at: string
    raw_text: string
    polished_text: string
    summary: string
    mood_tags: string[]
    topics: string[]
    followup_question: string
    privacy: string
    memory_written: boolean
    closing_review: string
  }
  tags: Record<string, string[]>
}

export interface DiaryListResponse {
  status: string
  count: number
  items: DiaryBrief[]
  note?: string
}

export interface DiaryStats {
  status: string
  total: number
  by_privacy: Record<string, number>
  top_moods: { mood: string; count: number }[]
}

function qs(params: Record<string, string | number>): string {
  const p = new URLSearchParams()
  Object.entries(params).forEach(([k, v]) => {
    if (v !== '' && v !== undefined && v !== null) p.set(k, String(v))
  })
  const s = p.toString()
  return s ? `?${s}` : ''
}

export const diaryApi = {
  edit:(id:number, value:{revision:number;title:string;raw_text:string;attachment_ids:string[]})=>request<{status:string;memory_written:boolean}>(`/api/diary/${id}`,{method:'PUT',body:JSON.stringify(value)}),
  revisions:(id:number)=>request<{status:string;items:DiaryDetail['diary'][]}>(`/api/diary/${id}/revisions`),
  // ⚠ 前缀必须是 `/api`（引擎 router = APIRouter(prefix="/api")）——
  // 这里此前漏写成 `/diary/...`，结果是日记页整页「Not Found」、日志里
  // `GET /diary/list 404`（实测：日记明明已落库却看不到）。
  list: (params: { q?: string; mood?: string; topic?: string; privacy?: string; limit?: number;offset?:number } = {}) =>
    request<DiaryListResponse>(`/api/diary/list${qs(params as Record<string, string | number>)}`),
  stats: () => request<DiaryStats>('/api/diary/stats'),
  detail: (id: number) => request<DiaryDetail>(`/api/diary/${id}`),
  remove: (id: number) =>
    request<{ status: string; memory_removed?: number }>(`/api/diary/${id}`, { method: 'DELETE' }),
  setPrivacy: (id: number, value: string) =>
    request<{ status: string; from?: string; to?: string; memory_removed?: number; memory_written?: number }>(
      `/api/diary/${id}/privacy${qs({ value })}`,
      { method: 'POST' },
    ),
  review: (id: number) =>
    request<{ status: string; review?: string }>(`/api/diary/${id}/review`, { method: 'POST' }),
}

export const api = {
  testSearch: (query: string) => request<{ status: string; note?: string; count?: number; latency_ms?: number; results?: { title: string; url: string; snippet: string; published_at?: string }[] }>('/api/search/test', {
    method: 'POST', body: JSON.stringify({ query }),
  }),
  getFishKey: () => request<KeyStatusResponse>('/api/providers/fish/key'),
  setFishKey: (key: string) => request<KeyStatusResponse>('/api/providers/fish/key', {
    method: 'PUT', body: JSON.stringify({ key }),
  }),
  clearFishKey: () => request<KeyStatusResponse>('/api/providers/fish/key', { method: 'DELETE' }),
  getConfig: () => request<ConfigResponse>('/api/config'),
  putConfig: async (patch: Record<string, Record<string, unknown>>, characterId?: string, revision?: number) => {
    const result=await request<ConfigResponse>('/api/config', {
      method: 'PUT',
      body: JSON.stringify({ patch, character_id: characterId, character_revision: revision }),
    })
    if(patch.vad||patch.tts)notifySpeechSettings(result.character?.active_id||characterId||'')
    return result
  },
  reloadConfig: async () => {
    const result=await request<ConfigResponse>('/api/config/reload', { method: 'POST' })
    notifySpeechSettings(result.character?.active_id||'')
    return result
  },
  switchCharacter: (id: string) => request<CharacterView>('/api/characters/switch', {
    method: 'POST', body: JSON.stringify({ id }),
  }),
  getStatus: () => request<StatusResponse>('/api/status'),
  /**
   * 组件自检。
   *
   * S52：`body` 用于传参 —— 目前只有语音合成试听用得到（`{lang}` 指定朗读语种，
   * 便于对比同一句话在不同语言下的听感）；其它组件不传，行为不变。
   */
  testProvider: (name: string, body?: Record<string, unknown>) =>
    request<ProviderTestResult>(`/api/providers/${name}/test`, {
      method: 'POST',
      body: JSON.stringify(body ?? {}),
    }),
  getLlmKey: () => request<KeyStatusResponse>('/api/providers/llm/key'),
  setLlmKey: (key: string) =>
    request<KeyStatusResponse>('/api/providers/llm/key', {
      method: 'PUT',
      body: JSON.stringify({ key }),
    }),
  // S51：联网检索的搜索服务 key（同走 keychain，只写不读明文）
  getSearchKey: () => request<KeyStatusResponse>('/api/providers/search/key'),
  setSearchKey: (key: string) =>
    request<KeyStatusResponse>('/api/providers/search/key', {
      method: 'PUT',
      body: JSON.stringify({ key }),
    }),
  /** 联网检索的**引擎侧**生效状态（与配置草稿区分：草稿可能还没保存）。 */
  getSearchStatus: () => request<SearchStatusView>('/api/search/status'),
  // S51：知识库（导入 / 查看来源 / 清除）——此前后端有、界面没有，于是"装了什么"无人知道
  getKnowledge: () => request<KnowledgeView>('/api/knowledge'),
  ingestKnowledge: (payload: { text?: string; source?: string; path?: string; force?: boolean }) =>
    request<{ ok: boolean; chunks?: number; blocked?: boolean; note?: string }>(
      '/api/knowledge/ingest',
      { method: 'POST', body: JSON.stringify(payload) },
    ),
  clearKnowledge: () =>
    request<{ ok: boolean; note?: string }>('/api/knowledge', { method: 'DELETE' }),
  getLogs: (n = 300) => request<LogsResponse>(`/api/logs/tail?n=${n}`),
  clearLogs: () => request<{ ok: boolean }>('/api/logs', { method: 'DELETE' }),
  // 审批模式：auto（自动通过，不弹窗）/ manual（人工审批弹窗）——实时切换不落盘
  getApprovalMode: () =>
    request<{ approval_mode: string }>('/api/systemd/approval-mode'),
  setApprovalMode: (mode: string) =>
    request<{ approval_mode: string }>('/api/systemd/approval-mode', {
      method: 'PUT',
      body: JSON.stringify({ approval_mode: mode }),
    }),

  // ── 记忆管理（调试台「记忆」页）──
  getMemory: () => request<MemorySnapshot>('/api/memory'),
  // 新增/更新事实（服务端会做同义 key 归并，返回归并后的 key）
  upsertFact: (key: string, value: string, confidence = 1.0) =>
    request<{ ok: boolean; key: string; value: string; note?: string }>(
      '/api/memory/facts',
      { method: 'PUT', body: JSON.stringify({ key, value, confidence }) },
    ),
  deleteFact: (key: string) =>
    request<{ ok: boolean; note?: string }>(
      `/api/memory/facts/${encodeURIComponent(key)}`,
      { method: 'DELETE' },
    ),
  // 检索观测：看某句话实际能召回哪些记忆（排查"记忆没呼出"）
  searchMemory: (q: string, topK = 5) =>
    request<MemorySearchResponse>(
      `/api/memory/search?q=${encodeURIComponent(q)}&top_k=${topK}`,
    ),
  deleteEpisode: (rowid: number) =>
    request<{ ok: boolean; note?: string }>(`/api/memory/episodes/${rowid}`, {
      method: 'DELETE',
    }),
  clearMemory: () => request<{ ok: boolean; note?: string }>('/api/memory', {
    method: 'DELETE',
  }),

  // ── S31：记忆洞察（S26/S28）/ 任务（S29）/ 人格基线（S30）──
  // 记忆三通道快照（explicit / facts / episodes）
  getMemoryShowcase: () => request<MemoryShowcase>('/api/memory/showcase'),
  // 关系记忆（认识多久 / 聊过多少次 / 一起做成过什么）
  getRelationship: () => request<RelationshipView>('/api/memory/relationship'),
  // 归纳（Episode → 稳定画像）；只写 L3 facts，不动会话
  consolidateMemory: (minSupport = 3, useLlm = false) =>
    request<ConsolidationReport>(
      `/api/memory/consolidate?min_support=${minSupport}&use_llm=${useLlm}`,
      { method: 'POST' },
    ),
  // 显式记忆（用户要求记住的事）列表 / 删除
  listExplicit: () => request<ExplicitList>('/api/memory/explicit'),
  deleteExplicit: (rowid: number) =>
    request<{ status: string; detail?: string }>(`/api/memory/explicit/${rowid}`, {
      method: 'DELETE',
    }),

  // 任务：列表（含待批准计划）/ 批准 / 拒绝 / 重试
  listTasks: (includeDone = false) =>
    request<TaskList>('/api/task/list?include_done=' + (includeDone ? 'true' : 'false')),
  approveTask: (taskId: string, steps = '') =>
    request<TaskView>(
      `/api/task/${encodeURIComponent(taskId)}/approve` +
        (steps ? `?steps=${encodeURIComponent(steps)}` : ''),
      { method: 'POST' },
    ),
  rejectTask: (taskId: string, reason = '') =>
    request<TaskView>(
      `/api/task/${encodeURIComponent(taskId)}/reject?reason=${encodeURIComponent(reason)}`,
      { method: 'POST' },
    ),
  retryTask: (taskId: string, reason = '') =>
    request<TaskView>(
      `/api/task/${encodeURIComponent(taskId)}/retry?reason=${encodeURIComponent(reason)}`,
      { method: 'POST' },
    ),

  // 人格基线（PB0）：列场景 / 跑一遍（live=false 为离线链路自检）
  getEvalScenarios: () => request<EvalScenarios>('/api/eval/personality/scenarios'),
  runEval: (limit = 0, live = false, includeTools = false) =>
    request<EvalReport>(
      `/api/eval/personality?limit=${limit}&live=${live}&include_tools=${includeTools}`,
      { method: 'POST' },
    ),

  // ── 桌宠表演库（调试台「外观 · 桌宠形象」内点击触发）──
  getPerformances: () => request<PerformanceList>('/api/avatar/performances'),
  runPerformance: (name: string) =>
    request<{ ok?: boolean; detail?: string }>(
      `/api/avatar/perform/${encodeURIComponent(name)}`,
      { method: 'POST' },
    ),
}
