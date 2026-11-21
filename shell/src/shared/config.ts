/**
 * 调试窗口与引擎 debug API 之间的类型契约。
 * 引擎端对应 engine/yuiro/debug_api.py + config.py 的 FIELD_META。
 */

/** 单个配置字段的元数据（驱动表单自动渲染）。 */
export interface FieldMeta {
  label: string
  type: 'string' | 'int' | 'float' | 'bool' | 'select' | 'string_list'
  options?: string[]
  secret?: boolean
  min?: number
  max?: number
  step?: number
  hint?: string
  /**
   * S54：该字段是一个**文件路径**，调试台会渲染「选择文件」按钮（调起系统文件框）。
   *
   * `audio` → 只列音频（wav/mp3/flac…）；`text` → 只列文本（txt/md…）。
   * 手填仍然可用（值就是普通字符串，引擎侧无需特殊处理）。
   */
  file?: 'audio' | 'text'
}

/** S54：系统文件/目录选择框的参数（主进程 `dev:pick-files`）。 */
export interface PickFilesOptions {
  /** 扩展名过滤：audio=音频，text=文本，any=不过滤（默认） */
  kind?: 'audio' | 'text' | 'any'
  /** 是否允许一次选多个（知识库导入用）。默认单选。 */
  multiple?: boolean
  /** 选目录而不是文件（知识库可导入整个目录）。 */
  directory?: boolean
  title?: string
}

/** S54：文件选择结果。取消时为 `{canceled: true, paths: []}`。 */
export interface PickFilesResult {
  canceled: boolean
  paths: string[]
}

/** 一个配置段（如 llm）的字段元数据映射。 */
export type SectionSchema = Record<string, FieldMeta>

/** 全部段的 schema：{ section: { field: FieldMeta } }。 */
export type ConfigSchema = Record<string, SectionSchema>

/** 配置值：字段值可以是标量、字符串数组（systemd.command）或嵌套字典（persona.emotion_hints）。 */
export type FieldValue = string | number | boolean | string[] | Record<string, string>

export type SectionValues = Record<string, FieldValue>

export type ConfigSections = Record<string, SectionValues>

/** GET/PUT /api/config 的响应负载。 */
export interface ConfigResponse {
  character?: CharacterView | null
  sections: ConfigSections
  schema: ConfigSchema
  backend: string
  /**
   * 「留空即回退引擎内置」的文本字段 → 内置默认文案（{ section: { field: text } }）。
   *
   * 目前只有提示词：配置里留空时引擎用的是自己的内置文案，光看配置是空串。
   * 调试台用它把**实际生效的内容**显示出来（并可在此基础上直接修改）。
   * 缺失/为空 = 引擎没提供（旧版本或导入失败），界面退回"留空 = 内置默认"的说明。
   */
  text_defaults?: Record<string, Record<string, string>>
}

export interface CharacterView {
  active_id: string
  revision: number
  switching: boolean
  items: { id: string; label: string }[]
  role_sections: string[]
}

/** GET /api/status 的响应负载。 */
export interface StatusResponse {
  engine: { version: string; chat_backend: string }
  systemd: {
    transport: string
    http_url: string
    approval_mode: string
    tool_count: number
  }
  providers: Record<string, Record<string, unknown>>
}

/** POST /api/providers/{name}/test 的响应负载。 */
export interface ProviderTestResult {
  provider?: string
  status: 'ok' | 'warn' | 'error'
  latency_ms?: number
  backend?: string
  sample?: string
  detail?: string
  [k: string]: unknown
}

/** GET/PUT /api/providers/llm/key 的响应负载。 */
export interface KeyStatusResponse {
  status: 'set' | 'unset'
  detail?: string
}

/** GET /api/logs/tail 的响应负载。 */
export interface LogEntry {
  ts: number
  level: string
  source: string
  message: string
}

export interface LogsResponse {
  count: number
  logs: LogEntry[]
}

/** 引擎 debug API 的 base URL（localhost-only）。 */
export const ENGINE_DEBUG_BASE = 'http://127.0.0.1:8200'
