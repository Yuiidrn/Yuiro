import { defineStore } from 'pinia'
import { api } from '../api'
import type { LogEntry } from '@shared'

export const useLogStore = defineStore('devLogs', {
  state: () => ({
    logs: [] as LogEntry[],
    source: '',
    level: '',
    paused: false,
    error: '',
  }),
  getters: {
    filtered(state): LogEntry[] {
      return state.logs.filter(
        (l) =>
          (!state.source || l.source === state.source) &&
          (!state.level || l.level === state.level),
      )
    },
  },
  actions: {
    async refresh() {
      this.error = ''
      try {
        const res = await api.getLogs(500)
        this.logs = res.logs
      } catch (e) {
        this.error = e instanceof Error ? e.message : String(e)
      }
    },
    async clear() {
      await api.clearLogs()
      this.logs = []
    },
  },
})
