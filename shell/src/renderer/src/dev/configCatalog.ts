/**
 * 调试台「结构目录」——本文件是调试台信息架构的唯一真相源。
 *
 * 三件事都在这里定义：
 *   1. DEV_TABS        导航分组与页面（tab）清单
 *   2. TAB_SECTIONS    每个页面承载哪些引擎配置段
 *   3. SECTION_CATALOG 每个配置段的字段分级（关键 / 高级 / 条件显示）
 *
 * 设计原则：
 *   · 页面 = 用户想干什么（配大脑 / 调声音 / 看日志），而不是照抄引擎的技术分层；
 *   · 配置项默认只露关键字段，其余收进「高级」，做到开箱即用；
 *   · 引擎 FIELD_META 里新增字段不会污染界面——未登记的字段一律归入「高级」。
 *
 * 注意：本文件只描述展示层，不改动引擎 FIELD_META。
 */

/* ===========================================================================
 * 一、导航与页面（tab）
 * ======================================================================== */

export type DevTab =
  // 调教：决定桌宠怎么思考、怎么说话、怎么记事（日常主界面）
  | 'brain' | 'speech' | 'persona' | 'memory' | 'diary' | 'search'
  // 调试：桌宠看起来是什么样、界面元素怎么表现
  | 'appearance' | 'ui'
  // 其他：运维与观察类工具，以及低频配置
  | 'overview' | 'task' | 'voiceDebug' | 'logs' | 'baseline'
  | 'initiative' | 'safety' | 'env'

export interface DevTabItem {
  key: DevTab
  label: string
  icon: string
}

export interface DevTabGroup {
  title: string
  /** 默认收起的分组（用于把低频项折叠起来，保持侧栏轻便） */
  collapsedByDefault?: boolean
  items: DevTabItem[]
}

/**
 * 导航分组：
 *   调教 / 调试 = 日常主界面（改配置、调观感）；
 *   其他       = 运维观察类工具 + 低频配置，默认折起，需要时再展开。
 */
export const DEV_TABS: DevTabGroup[] = [
  {
    title: '调教',
    items: [
      { key: 'brain', label: '大脑', icon: 'solar:cpu-bolt-bold' },
      { key: 'speech', label: '声音', icon: 'solar:music-note-slider-bold' },
      { key: 'persona', label: '性格', icon: 'solar:user-heart-bold' },
      { key: 'memory', label: '记忆', icon: 'solar:history-3-bold' },
      { key: 'diary', label: '日记', icon: 'solar:notebook-bold' },
      // S51：联网检索**独立成页**（原挤在「能力与安全」里，用户实测反馈：
      // 它既要用总开关、又要配 key，还牵扯隐私说明，值得单独一页）。
      { key: 'search', label: '联网', icon: 'solar:global-bold' },
    ],
  },
  {
    title: '调试',
    items: [
      { key: 'appearance', label: '外观', icon: 'solar:mirror-left-bold' },
      { key: 'ui', label: 'UI', icon: 'solar:slider-horizontal-bold' },
    ],
  },
  {
    title: '其他',
    collapsedByDefault: true,
    items: [
      { key: 'overview', label: '总览', icon: 'solar:pulse-bold' },
      { key: 'task', label: '任务', icon: 'solar:checklist-minimalistic-bold' },
      { key: 'voiceDebug', label: '语音联调', icon: 'solar:soundwave-bold' },
      { key: 'logs', label: '日志', icon: 'solar:document-text-bold' },
      { key: 'baseline', label: '人格基线', icon: 'solar:chart-2-bold' },
      { key: 'initiative', label: '主动性', icon: 'solar:bell-bing-bold' },
      { key: 'safety', label: '能力与安全', icon: 'solar:shield-check-bold' },
      { key: 'env', label: '运行环境', icon: 'solar:server-square-bold' },
    ],
  },
]

