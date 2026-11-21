<script setup lang="ts">
const props=withDefaults(defineProps<{modelValue:number;label:string;min:number;max:number;step?:number;unit?:string}>(),{step:1,unit:''})
const emit=defineEmits<{'update:modelValue':[number]}>()
function update(e:Event){const n=(e.target as HTMLInputElement).valueAsNumber;if(Number.isFinite(n))emit('update:modelValue',Math.max(props.min,Math.min(props.max,n)))}
</script>
<template>
  <div class="ui-range">
    <label>{{ label }} <span>{{ modelValue }}{{ unit }}</span><input type="range" :min="min" :max="max" :step="step" :value="modelValue" @input="update" /></label>
    <input class="ui-number" type="number" :aria-label="label+'数值'" :min="min" :max="max" :step="step" :value="modelValue" @change="update" />
  </div>
</template>
<style scoped>
.ui-range{display:flex;gap:12px;align-items:end;margin:14px 0}.ui-range label{flex:1;min-width:0;font-size:13px}.ui-range label span{color:var(--muted);margin-left:8px;font-size:12px}.ui-range input[type=range]{display:block;width:100%;margin-top:8px;accent-color:var(--accent)}.ui-number{width:76px;padding:5px;border:1px solid var(--line);border-radius:6px;background:var(--surface);color:inherit}
</style>
