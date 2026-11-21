const fs=require('fs'),vm=require('vm'),assert=require('node:assert/strict'),ts=require('../../shell/node_modules/typescript')
const sources=[],receipts=[],rafs=[],timers=new Map();let timerId=0,stops=0,decodeGate=null
class AudioContext {
  state='running';currentTime=0;destination={}
  constructor(){context.audio=this}
  async decodeAudioData(){if(decodeGate)await decodeGate;return {duration:.48}}
  createBufferSource(){const s={connect(){},start(t){this.when=t},stop(){stops++},onended:null};sources.push(s);return s}
}
const context={exports:{},AudioContext,WebSocket:{OPEN:1},localStorage:{getItem:()=> 'hotaru'},window:{},
  performance:{now:()=>0},atob:()=> '\0',Uint8Array,console,
  setTimeout:cb=>{timers.set(++timerId,cb);return timerId},clearTimeout:id=>timers.delete(id),
  requestAnimationFrame:cb=>{rafs.push(cb);return rafs.length},cancelAnimationFrame(){},
  require:n=>n==='vue'?{ref:value=>({value})}:n.includes('useAudioDevices')?{useAudioDevices:()=>({}),describeMicError:String}:{inputLevel:()=>0}}
let code=fs.readFileSync('shell/src/renderer/src/composables/useVoiceInput.ts','utf8').replace(/\r\n/g,'\n')
code=code.replace('  return {\n    inputLevel,','  return {\n    testReceive:handleServerMessage,testBind:(socket:any)=>{ws=socket;voiceSessionId="s"},\n    inputLevel,')
vm.runInNewContext(ts.transpileModule(code,{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText,context)
const events=[],v=context.exports.useVoiceInput(t=>events.push(t))
v.testBind({readyState:1,send:s=>receipts.push(JSON.parse(s))})
const send=id=>v.testReceive({type:'tts:audio',session_id:'s',character_id:'hotaru',generation:3,playback_id:id,streaming:true,wav:'AA==',volumes:Array(24).fill(.2),sample_rate:24000,slice_ms:20})
const flush=async()=>{for(let i=0;i<8;i++)await new Promise(r=>setImmediate(r))}
const tick=()=>{const callbacks=[...timers.values()];timers.clear();callbacks.forEach(cb=>cb())}
;(async()=>{
  send('a');send('b');send('c');await flush()
  assert.equal(sources.length,3,'必须在上一段结束前提前解码排期')
  assert.equal(sources[1].when,sources[0].when+.48)
  assert.equal(sources[2].when,sources[1].when+.48)
  assert(!receipts.some(r=>r.type==='audio:playback_started'),'未来排期不得提前上报出声')
  context.audio.currentTime=.1;tick();rafs.at(-1)()
  assert.equal(receipts.filter(r=>r.type==='audio:playback_started').length,1)
  assert(Math.abs(v.mouthOpen.value-.6)<1e-6)
  v.testReceive({type:'tts:end',session_id:'s',character_id:'hotaru',generation:3})
  sources[0].onended();assert(!events.includes('tts:playback_end'))
  context.audio.currentTime=.6;tick();rafs.at(-1)()
  assert(Math.abs(v.mouthOpen.value-.6)<1e-6,'下一片口型使用自己的音频起点')
  sources[1].onended();context.audio.currentTime=1.5;sources[2].onended()
  assert(events.includes('tts:playback_end'));assert.equal(v.mouthOpen.value,0)
  v.beginReplyPlayback()
  send('d');send('e');await flush();v.stopPlayback()
  assert.equal(stops,2,'当前与尚未播放的已排期节点必须同时取消')
  assert.equal(v.mouthOpen.value,0);assert.equal(timers.size,0)
  const n=sources.length;let release
  decodeGate=new Promise(r=>release=r);send('late');await flush();v.stopPlayback();release();await flush()
  assert.equal(sources.length,n,'打断后完成的解码不能再排期')
  assert(receipts.some(r=>r.playback_id==='late'&&r.type==='audio:playback_finished'))
  decodeGate=null;v.beginReplyPlayback();send('gap-first');await flush()
  const first=sources.at(-1);context.audio.currentTime=first.when+.48;first.onended()
  context.audio.currentTime+=.8;send('gap-second');await flush()
  assert.equal(sources.at(-1),first,'断供后单块不能立即反复续读')
  send('gap-third');await flush()
  assert(events.includes('tts:playback_underrun'),'同回合供给中断必须可观测')
  v.stopPlayback()
  v.beginReplyPlayback();send('tail-first');await flush()
  const tailFirst=sources.at(-1);context.audio.currentTime=tailFirst.when+.48;tailFirst.onended()
  send('tail-last');await flush();assert.equal(sources.at(-1),tailFirst)
  v.endReplyAudio();await flush();assert.notEqual(sources.at(-1),tailFirst,'不足缓冲目标的尾块收到EOF必须立即释放')
  v.stopPlayback();v.beginReplyPlayback();send('cancel-first');await flush()
  const cancelFirst=sources.at(-1);context.audio.currentTime=cancelFirst.when+.48;cancelFirst.onended()
  send('cancel-waiting');await flush();v.stopPlayback();await flush()
  assert.equal(sources.at(-1),cancelFirst,'重新缓冲期间取消不能迟到续播')
  assert.equal(timers.size,0,'重新缓冲取消必须清理定时器')
  v.beginReplyPlayback();send('timeout-first');await flush()
  const timeoutFirst=sources.at(-1);context.audio.currentTime=timeoutFirst.when+.48;timeoutFirst.onended()
  send('timeout-waiting');await flush();tick();await flush()
  assert.notEqual(sources.at(-1),timeoutFirst,'超时必须释放不足目标的块，不能无限等待')
  v.stopPlayback();v.beginReplyPlayback()
  v.enqueueReplyAudio({wav:'AA==',volumes:Array(24).fill(.2),streaming:true,stream_id:'phrase-one'})
  await flush();const phraseFirst=sources.at(-1)
  context.audio.currentTime=phraseFirst.when+.48;phraseFirst.onended()
  v.enqueueReplyAudio({wav:'AA==',volumes:Array(24).fill(.2),streaming:true,stream_id:'phrase-two'})
  await flush();assert.notEqual(sources.at(-1),phraseFirst,'新句首块不应被上一句的欠载额外阻塞')
  v.stopPlayback()
  console.log('Production streaming queue: contiguous audio-clock scheduling, deferred receipts, per-chunk lips, all-node cancellation and late decode rejection passed.')
})().catch(e=>{console.error(e);process.exitCode=1})