/** 每个页面承载的引擎配置段（顺序即页面内卡片顺序）。 */
export const TAB_SECTIONS: Partial<Record<DevTab, string[]>> = {
  // 顺序即卡片顺序：语言紧跟大模型（她用什么语言思考是大脑的事，说什么语言也是）
  brain: ['llm'],
  speech: ['language', 'tts', 'asr', 'vad'],
  memory: ['memory'],
  diary: ['diary'],
  search: ['search'],
  initiative: ['proactive', 'presence'],
  safety: ['capability', 'systemd', 'transaction'],
  env: ['server', 'observability', 'context'],
}

/** 每页一句话说明：让用户不用猜「这一页能干什么」。 */
export const TAB_DESC: Record<DevTab, string> = {
  overview: '引擎与守护进程是否在线，各组件能否跑通。',
  task: '它正在替你做什么、做到哪一步，以及等你点头的计划。',
  voiceDebug: '实时观察语音链路：VAD → ASR → LLM → TTS。',
  logs: '引擎运行日志，排查问题看这里。',
  baseline: '同一批固定场景反复跑，看人格有没有变化。',
  brain: '配置桌宠使用的大模型与思考参数。',
  speech: '统一配置展示语言、朗读语言与语音引擎，让语言和音色相互对齐。',
  persona: '她是谁、怎么说话。',
  memory: '她记得住什么、你给她看过什么资料，以及怎么把记忆清干净。',
  diary: '你写下的生活片段：回顾、筛选、搜索，以及隐私档位（她能不能提起）与吐槽设置。',
  search: '让她能查时效性信息并给出可核验的来源。需要总开关 + 搜索服务 Key；查询词会发送给第三方。',
  initiative: '她什么时候可以主动找你，以及如何不打扰你。',
  safety: '她有多大权限、动文件要不要你确认、操作能否回滚。',
  env: '监听地址、日志级别、上下文预算。一般保持默认。',
  appearance: '桌宠用哪个 Live2D 模型，以及动作 / 表情试播与表演搭配。',
  ui: '桌宠的界面表现：免打扰、主题、窗口与模型几何、回复气泡 / 歌单卡 / 聊天坞的样子。'
    + '本页所有调整都是热重载 —— 改完回车即生效，无需点保存。',
}

/* ===========================================================================
 * 二、配置段字段分级
 * ======================================================================== */

/** 按某字段的取值，条件性地显示一组字段。 */
export interface ConditionalFields {
  /** 依据字段（通常是 provider） */
  field: string
  /** 当依据字段的值命中其中之一时 */
  equals: string[]
  /** 显示的字段列表 */
  fields: string[]
}

export interface SectionCatalog {
  /** 引擎 section key */
  key: string
  /** 中文标题 */
  title: string
  /** 一句话说明这个模块是干什么的 */
  subtitle: string
  /** 关键字段：默认显示 */
  essential: string[]
  /** 高级字段：默认隐藏，点「高级」才展开 */
  advanced?: string[]
  /** 条件字段：随依据字段取值动态显示 */
  conditional?: ConditionalFields[]
}

