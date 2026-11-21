import { useLocalStorage } from '@vueuse/core'
import { computed } from 'vue'

export function useContourPref() {
  const debug = useLocalStorage('yuiro-contour-debug', false)
  const rawThreshold = useLocalStorage('yuiro-contour-threshold', 24)
  const rawTolerance = useLocalStorage('yuiro-contour-tolerance', 2)
  const threshold = computed({ get: () => Math.max(1, Math.min(254, Number(rawThreshold.value) || 24)), set: v => { rawThreshold.value = v } })
  const tolerance = computed({ get: () => Math.max(0, Math.min(16, Number(rawTolerance.value) || 0)), set: v => { rawTolerance.value = v } })
  return { debug, threshold, tolerance }
}
