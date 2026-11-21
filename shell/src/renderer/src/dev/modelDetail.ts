/**
 * 解析模型自带的 ``model3.json``，列出它**真实拥有**的表情与动作组。
 *
 * 为什么单独抽成一个模块：调试台有两处都要这份数据 ——
 *   · 桌宠形象卡（ModelPicker）：试动作 / 预览表情的按钮列表；
 *   · 表演搭配编辑器（PerformanceEditor）：表情与动作下拉框的选项来源。
 * 两边各写一份必然会「改一处漏一处」（本项目已多次踩过这个坑），故收在此处做唯一真相源。
 *
 * 注意：下拉框只能选模型自带的资源 —— 换了模型，能选的表情/动作就跟着变。
 * 这也是"换模型后动作组名全变"这个坑的解法：不必再手记 `TapBody` 这种名字。
 */

/** 一个动作组（组名 + 该组动作数量，用于生成「组名#索引」选项）。 */
export interface MotionGroup {
  group: string
  count: number
}

export interface ModelDetail {
  motions: MotionGroup[]
  /** 表情名（model3.json 的 FileReferences.Expressions[].Name） */
  expressions: string[]
  /** 读取失败原因（空 = 正常）；调用方通常只显示，不阻断其它功能 */
  error: string
}

/**
 * 拉取并解析模型明细。
 *
 * 全程不抛错：路径为空 / 文件 404 / JSON 坏掉都返回带 `error` 的空结果，
 * 让调用方可继续渲染其余部分（模型明细只是"选项来源"，不是核心链路）。
 */
export async function fetchModelDetail(modelPath: string): Promise<ModelDetail> {
  const empty: ModelDetail = { motions: [], expressions: [], error: '' }
  const path = (modelPath || '').trim()
  if (!path) return empty
  try {
    // 目录名可能含空格（如 `Hotaru Shiomi`）：只转义空格，幂等且不会破坏已有的 %20
    const res = await fetch(path.replace(/ /g, '%20'))
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    const data = (await res.json()) as {
      FileReferences?: {
        Motions?: Record<string, unknown[]>
        Expressions?: { Name?: string }[]
      }
    }
    const refs = data.FileReferences ?? {}

    const rawMotions = refs.Motions
    const motions: MotionGroup[] =
      rawMotions && typeof rawMotions === 'object'
        ? Object.entries(rawMotions)
            // 空组名（mao_pro 里有 "" 这种键）与空数组都要滤掉，否则下拉框会出现幽灵选项
            .filter(([group, arr]) => !!group && Array.isArray(arr) && arr.length > 0)
            .map(([group, arr]) => ({ group, count: arr.length }))
        : []

    const expressions = Array.isArray(refs.Expressions)
      ? refs.Expressions.map((it) => String(it?.Name ?? '')).filter(Boolean)
      : []

    return { motions, expressions, error: '' }
  } catch (e) {
    return {
      ...empty,
      error: `读取模型明细失败：${e instanceof Error ? e.message : String(e)}`,
    }
  }
}
