const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict'),ts=require('../../shell/node_modules/typescript')
const presenceModule={exports:{}}
vm.runInNewContext(ts.transpileModule(fs.readFileSync('shell/src/renderer/src/avatar/presence.ts','utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS}}).outputText,presenceModule)
const next=presenceModule.exports.presenceAfter
assert.equal(next('idle','tts:playback_waiting'),'thinking')
assert.equal(next('thinking','tts:playback_start'),'speaking')
for(const event of ['tts:start','tts:synthesize','tts:playback_waiting'])assert.equal(next('speaking',event),'speaking')
assert.equal(next('thinking','tts:playback_empty'),'idle')
assert.equal(next('thinking','tts:end'),'thinking','sending end is not local playback end')
let state='idle';const events=[]
const context={exports:{},localStorage:{getItem:()=> 'hotaru'},window:{},console,
 setTimeout,clearTimeout,requestAnimationFrame:()=>1,cancelAnimationFrame(){},
 require:name=>name==='vue'?{ref:value=>({value})}:name.includes('useAudioDevices')?{useAudioDevices:()=>({}),describeMicError:String}:{inputLevel:()=>0}}
let code=fs.readFileSync('shell/src/renderer/src/composables/useVoiceInput.ts','utf8').replace(/\r\n/g,'\n')
code=code.replace('  return {\n    inputLevel,','  return {\n    receive:handleServerMessage,bind:()=>{voiceSessionId="s"},\n    inputLevel,')
assert(code.includes('receive:handleServerMessage'))
vm.runInNewContext(ts.transpileModule(code,{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText,context)
const voice=context.exports.useVoiceInput((type)=>{events.push(type);state=next(state,type)})
voice.beginReplyPlayback();assert.equal(state,'thinking')
assert.equal(voice.endReplyAudio(),false);assert.equal(state,'idle')
assert.deepEqual(events,['tts:playback_waiting','tts:playback_empty'])
voice.endReplyAudio();assert(!events.includes('tts:playback_end'),'zero audio must not pretend it played')
voice.bind()
function send(type,extra={}){voice.receive({type,session_id:'s',character_id:'hotaru',generation:1,...extra})}
send('llm:start');assert.equal(state,'thinking')
send('tts:start');send('llm:text',{text:'最终文本晚于合成开始'});assert.equal(state,'thinking')
assert.deepEqual(events.slice(-2),['llm:text','tts:playback_waiting'])
send('tts:end');assert.equal(state,'idle');assert(!events.includes('tts:playback_end'))
voice.beginReplyPlayback();send('tts:interrupted');assert.equal(state,'idle')
send('tts:start',{character_id:'hiyori'});assert.equal(state,'idle','wrong role must not re-enter waiting')
console.log('Production presence + voice handlers: text first-audio waiting, late final text, actual speaking preserved, zero audio completion without playback_end, cancel and foreign role rejection passed.')
