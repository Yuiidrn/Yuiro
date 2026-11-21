import { defineStore } from 'pinia'
import { api } from '../api'
import type { CharacterView, ConfigSchema, ConfigSections } from '@shared'

export const useConfigStore = defineStore('devConfig', {
  state: () => ({
    sections: {} as ConfigSections,
    schema: {} as ConfigSchema,
    backend: '',
    character: null as CharacterView | null,
    switching: false,
    hasDraftChanges: false,
    loadVersion: 0,
    /** 「留空即回退引擎内置」的文本字段的内置文案（见 ConfigResponse.text_defaults） */
    textDefaults: {} as Record<string, Record<string, string>>,
    loading: false,
    error: '',
    saving: false,
    saveError: '',
  }),
  getters: {
    /**
     * 某字段**实际生效**的文本：配置里有值就用配置的，留空则回退引擎内置。
     * 调试台用它显示提示词的"当前生效内容"（配置留空时不再是一片空白）。
     */
    effectiveText: (state) => {
      return (section: string, field: string): string => {
        const saved = String(state.sections?.[section]?.[field] ?? '')
        return saved || String(state.textDefaults?.[section]?.[field] ?? '')
      }
    },
    /** 该字段的生效值来自哪里：config=已写进配置，builtin=回退引擎内置，none=两边都空 */
    textSource: (state) => {
      return (section: string, field: string): 'config' | 'builtin' | 'none' => {
        if (String(state.sections?.[section]?.[field] ?? '').trim()) return 'config'
        if (String(state.textDefaults?.[section]?.[field] ?? '').trim()) return 'builtin'
        return 'none'
      }
    },
  },
  actions: {
    async load() {
      const version = ++this.loadVersion
      this.loading = true
      this.error = ''
      try {
        const res = await api.getConfig()
        if (version !== this.loadVersion) return
        this.sections = res.sections
        this.character = res.character ?? null
        if (this.character) localStorage.setItem('yuiro-active-character', this.character.active_id)
        this.schema = res.schema
        this.backend = res.backend
        this.textDefaults = res.text_defaults ?? {}
      } catch (e) {
        this.error = e instanceof Error ? e.message : String(e)
      } finally {
        this.loading = false
      }
    },
    async applySection(section: string, values: Record<string, unknown>) {
      this.saving = true
      this.saveError = ''
      try {
        const role = this.character?.active_id
        const revision = this.character?.revision
        const res = await api.putConfig({ [section]: values }, role, revision)
        if (this.character?.active_id !== role || this.character?.revision !== revision) {
          throw new Error('角色已切换，旧操作已停止')
        }
        this.sections = res.sections
        this.backend = res.backend
        this.hasDraftChanges = false
        this.textDefaults = res.text_defaults ?? {}
      } catch (e) {
        this.saveError = e instanceof Error ? e.message : String(e)
        throw e
      } finally {
        this.saving = false
      }
    },
    async reload() {
      this.loading = true
      this.error = ''
      try {
        const res = await api.reloadConfig()
        this.sections = res.sections
        this.character = res.character ?? null
        this.schema = res.schema
        this.backend = res.backend
        this.textDefaults = res.text_defaults ?? {}
      } catch (e) {
        this.error = e instanceof Error ? e.message : String(e)
      } finally {
        this.loading = false
      }
    },
    async switchCharacter(id: string) {
      this.loadVersion++
      this.switching = true
      this.saveError = ''
      try {
        await api.switchCharacter(id)
      } catch (e) {
        this.saveError = e instanceof Error ? e.message : String(e)
      } finally {
        await this.load()
        this.hasDraftChanges = false
        this.switching = false
      }
    },
  },
})
