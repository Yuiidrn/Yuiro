const fs=require('fs'),vm=require('vm'),assert=require('node:assert/strict'),ts=require('../../shell/node_modules/typescript')
const pending=[];let role='hotaru'
const context={exports:{},console,localStorage:{getItem:()=>role},window:{yuiro:{getEngineSecret:async()=> 'fixture'}},
 fetch:()=>new Promise(resolve=>pending.push(resolve)),requestAnimationFrame:()=>1,cancelAnimationFrame(){},
 require:name=>name==='vue'?{ref:value=>({value})}:name.includes('useAudioDevices')?{useAudioDevices:()=>({})}:{inputLevel:()=>0}}
vm.runInNewContext(ts.transpileModule(fs.readFileSync('shell/src/renderer/src/composables/useVoiceInput.ts','utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText,context)
const response=value=>({ok:true,json:async()=>({sections:{vad:{barge_in_enabled:value}}})})
const flush=()=>new Promise(resolve=>setImmediate(resolve))
;(async()=>{
 const v=context.exports.useVoiceInput(),old=v.loadBargeIn(),newer=v.loadBargeIn();await flush()
 pending[1](response(false));await newer;pending[0](response(true));await old
 assert.equal(v.bargeInEnabled.value,false,'旧HTTP响应不得覆盖新回读')
 const switched=v.loadBargeIn();await flush();role='hiyori';pending[2](response(true));await switched
 assert.equal(v.bargeInEnabled.value,false,'其他角色迟到响应不得写入')
 const disposed=v.loadBargeIn();await flush();await v.dispose();pending[3](response(true));await disposed
 assert.equal(v.bargeInEnabled.value,false,'卸载后的回读不得更新镜像')
 console.log('Production speech settings readback: request order, role boundary and disposed response rejection passed.')
})().catch(error=>{console.error(error);process.exitCode=1})