export const SECTION_CATALOG: Record<string, SectionCatalog> = {
  /* ── 调教 · 大脑 ── */
  llm: {
    key: 'llm',
    title: '大模型',
    subtitle: '桌宠的「大脑」。填好服务商、模型和 API Key 即可对话。',
    essential: ['provider', 'model', 'base_url'],
  },

  /* ── 调教 · 大脑 · 语言（S52） ── */
  language: {
    key: 'language',
    title: '语言',
    subtitle: '她「内部思考」始终是中文；这里只管两件对外的事——气泡文字、嘴里念的语音。'
      + '参考音频可能是别的语种（现有日文/英文参考），朗读语言设成参考的语种才有最佳效果。',
    essential: ['display_language', 'speak_language'],
    advanced: ['translate_mode', 'translate_timeout_s'],
  },

  /* ── 调教 · 声音 ── */
  tts: {
    key: 'tts',
    title: '语音合成（说）',
    subtitle: '把文字变成声音。按所选引擎只显示相关参数。',
    essential: ['provider'],
    conditional: [
      { field: 'provider', equals: ['fish'], fields: ['fish_model', 'fish_reference_id', 'fish_latency', 'fish_speed', 'fish_transport', 'segment_streaming', 'reply_tts_enabled'] },
      { field: 'provider', equals: ['edge-tts'], fields: ['default_language', 'segment_streaming'] },
      { field: 'provider', equals: ['cosyvoice'], fields: ['tts_url', 'backend', 'reference_wav', 'reference_text'] },
      { field: 'provider', equals: ['gptsovits'], fields: ['tts_url', 'tts_text_language'] },
      {
        field: 'provider',
        equals: ['siliconflow'],
        fields: ['siliconflow_key', 'siliconflow_model', 'siliconflow_voice', 'siliconflow_reference_wav', 'siliconflow_reference_text'],
      },
    ],
    advanced: ['instruct_zh', 'instruct_en'],
  },
  asr: {
    key: 'asr',
    title: '语音识别（听）',
    subtitle: '把你说的话转成文字。默认参数已可用，通常只需确认语言。',
    essential: ['model', 'language'],
    advanced: ['provider', 'device', 'compute_type', 'beam_size', 'vad_filter', 'initial_prompt'],
  },
  vad: {
    key: 'vad',
    title: '语音活动检测',
    subtitle: '判断你什么时候开始/停止说话。听不清或太灵敏时才需要调。',
    // 「允许插话打断」放在 essential：它是**行为开关**（要不要让她被打断），
    // 与下面那些"灵敏度参数"性质不同，用户一眼就能找到、随时可关。
    essential: ['barge_in_enabled', 'db_threshold', 'probability_threshold'],
    advanced: ['provider', 'smoothing_window', 'required_hits', 'required_misses', 'barge_margin_db'],
  },

  /* ── 调教 · 记忆 ── */
  memory: {
    key: 'memory',
    title: '记忆行为',
    subtitle: '她怎么记、每次想起多少。条数越多越聪明，也越慢。',
    // S51：关键项换成"用户真会调的"（带入条数 / 相关度门槛）；
    // 存储方式、语义模型、融合参数都收进「高级」—— 它们是内部实现，
    // 摆在首屏只会让人不敢动（此前标题栏还有 RRF k 这类术语）。
    essential: ['auto_inject_top_k', 'auto_inject_threshold'],
    advanced: ['backend', 'embedder', 'rrf_k', 'memory_prompt'],
  },

  /* ── 调教 · 主动性 ── */
  proactive: {
    key: 'proactive',
    title: '定时关怀（轻）',
    subtitle: '按随机间隔偶尔打个招呼，与「存在感」是两套独立机制。',
    essential: ['enabled', 'min_interval_s', 'max_interval_s'],
  },
  presence: {
    key: 'presence',
    title: '存在感（事件驱动）',
    subtitle: '基于事件与注意力策略主动关心你，带静默时段与打扰上限。',
    essential: ['enabled', 'quiet_hours'],
    advanced: ['cooldown_s', 'max_urgency', 'idle_trigger_s', 'tick_s'],
  },

  /* ── 系统 · 能力与安全 ── */
  search: {
    key: 'search',
    title: '联网检索',
    subtitle: '让她能查时效性内容，并给出可点开核验的来源。查询词会发送给第三方搜索服务，默认关闭。',
    essential: ['enabled', 'provider', 'top_k'],
    advanced: ['timeout_s', 'refine_results'],
  },
  capability: {
    key: 'capability',
    title: '权限档位',
    subtitle: '总闸门：越低越安全。写操作是否放行由这里与审批模式共同决定。',
    essential: ['profile'],
  },
  systemd: {
    key: 'systemd',
    title: '系统操作与审批',
    subtitle: '执行后端与审批模式。审批模式改完保存即生效，无需重启。',
    essential: ['backend', 'approval_mode'],
    advanced: ['file_roots', 'transport', 'command', 'http_url'],
  },
  transaction: {
    key: 'transaction',
    title: '文件事务（可回滚）',
    subtitle: '开启后改/移/删文件会先自动备份，可随时恢复刚才的操作。',
    essential: ['enabled', 'keep'],
    advanced: ['backup_root'],
  },

  /* ── 系统 · 运行环境 ── */
  server: {
    key: 'server',
    title: '服务与鉴权',
    subtitle: '引擎监听地址与共享密钥。改动后需重启引擎。',
    essential: [],
    advanced: ['host', 'port', 'shared_secret'],
  },
  observability: {
    key: 'observability',
    title: '日志与监控',
    subtitle: '排查问题时调低日志级别可以看到更多细节。',
    essential: ['log_level'],
    advanced: ['metrics_port'],
  },
  context: {
    key: 'context',
    title: '上下文与裁剪',
    subtitle: '喂给模型的上下文预算。超预算时按优先级裁掉低优先段。',
    essential: ['budget_tokens'],
    advanced: ['tool_result_max_chars'],
  },
}

