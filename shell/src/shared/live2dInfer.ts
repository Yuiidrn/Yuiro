/**
 * Live2D 语义槽位推断（**纯函数**，无 fs / electron 依赖）。
 *
 * 单独放这里的两个理由：
 *   1. 主进程（manifest）与测试共用同一份规则，不会"两边各写一套"；
 *   2. 可以脱离 electron 直接跑（`esbuild` 转译后 node 调用）。
 *
 * 原则：**能从名字看出来的才推断，看不出来就留空**（绝不猜）。
 *   · Hotaru：`mtn_bye01_C` / `exp_smile03` → 语义清晰，零配置可接入；
 *   · Hiyori：`Hiyori_m01` / `happy` → 动作名无语义，靠档案覆盖；
 *   · 肥牛：`expression2..7` → 表情名无语义，靠档案覆盖。
 */
import type { ExpressionSlot, MotionSlot } from './live2d'

/** 表情语义词 → 槽位。 */
export const EXPRESSION_WORDS: Record<string, ExpressionSlot> = {
  // neutral（平静 / 默认）
  idle: 'neutral', neutral: 'neutral', normal: 'neutral', default: 'neutral', calm: 'neutral', shadow: 'neutral',
  // happy
  smile: 'happy', bsmile: 'happy', happy: 'happy', joy: 'happy', laugh: 'happy', grin: 'happy', cheerful: 'happy',
  // sad
  sad: 'sad', cry: 'sad', tear: 'sad', pale: 'sad', anxiety: 'sad', worry: 'sad', down: 'sad',
  // angry
  angry: 'angry', anger: 'angry', mad: 'angry', rage: 'angry',
  // surprised
  surprised: 'surprised', surprise: 'surprised', panic: 'surprised', shock: 'surprised',
  // shy
  shy: 'shy', blush: 'shy', heart: 'shy', embarrassed: 'shy',
  // thinking
  thinking: 'thinking', think: 'thinking', puzzled: 'thinking', question: 'thinking', confuse: 'thinking',
  // playful
  kime: 'playful', kirakira: 'playful', spin: 'playful', playful: 'playful', wink: 'playful', smug: 'playful',
  sing: 'playful',
}

/** 动作语义词 → 槽位。 */
export const MOTION_WORDS: Record<string, MotionSlot> = {
  idle: 'idle',
  // 招呼 / 告别
  bye: 'greet', hello: 'greet', greet: 'greet', wave: 'greet', welcome: 'greet', bow: 'greet',
  // 庆祝
  celebrate: 'celebrate', kime: 'celebrate', spin: 'celebrate', dance: 'celebrate', clap: 'celebrate', joy: 'celebrate',
  // 安抚行为不等于角色自身悲伤；sad/cry/tear需审定后由角色档案显式指定。
  comfort: 'comfort', pat: 'comfort', hug: 'comfort',
  // 惊讶
  surprised: 'surprise', surprise: 'surprise', panic: 'surprise', shock: 'surprise',
  // 思考
  thinking: 'thinking', think: 'thinking', puzzled: 'thinking', question: 'thinking', confuse: 'thinking',
  // 唱歌
  sing: 'sing', singing: 'sing',
  // 生气
  angry: 'angry', anger: 'angry', mad: 'angry', serious: 'angry',
  // 点头
  nod: 'nod',
  // 查看 / 环顾
  look: 'look', check: 'look', watch: 'look', search: 'look',
}

export interface ParsedMotionName {
  word: string
  direction: 'C' | 'L' | 'R' | ''
}

/**
 * 动作文件名 → { 语义词, 方向 }。
 * 支持 `mtn_<word><NN>_<C|L|R>` / `misc_<word>`（Hotaru）与裸名字 `wave.motion3.json`；
 * 认不出的（如 `Hiyori_m01`）会返回未映射的词（'hiyori'），由词表判定为空。
 */
export function parseMotionName(file: string): ParsedMotionName {
  const base = (String(file ?? '').split(/[\\/]/).pop() || '').replace(/\.motion3\.json$/i, '')
  const m = base.match(/^(?:mtn|misc)_([a-z]+?)(\d+)?(?:_([CLR]))?$/i)
  if (m) {
    const dir = (m[3] || '').toUpperCase()
    return {
      word: (m[1] || '').toLowerCase(),
      direction: dir === 'C' || dir === 'L' || dir === 'R' ? dir : '',
    }
  }
  const g = base.match(/^([a-z]+)/i)
  return { word: (g?.[1] || '').toLowerCase(), direction: '' }
}

/** 表情名 → 语义词（`exp_smile03` → smile；`happy` → happy；`expression2` → expression）。 */
export function parseExpressionName(name: string): string {
  const raw = String(name ?? '')
  const m = raw.match(/^(?:exp_)?([a-z]+?)(\d+)?$/i)
  return (m?.[1] || raw).toLowerCase()
}

/** 表情名 → 槽位（'' = 无法推断）。 */
export function inferExpressionSlot(name: string): ExpressionSlot | '' {
  return EXPRESSION_WORDS[parseExpressionName(name)] ?? ''
}

/**
 * 动作 → 槽位（'' = 无法推断）。
 * `group` 仅用于一条启发式：整组叫 `Idle` 时，组内动作视为待机
 * （Hotaru 没有 Idle 组，靠文件名里的 `idle` 推断）。
 */
export function inferMotionSlot(group: string, file: string): MotionSlot | '' {
  const { word } = parseMotionName(file)
  const byName = MOTION_WORDS[word]
  if (byName) return byName
  if (String(group ?? '').trim().toLowerCase() === 'idle') return 'idle'
  return ''
}
