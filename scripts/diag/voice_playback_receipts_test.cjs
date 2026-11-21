const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict')
const ts=require('../../shell/node_modules/typescript')
const receipts=[],sources=[];let stops=0,decodeFailure=false
class AudioContext {
  state='running';currentTime=1;destination={}
  async decodeAudioData(){if(decodeFailure)throw Error('bad WAV');return {}}
  createBufferSource(){const s={connect(){},start(){},stop(){stops++},onended:null};sources.push(s);return s}
}
const context={exports:{},AudioContext,WebSocket:{OPEN:1},localStorage:{getItem:()=> 'hotaru'},
  window:{},performance:{now:()=>0},atob:()=> '\0',Uint8Array,setTimeout,clearTimeout,
  requestAnimationFrame:()=>1,cancelAnimationFrame(){},console,
  require:name=>name==='vue'?{ref:value=>({value})}:name.includes('useAudioDevices')?{useAudioDevices:()=>({}),describeMicError:String}:{inputLevel:()=>0}}
let code=fs.readFileSync('shell/src/renderer/src/composables/useVoiceInput.ts','utf8').replace(/\r\n/g,'\n')
// 仅测试注入私有WS/已绑定会话；生产代码不导出测试后门。
code=code.replace('  return {\n    inputLevel,','  return {\n    testReceive:handleServerMessage,testBind:(socket:any)=>{ws=socket;voiceSessionId="s"},\n    inputLevel,')
vm.runInNewContext(ts.transpileModule(code,{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText,context)
const v=context.exports.useVoiceInput(),flush=()=>new Promise(r=>setImmediate(r))
v.testBind({readyState:1,send:s=>receipts.push(JSON.parse(s))})
const frame=(id,extra={})=>({type:'tts:audio',session_id:'s',character_id:'hotaru',generation:3,playback_id:id,wav:'AA==',sample_rate:24000,slice_ms:20,volumes:[.2],...extra})
;(async()=>{
  v.testReceive(frame('a'));v.testReceive(frame('b'));await flush()
  assert.equal(sources.length,1)
  for(const stale of [
    {type:'tts:interrupted',generation:2,session_id:'s',character_id:'hotaru'},
    {type:'tts:interrupted',generation:3,session_id:'s',character_id:'hiyori'},
    {type:'tts:interrupted',generation:3,session_id:'other',character_id:'hotaru'},
    {type:'tts:interrupted'},
    {type:'tts:end',generation:2,session_id:'s',character_id:'hotaru'},
  ])v.testReceive(stale)
  assert.equal(stops,0,'旧/外来/缺身份状态不能停止当前音频')
  v.testReceive({type:'tts:end',session_id:'s',character_id:'hotaru',generation:3})
  assert(!receipts.some(r=>r.type==='audio:playback_finished'),'下发结束不能释放播放占用')
  sources[0].onended();await flush()
  assert.equal(sources.length,2)
  assert(receipts.some(r=>r.playback_id==='a'&&r.type==='audio:playback_finished'))
  v.testReceive(frame('c'));v.testReceive({type:'tts:interrupted',session_id:'s',character_id:'hotaru',generation:3});await flush()
  assert.equal(stops,1)
  for(const id of ['b','c'])assert(receipts.some(r=>r.playback_id===id&&r.type==='audio:playback_finished'))
  const n=sources.length
  v.testReceive(frame('old',{generation:2}));v.testReceive(frame('role',{character_id:'hiyori'}));v.testReceive(frame('session',{session_id:'other'}));await flush()
  assert.equal(sources.length,n)
  decodeFailure=true;v.testReceive(frame('bad'));await flush()
  assert(receipts.some(r=>r.playback_id==='bad'&&r.type==='audio:playback_finished'))
  const state=(type,generation)=>({type,session_id:'s',character_id:'hotaru',generation})
  v.testReceive(state('asr:start',4));assert(v.turnBusy.value)
  v.testReceive(state('asr:dropped',3));assert(v.turnBusy.value,'旧ASR收尾不能清除新回合繁忙状态')
  v.testReceive(state('asr:dropped',4));assert(!v.turnBusy.value)
  for(const r of receipts)assert.deepEqual(Object.keys(r).sort(),['type','session_id','character_id','generation','playback_id'].sort(),'回执不回传音频')
  console.log('Production voice queue: sent-all vs played-all, natural end, active/queued cancellation, stale identities, decode failure, minimal receipts passed.')
})().catch(e=>{console.error(e);process.exitCode=1})
