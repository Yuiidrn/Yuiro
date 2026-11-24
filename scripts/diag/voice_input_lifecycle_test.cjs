const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict')
const ts=require('../../shell/node_modules/typescript')
const admission={}
vm.runInNewContext(ts.transpileModule(fs.readFileSync('shell/src/shared/playback-admission.ts','utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText,{exports:admission})
const events=[],sources=[],contexts=[],rafCallbacks=[];let stopped=0,cancelledRaf=0,closed=0,decodeGate=null
class AudioContext {
 state='running';destination={};currentTime=0
 constructor(){contexts.push(this)}
 async close(){closed++;this.state='closed'}
 async decodeAudioData(){if(decodeGate)await decodeGate;return {}}
 createBufferSource(){const source={connect(){},start(){},stop(){stopped++},onended:null};sources.push(source);return source}
}
const context={exports:{},window:{yuiro:{getEngineSecret:async()=> 'fixture'}},localStorage:{getItem:()=> 'hotaru'},fetch:async()=>({ok:true,json:async()=>({sections:{vad:{barge_in_enabled:true}}})}),AudioContext,performance:{now:()=>0},atob:()=>String.fromCharCode(0),Uint8Array,setTimeout,clearTimeout,
 requestAnimationFrame:cb=>{rafCallbacks.push(cb);return rafCallbacks.length},cancelAnimationFrame:()=>cancelledRaf++,console,
 require:name=>name==='vue'?{ref:value=>({value})}:name.includes('playback-admission')?admission:name.includes('useAudioDevices')?{useAudioDevices:()=>({}),describeMicError:String}:{inputLevel:()=>0}}
vm.runInNewContext(ts.transpileModule(fs.readFileSync('shell/src/renderer/src/composables/useVoiceInput.ts','utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText,context)
const voice=context.exports.useVoiceInput(type=>events.push(type)),flush=()=>new Promise(resolve=>setImmediate(resolve))
;(async()=>{
 await voice.loadBargeIn();assert.equal(voice.bargeInEnabled.value,true)
 voice.beginReplyPlayback();voice.enqueueReplyAudio({wav:'AA==',sample_rate:24000,slice_ms:20,volumes:[.2]});await flush()
 assert(events.includes('tts:playback_start'));assert.equal(voice.mouthOpen.value,0,'stalled audio clock must not open mouth')
 rafCallbacks.at(-1)();assert.equal(voice.mouthOpen.value,0)
 contexts[0].currentTime=.01;rafCallbacks.at(-1)();assert(Math.abs(voice.mouthOpen.value-.6)<1e-9)
 const before=cancelledRaf;await voice.stop()
 assert.equal(stopped,0);assert.equal(cancelledRaf,before);assert(Math.abs(voice.mouthOpen.value-.6)<1e-9)
 assert.equal(voice.inputLevel.value,0);assert(events.includes('mic:stop'))
 voice.endReplyAudio();sources[0].onended();await flush()
 assert.equal(voice.mouthOpen.value,0);assert(events.includes('tts:playback_end'))
 assert.equal(closed,0,'停止输入不应关闭输出音频图')
 voice.beginReplyPlayback();voice.enqueueReplyAudio({wav:'AA==',volumes:[.2]});await flush();await voice.dispose();await flush()
 assert.equal(stopped,1);assert.equal(voice.mouthOpen.value,0);assert(events.includes('tts:playback_cancelled'))
 await voice.dispose();assert.equal(closed,1,'完整释放幂等且关闭一次AudioContext')
 const count=sources.length;voice.enqueueReplyAudio({wav:'AA==',volumes:[.2]});await flush()
 assert.equal(sources.length,count,'卸载后的迟到帧不能创建新音频图或播放')
 await assert.rejects(voice.start(),/已释放/)
 let release;decodeGate=new Promise(resolve=>release=resolve)
 const lateEvents=[],second=context.exports.useVoiceInput(type=>lateEvents.push(type))
 second.enqueueReplyAudio({wav:'AA==',streaming:true,volumes:[.2]});await flush()
 await second.dispose();release();await flush()
 assert.equal(closed,2);assert.equal(contexts.length,2)
 assert.equal(sources.length,count,'卸载后完成的解码不能创建source')
 assert(!lateEvents.includes('tts:playback_start'))
 console.log('Audio clock: stalled clock keeps mouth closed; advancing audio clock drives first volume slice. Passed.')
 console.log('Actual voice composable: mic stop preserves active output/lips; natural end resets lips; dispose cancels output. Passed.')
})().catch(e=>{console.error(e);process.exitCode=1})
