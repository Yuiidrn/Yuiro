import { defineStore } from 'pinia'
import { api } from '../api'
import type { StatusResponse } from '@shared'

export const useStatusStore = defineStore('devStatus', {
  state: () => ({
    status: null as StatusResponse | null,
    loading: false,
    error: '',
  }),
  actions: {
    async refresh() {
      this.loading = true
      this.error = ''
      try {
        this.status = await api.getStatus()
      } catch (e) {
        this.error = e instanceof Error ? e.message : String(e)
      } finally {
        this.loading = false
      }
    },
  },
})
