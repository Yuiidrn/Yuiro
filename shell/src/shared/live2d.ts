/**
 * Live2D 资产语义槽位（主进程 / preload / 渲染层共用一份）。
 *
 * 为什么需要槽位：引擎只该表达"要什么语义"（打招呼 / 庆祝 / 思考），
 * 至于这个模型把"打招呼"放在第几个动作、叫什么名字，是**模型私有**的。
 * 以前内置表演包写死 `TapBody#5`，换模型就静默失效（Hotaru 只有一个 Motion 组）。
 *
 * 槽位是引擎与资产之间的稳定契约：
 *   引擎意图（slot） → 本文件的 manifest（slot → 具体 group#index / 表情名） → pixi 调用
 */

/** 表情语义槽位（8 个，覆盖现有三套资产与情绪词表）。 */
export type ExpressionSlot =
  | 'neutral'
  | 'happy'
  | 'sad'
  | 'angry'
  | 'surprised'
  | 'shy'
  | 'thinking'
  | 'playful'

/** 动作语义槽位（10 个）。 */
export type MotionSlot =
  | 'idle'
  | 'greet'
  | 'celebrate'
  | 'comfort'
  | 'surprise'
  | 'thinking'
  | 'sing'
  | 'angry'
  | 'nod'
  | 'look'

export const EXPRESSION_SLOTS: ExpressionSlot[] = [
  'neutral', 'happy', 'sad', 'angry', 'surprised', 'shy', 'thinking', 'playful',
]

export const MOTION_SLOTS: MotionSlot[] = [
  'idle', 'greet', 'celebrate', 'comfort', 'surprise', 'thinking', 'sing', 'angry', 'nod', 'look',
]

/** 情绪 → 表情槽位（与引擎的 emotion 词表对齐）。 */
export const EMOTION_TO_SLOT: Record<string, ExpressionSlot> = {
  happy: 'happy',
  sad: 'sad',
  angry: 'angry',
  excited: 'surprised',
  bored: 'neutral',
  thinking: 'thinking',
}

export interface ManifestExpression {
  name: string
  slot: ExpressionSlot | ''
}

export interface ManifestMotion {
  group: string
  index: number
  /** motion3 文件相对 model3.json 的路径 */
  file: string
  /** Meta.Loop */
  loop: boolean
  /** Meta.Duration 换算成毫秒 */
  durationMs: number
  slot: MotionSlot | ''
  /** 方向变体：C=中 / L=左 / R=右，'' = 无 */
  direction: 'C' | 'L' | 'R' | ''
}

/** 槽位覆盖统计（调试台「模型体检」展示用）。 */
export interface SlotCoverage {
  /** slot → 候选数量 */
  expression: Record<string, number>
  motion: Record<string, number>
  /** 未能推断出槽位的资源名（最多保留前 20 个，避免载荷过大） */
  unmappedExpressions: string[]
  unmappedMotions: string[]
  unmappedExpressionCount: number
  unmappedMotionCount: number
  hasLipSync: boolean
  hasEyeBlink: boolean
}

/**
 * 模型清单：一次扫描 model3.json + 每个 motion3 的 Meta，得到"这个模型能演什么"。
 * 渲染层据此把语义槽位解析成具体资源，不再做任何组名假设。
 */
export interface Live2DManifest {
  /** 归一化后的 web 路径（/live2d/...），失败时回退原始输入 */
  path: string
  /** model3.json 的绝对路径（排查用） */
  model3: string
  /** moc3 版本字节（>=6 表示 Cubism 5.3 导出，Core 5.1 读不了） */
  mocVersion: number
  expressions: ManifestExpression[]
  motions: ManifestMotion[]
  /** 预索引：解析 O(1)，渲染层不逐帧查表 */
  index: {
    expression: Record<string, string[]>
    motion: Record<string, { group: string; index: number }[]>
    idle: { group: string; index: number; durationMs: number }[]
  }
  coverage: SlotCoverage
  warnings: string[]
}