/**
 * 算出某配置段「当前应该显示哪些字段」。
 *
 * 规则：关键项 + 命中的条件项（+ 高级项，当 showAdvanced 为真）
 * 未登记进目录的字段 → 归为高级（隐藏），避免引擎新增字段就污染界面。
 */
export function resolveVisibleFields(
  section: string,
  allKeys: string[],
  draft: Record<string, unknown>,
  showAdvanced: boolean,
): string[] {
  const cat = SECTION_CATALOG[section]
  if (!cat) return allKeys

  const picked = new Set<string>(cat.essential)

  for (const cond of cat.conditional ?? []) {
    if (cond.equals.includes(String(draft[cond.field] ?? ''))) {
      for (const f of cond.fields) picked.add(f)
    }
  }

  if (showAdvanced) {
    for (const f of cat.advanced ?? []) picked.add(f)
    const known = new Set([
      ...cat.essential,
      ...(cat.advanced ?? []),
      ...(cat.conditional ?? []).flatMap((c) => c.fields),
    ])
    for (const k of allKeys) if (!known.has(k)) picked.add(k)
  }

  // 保持引擎返回的原始顺序，避免字段跳动
  return allKeys.filter((k) => picked.has(k))
}

/** 某配置段是否有被隐藏的字段（决定是否显示「高级」开关）。 */
export function hasHiddenFields(section: string, allKeys: string[]): boolean {
  const cat = SECTION_CATALOG[section]
  if (!cat) return false
  const known = new Set([
    ...cat.essential,
    ...(cat.advanced ?? []),
    ...(cat.conditional ?? []).flatMap((c) => c.fields),
  ])
  return allKeys.some((k) => !known.has(k)) || (cat.advanced ?? []).length > 0
}

/** 由给定的字段列表生成「关键值摘要」（如「qwen · qwen-plus」）。 */
export function summaryOfFields(
  keys: string[],
  meta: Record<string, { type?: string }>,
  draft: Record<string, unknown>,
): string {
  const parts: string[] = []
  for (const k of keys) {
    const v = draft[k]
    if (v === undefined || v === null || v === '') continue
    if (meta[k]?.type === 'bool') {
      if (v === true) parts.push('已开启')
      continue
    }
    parts.push(String(v))
  }
  return parts.join(' · ')
}

/** 卡片收起时展示的关键值摘要（如「qwen · qwen-plus」），减少点击。 */
export function essentialSummary(
  section: string,
  meta: Record<string, { type?: string }>,
  draft: Record<string, unknown>,
): string {
  const cat = SECTION_CATALOG[section]
  if (!cat) return ''
  return summaryOfFields(cat.essential, meta, draft)
}

/* ===========================================================================
 * 三、已知限制
 *
 * 只记录「用户能在界面上感受到、但我们尚未处理」的事项，措辞面向使用者。
 * 后端补齐后请删除对应条目。
 * ======================================================================== */

export const LIMITATIONS: string[] = [
  // 已补齐：知识库（导入/来源清单/清除）现在有界面了（S51 的 KnowledgePanel）
  '网易云配置段（[netease]）尚未提供字段元数据，因此暂不可视化编辑。',
]
