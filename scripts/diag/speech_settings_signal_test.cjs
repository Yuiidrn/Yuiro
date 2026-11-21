const fs=require('fs'),vm=require('vm'),assert=require('node:assert/strict'),ts=require('../../shell/node_modules/typescript')
const listeners=new Set(),writes=[];let nonce=0,refreshes=0
const storage={getItem:()=> 'hotaru',setItem:(k,v)=>writes.push([k,v])}
const signal={exports:{},console,localStorage:storage,crypto:{randomUUID:()=>String(++nonce)},window:{addEventListener:(_,fn)=>listeners.add(fn),removeEventListener:(_,fn)=>listeners.delete(fn)}}
vm.runInNewContext(ts.transpileModule(fs.readFileSync('shell/src/renderer/src/utils/speechSettingsSignal.ts','utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText,signal)
const off=signal.exports.watchSpeechSettings(()=> 'hotaru',()=>refreshes++)
signal.exports.notifySpeechSettings('hotaru');signal.exports.notifySpeechSettings('hotaru')
assert.notEqual(writes[0][1],writes[1][1])
assert.deepEqual(Object.keys(JSON.parse(writes[0][1])).sort(),['characterId','nonce'])
const dispatch=(value,key=writes[0][0])=>listeners.forEach(fn=>fn({key,newValue:value}))
dispatch('bad');dispatch(JSON.stringify({characterId:'hiyori'}));assert.equal(refreshes,0)
dispatch(writes[0][1]);assert.equal(refreshes,1);off();dispatch(writes[1][1]);assert.equal(refreshes,1)
let success=true
const apiContext={exports:{},localStorage:storage,URLSearchParams,console,window:{yuiro:{getEngineSecret:async()=> 'fixture'}},
 fetch:async()=>({ok:success,status:409,statusText:'Conflict',json:async()=>success?{character:{active_id:'hotaru'}}:{detail:'fixture'}}),
 require:name=>name==='@shared'?{ENGINE_DEBUG_BASE:'http://fixture'}:signal.exports}
vm.runInNewContext(ts.transpileModule(fs.readFileSync('shell/src/renderer/src/dev/api.ts','utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText,apiContext)
;(async()=>{
 const api=apiContext.exports.api,before=writes.length
 await api.putConfig({persona:{name:'fixture'}},'hotaru',1);assert.equal(writes.length,before)
 await api.putConfig({vad:{barge_in_enabled:true}},'hotaru',1);assert.equal(writes.length,before+1)
 await api.putConfig({tts:{reply_tts_enabled:false}},'hotaru',1);assert.equal(writes.length,before+2)
 await api.reloadConfig();assert.equal(writes.length,before+3)
 success=false;await assert.rejects(api.putConfig({vad:{}},'hotaru',1));assert.equal(writes.length,before+3)
 console.log('Speech settings: role filtering, malformed signal, unsubscribe, successful speech writes/reload only, no config/secret payload passed.')
})().catch(error=>{console.error(error);process.exitCode=1})
