import { computed, effectScope, watch, watchEffect } from 'vue'
import { useLocalStorage } from '@vueuse/core'
import { UI_APPEARANCE_DEFAULTS,normalizeUiAppearance,panelAppearance,resolveSkin,type PanelKind } from '../../../shared/uiAppearance'

import '../styles/characterSkins.css'

function create(){
  const settings=useLocalStorage('yuiro-detached-ui-v1',structuredClone(UI_APPEARANCE_DEFAULTS))
  const petTheme=useLocalStorage('yuiro-theme','light',{writeDefaults:false})
  watch(settings,value=>{const clean=normalizeUiAppearance(value);if(JSON.stringify(clean)!==JSON.stringify(value))settings.value=clean},{deep:true,immediate:true,flush:'sync'})
  const role=useLocalStorage('yuiro-active-character','hiyori',{writeDefaults:false})
  const resolvedSkin=computed(()=>resolveSkin(settings.value.skin,role.value))
  watchEffect(()=>{document.documentElement.dataset.skin=resolvedSkin.value})
  const style=(kind:PanelKind)=>panelAppearance(settings.value,kind,petTheme.value,resolvedSkin.value)
  const resolvedTheme=computed(()=>settings.value.theme==='auto'?petTheme.value:settings.value.theme)
  function reset(group:'general'|'speech'|'results'|'source'){
    if(group==='general')settings.value={...settings.value,skin:'auto',theme:'light',gap:12,speechSide:'right'}
    else settings.value={...settings.value,[group]:structuredClone(UI_APPEARANCE_DEFAULTS[group])}
  }
  const setCharacter=(id:string)=>{if(id)role.value=id}
  return {settings,style,reset,setCharacter,resolvedTheme,resolvedSkin,petTheme}
}
const scope=effectScope(true)
// 模块加载时初始化，避开组件 mounted 回调：否则 VueUse storage 监听会随设置页卸载。
const cached=scope.run(create)!
export function useUiAppearance(){return cached}
if(import.meta.hot)import.meta.hot.dispose(()=>scope.stop())
