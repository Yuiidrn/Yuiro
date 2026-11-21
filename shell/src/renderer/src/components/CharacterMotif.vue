<script setup lang="ts">
defineProps<{skin:'cream'|'lily'}>()
</script>
<template>
 <svg class="character-motif" viewBox="0 0 100 64" fill="none" aria-hidden="true" focusable="false">
  <g v-if="skin==='lily'" stroke="currentColor" stroke-width="1.15" stroke-linecap="round" stroke-linejoin="round">
   <path d="M20 57 Q42 43 49 25 M37 44 Q58 43 69 28 M32 46 Q23 36 17 38 Q21 48 32 46" />
   <path d="M49 27 Q31 20 31 7 Q44 10 49 27 Q44 9 52 3 Q59 14 49 27 Q64 11 73 16 Q65 28 49 27Z" fill="var(--motif-fill,var(--card,#fff))" />
   <path d="M49 27 L48 17 M49 27 L56 19" />
   <g transform="translate(72 33)"><path d="M0 0 C-14-2-12-13-5-8 C-5-20 7-17 5-7 C17-13 20-2 9 1 C19 10 9 17 3 7 C-1 19-13 11-5 4 C-17 7-18-6-7-3Z" fill="var(--motif-fill,var(--card,#fff))"/><circle r="2" fill="currentColor" stroke="none" /></g>
  </g>
  <g v-else stroke="currentColor" stroke-width="1.2" stroke-linejoin="round"><path d="M52 9 Q53 29 65 31 Q53 33 52 51 Q50 33 38 31 Q50 29 52 9Z"/><path d="M77 14L79 21L86 23L79 25L77 32L75 25L68 23L75 21Z"/><circle cx="27" cy="42" r="2"/><path d="M30 16L32 20M34 16L30 20"/></g>
 </svg>
</template>
<style scoped>.character-motif{width:88px;height:56px;color:var(--character-flower,#b3a48b);pointer-events:none;flex:none;opacity:.65}</style>
