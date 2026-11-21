/** 仅通知同源窗口回读引擎，不在浏览器中保存第二份语音配置。 */
const KEY='yuiro-speech-settings-changed-v1'
export function notifySpeechSettings(characterId:string):void {
  if(!characterId)return
  try{localStorage.setItem(KEY,JSON.stringify({characterId,nonce:crypto.randomUUID()}))}
  catch{console.warn('[voice] 语音设置跨窗口刷新通知失败')}
}
export function watchSpeechSettings(role:()=>string,refresh:()=>void):()=>void {
  const changed=(event:StorageEvent)=>{
    if(event.key!==KEY||!event.newValue)return
    try{const value=JSON.parse(event.newValue);if(value.characterId===role())refresh()}catch{/* 非法通知不改变状态。 */}
  }
  window.addEventListener('storage',changed)
  return ()=>window.removeEventListener('storage',changed)
}
