import { useLocalStorage } from '@vueuse/core'
import type { Live2DManifest } from '@shared'
import { recommendedClicks, validClicks } from '../avatar/clickFeedback'
export function useAvatarClickPref(){
  const role=useLocalStorage('yuiro-active-character','hiyori')
  const pools=useLocalStorage<Record<string,{enabled:boolean;motions:string[]}>>('yuiro-avatar-click-pools-v1',{})
  function key(path:string){try{return `${role.value}:${decodeURI(path)}`}catch{return `${role.value}:${path}`}}
  function read(path:string,manifest:Live2DManifest|null){
    const stored=pools.value?.[key(path)]
    return {enabled:stored?.enabled!==false,motions:validClicks(stored?.motions??recommendedClicks(manifest),manifest)}
  }
  function write(path:string,value:{enabled:boolean;motions:string[]}){
    pools.value={...pools.value,[key(path)]:{enabled:value.enabled,motions:[...new Set(value.motions)].slice(0,128)}}
  }
  return {read,write}
}
