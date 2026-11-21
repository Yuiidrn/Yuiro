const fs=require('fs'),vm=require('vm'),assert=require('node:assert/strict'),ts=require('../../shell/node_modules/typescript')
const src=fs.readFileSync('shell/src/renderer/src/App.vue','utf8').split('<script setup lang="ts">')[1].split('</script>')[0]
const file=ts.createSourceFile('App.ts',src,ts.ScriptTarget.ES2022,true)
const names=new Set(['toggleBargeIn','toggleReplyTts','loadReplyTts'])
const code=file.statements.filter(n=>ts.isFunctionDeclaration(n)&&names.has(n.name?.text)).map(n=>n.getText(file)).join('\n')
const pending=[],writes=[],speech=[],signals=[];let keyLoader=async()=> 'fixture'
const context={activeCharacter:{value:'hotaru'},characterRevision:{value:12},bargeInBusy:{value:false},bargeInEnabled:{value:false},replyTtsBusy:{value:false},replyTtsEnabled:{value:true},
 window:{yuiro:{getEngineSecret:()=>keyLoader()}},ENGINE_API:'http://fixture',
 fetch:(url,options)=>{writes.push(options);return new Promise(resolve=>pending.push(resolve))},
 showSpeech:x=>speech.push(x),log(){},notifySpeechSettings:x=>signals.push(x),loadBargeIn(){},loadReplyTts(){}}
vm.runInNewContext(ts.transpileModule(code,{compilerOptions:{target:ts.ScriptTarget.ES2022}}).outputText,context)
context.replySettingsRead=0;context.speechSettingsAlive=true
context.localStorage={getItem:()=>context.activeCharacter.value}
const flush=()=>new Promise(resolve=>setImmediate(resolve))
;(async()=>{
 const stale=context.toggleBargeIn();await flush();context.activeCharacter.value='hiyori';context.characterRevision.value=13
 pending.shift()({ok:true});await stale
 assert.equal(context.bargeInEnabled.value,false);assert.equal(speech.length,0);assert.equal(signals.length,0)
 const current=context.toggleBargeIn();await flush();pending.shift()({ok:true});await current
 assert.equal(context.bargeInEnabled.value,true);assert.equal(signals[0],'hiyori')
 const body=JSON.parse(writes.at(-1).body);assert.equal(body.character_id,'hiyori');assert.equal(body.character_revision,13)
 assert.equal(writes.at(-1).headers['x-yuiro-character'],'hiyori')
 let release;keyLoader=()=>new Promise(resolve=>release=resolve)
 const count=writes.length,late=context.toggleReplyTts();await flush();context.activeCharacter.value='hotaru';context.characterRevision.value=14
 release('fixture');await late;assert.equal(writes.length,count,'旧角色密钥返回后不得发配置写入')
 keyLoader=async()=> 'fixture'
 const tts=context.toggleReplyTts();await flush();pending.shift()({ok:true});await tts
 assert.equal(context.replyTtsEnabled.value,false);assert.equal(signals.at(-1),'hotaru')
 const response=value=>({ok:true,json:async()=>({sections:{tts:{reply_tts_enabled:value}}})})
 const oldRead=context.loadReplyTts(),newRead=context.loadReplyTts();await flush()
 const oldResolve=pending.shift(),newResolve=pending.shift()
 newResolve(response(true));await newRead;oldResolve(response(false));await oldRead
 assert.equal(context.replyTtsEnabled.value,true,'旧TTS回读不得覆盖最新值')
 const roleRead=context.loadReplyTts();await flush();context.activeCharacter.value='hiyori'
 pending.shift()(response(false));await roleRead;assert.equal(context.replyTtsEnabled.value,true)
 const disposedRead=context.loadReplyTts();await flush();context.speechSettingsAlive=false
 pending.shift()(response(false));await disposedRead;assert.equal(context.replyTtsEnabled.value,true)
 console.log('Production speech quick toggles: role/revision snapshot, late lookup/response rejection and successful notification passed.')
})().catch(error=>{console.error(error);process.exitCode=1})
