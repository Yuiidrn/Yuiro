<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { Icon } from '@iconify/vue'
import { api } from '../api'
import type { ProviderTestResult } from '@shared'
import { useConfigStore } from '../stores/config'

/**
 * 组件自检卡：点一下就把某条链路真跑一遍，把耗时/后端/样本摊开给用户看。
 * 只用于「后端确实实现了测试」的组件 —— 空壳自检不放上来，免得让人以为功能坏了。
 */
const props = defineProps<{ provider: string; title: string; description: string }>()

const testing = ref(false)
const result = ref<ProviderTestResult | null>(null)
const error = ref('')
const store = useConfigStore()
const player = ref<HTMLAudioElement | null>(null)
const audioSrc = ref('')
let epoch = 0
function reset(): void {
  epoch++
  player.value?.pause()
  if (audioSrc.value) URL.revokeObjectURL(audioSrc.value)
  audioSrc.value = ''
  result.value = null
  error.value = ''
  testing.value = false
}
watch(() => [store.character?.active_id, store.character?.revision, store.switching], reset, { flush: 'sync' })
onBeforeUnmount(reset)

const STATUS_TEXT: Record<string, string> = { ok: '通过', warn: '警告', error: '失败' }

/**
 * S52：语音合成试听可选语种 —— 参考音频是单语的，跨语言效果差异大，
 * 得能让用户**当场对比**（不选则用「语言」设置里的朗读语言）。
 */
const isTts = computed(() => props.provider === 'tts')
const lang = ref('auto')
const LANG_OPTIONS = [
  { value: 'auto', label: '跟随设置' },
  { value: 'zh', label: '中文' },
  { value: 'en', label: '英文' },
  { value: 'ja', label: '日文' },
]

async function run(): Promise<void> {
  reset()
  const current = epoch
  testing.value = true
  result.value = null
  error.value = ''
  try {
    const response = await api.testProvider(
      props.provider,
      isTts.value ? { lang: lang.value } : undefined,
    )
    if (current === epoch) {
      result.value = response
      if (typeof response.audio_base64 === 'string') {
        const bytes = Uint8Array.from(atob(response.audio_base64), c => c.charCodeAt(0))
        audioSrc.value = URL.createObjectURL(new Blob([bytes], { type: 'audio/wav' }))
      }
    }
  } catch (e) {
    if (current === epoch) error.value = e instanceof Error ? e.message : String(e)
  } finally {
    if (current === epoch) testing.value = false
  }
}
</script>

<template>
  <div class="self-test">
    <div class="st-head">
      <div class="st-text">
        <h3 class="st-title">{{ title }}</h3>
        <p class="st-desc">{{ description }}</p>
      </div>
      <div class="st-actions">
        <select v-if="isTts" v-model="lang" class="st-lang" :disabled="testing">
          <option v-for="o in LANG_OPTIONS" :key="o.value" :value="o.value">{{ o.label }}</option>
        </select>
        <button class="st-run" :disabled="testing || store.switching" @click="run">
          <Icon :icon="testing ? 'solar:refresh-bold' : 'solar:play-bold'" width="13" />
          {{ testing ? '测试中' : '测试' }}
        </button>
      </div>
    </div>

    <div v-if="result" class="st-result" :class="result.status">
      <div class="st-result-head">
        <span class="pill" :class="`pill-${result.status === 'ok' ? 'ok' : result.status === 'warn' ? 'warn' : 'err'}`">
          {{ STATUS_TEXT[result.status] ?? result.status }}
        </span>
        <span v-if="typeof result.latency_ms === 'number'" class="st-meta">{{ result.latency_ms }} ms</span>
        <span v-if="result.backend" class="st-meta">{{ result.backend }}</span>
      </div>
      <p v-if="result.detail" class="st-detail">{{ result.detail }}</p>
      <p v-if="result.sample" class="st-sample">{{ result.sample }}</p>
      <!-- S52：试听回传实际用的语种与文本，避免"设了日文其实念的是中文"这种误判 -->
      <p v-if="isTts && result.lang" class="st-sample">
        语种 {{ result.lang }}｜试听文本：{{ result.text ?? '' }}
      </p>
      <!-- S52：参考音频的语种（可能不是中文）—— 朗读语言建议就设成它 -->
      <p v-if="isTts && result.reference_lang && result.reference_lang !== 'unknown'" class="st-sample">
        参考音频语种：{{ result.reference_lang }}｜朗读语言建议设为
        {{ result.reference_lang }}（与参考一致时克隆最自然）
      </p>
    </div>

    <p v-if="error" class="st-error">{{ error }}</p>
    <audio v-if="isTts && audioSrc" ref="player" :src="audioSrc" controls preload="metadata" />
  </div>
</template>

<style scoped>
.self-test {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 16px 18px;
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  background: var(--card);
  box-shadow: var(--shadow-soft);
  transition: box-shadow var(--dur-fast) ease;
}
.self-test:hover { box-shadow: var(--shadow-lift); }

.st-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 14px; }
.st-text { min-width: 0; }
.st-title { margin: 0; font-size: 14px; font-weight: 600; }
.st-desc { margin: 4px 0 0; font-size: 12px; color: var(--muted); line-height: 1.5; }

.st-actions { display: flex; align-items: center; gap: 8px; flex-shrink: 0; }

/* S52：试听语种选择（仅语音合成卡显示） */
.st-lang {
  padding: 5px 8px; border-radius: var(--radius-sm);
  border: 1px solid var(--border); background: var(--card-head); color: var(--text);
  font-size: 12px; font-family: inherit; cursor: pointer;
}
.st-lang:disabled { opacity: 0.5; cursor: default; }

.st-run {
  display: inline-flex; align-items: center; gap: 5px; flex-shrink: 0;
  padding: 6px 13px; border-radius: 999px;
  border: 1px solid var(--accent); background: var(--accent); color: #fff;
  font-size: 12px; font-family: inherit; font-weight: 600; cursor: pointer;
  transition: opacity var(--dur-fast) ease;
}
.st-run:hover:not(:disabled) { opacity: 0.88; }
.st-run:disabled { opacity: 0.5; cursor: default; }

/* 结果块：左侧色条 + 极淡底色，一眼区分通过/警告/失败 */
.st-result {
  padding: 10px 12px;
  border-radius: var(--radius-sm);
  background: var(--card-head);
  border-left: 3px solid var(--muted);
}
.st-result.ok { border-left-color: var(--ok); }
.st-result.warn { border-left-color: var(--warn); }
.st-result.error { border-left-color: var(--err); }

.st-result-head { display: flex; align-items: center; gap: 9px; flex-wrap: wrap; }
.st-meta { font-size: 11.5px; color: var(--muted); font-family: ui-monospace, monospace; }
.st-detail { margin: 7px 0 0; font-size: 12px; line-height: 1.55; }
.st-sample { margin: 6px 0 0; font-size: 12px; color: var(--text-soft); line-height: 1.55; }
.st-error { margin: 0; font-size: 12px; color: var(--err); }
</style>
