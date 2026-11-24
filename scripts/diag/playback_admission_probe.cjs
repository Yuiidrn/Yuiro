// 运行真实useVoiceInput函数，受控音频设备验证停播后的迟到入队与解码。
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {createRequire} = require('node:module');
const root = path.resolve(__dirname, '../..');
const ts = createRequire(path.join(root, 'shell/package.json'))('typescript');
function compile(file) {
  return ts.transpileModule(fs.readFileSync(path.join(root, file), 'utf8'), {
    compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS}
  }).outputText;
}
const shared = {};
vm.runInNewContext(compile('shell/src/shared/playback-admission.ts'), {exports:shared});
let starts = 0, hold = false, decode, closeGate;
const contexts=[];
class Context {
  constructor(){contexts.push(this);}
  state = 'running';currentTime = 0;destination = {};
  async resume() {}
  async close() { this.state='closed'; if(closeGate)await closeGate; }
  decodeAudioData() {
    return hold ? new Promise(resolve=>{decode=resolve;}) : Promise.resolve({duration:.1});
  }
  createBufferSource() {
    return {connect(){},disconnect(){},start(){starts++;},stop(){this.onended?.();},onended:null};
  }
}
const exportsObj = {};
vm.runInNewContext(compile('shell/src/renderer/src/composables/useVoiceInput.ts'), {
  exports:exportsObj,
  require(name) {
    if(name==='vue')return {ref:value=>({value})};
    if(name.includes('playback-admission'))return shared;
    if(name.includes('useAudioDevices'))return {useAudioDevices:()=>({openStream:async()=>{}})};
    if(name.includes('inputLevel'))return {inputLevel:()=>0};
    throw Error(name);
  },
  AudioContext:Context,window:{},performance:{now:()=>0},
  atob:s=>Buffer.from(s,'base64').toString('binary'),
  requestAnimationFrame:()=>1,cancelAnimationFrame:()=>{},
  setTimeout,clearTimeout,WebSocket:{OPEN:1}
});
const flush=async()=>{for(let i=0;i<20;i++)await Promise.resolve();};
async function main() {
  const appSource=fs.readFileSync(path.join(root,'shell/src/renderer/src/App.vue'),'utf8').split('</script>')[0].replace(/^<script[^>]*>/,'');
  const appAst=ts.createSourceFile('App.ts',appSource,ts.ScriptTarget.Latest,true);
  const sender=appAst.statements.find(n=>ts.isFunctionDeclaration(n)&&n.name?.text==='sendText');
  let notice='';const scope={controlReady:false,showSpeech:message=>{notice=message;}};
  vm.runInNewContext(ts.transpileModule(sender.getText(appAst),{compilerOptions:{target:ts.ScriptTarget.ES2022}}).outputText,scope);
  scope.sendText('你好');assert.ok(notice.includes('就绪'),'权威会话未就绪时不能发送');
  assert.equal(shared.acceptsReplyRequest({reply_request_id:'old'},''),false);
  assert.equal(shared.acceptsReplyRequest({reply_request_id:'old'},'new'),false);
  assert.equal(shared.acceptsReplyRequest({reply_request_id:'new'},'new'),true);
  assert.equal(shared.acceptsReplyRequest({},''),true);
  const pipe=exportsObj.useVoiceInput();
  const frame=generation=>({session_id:'s',generation,wav:'YQ==',volumes:[],sample_rate:24000});
  pipe.enqueueReplyAudio(frame(1));await flush();assert.equal(starts,1);
  pipe.stopPlayback();await flush();
  pipe.enqueueReplyAudio(frame(1));await flush();assert.equal(starts,1,'停播后旧网络帧不能重新入队');
  pipe.enqueueReplyAudio(frame(2));await flush();assert.equal(starts,2,'后继代际仍须能播放');
  pipe.stopPlayback();await flush();
  hold=true;pipe.enqueueReplyAudio(frame(3));await flush();assert.ok(decode);
  pipe.stopPlayback();decode({duration:.1});await flush();
  pipe.enqueueReplyAudio(frame(3));await flush();assert.equal(starts,2,'旧解码及后续旧帧均不能启动');
  hold=false;pipe.enqueueReplyAudio(frame(4));await flush();assert.equal(starts,3);
  const priorContext=contexts.at(-1);
  pipe.resetPlaybackSession();await flush();
  assert.equal(priorContext.state,'closed','闭麦权威会话交接须关闭旧音频图');
  pipe.enqueueReplyAudio(frame(0));await flush();assert.equal(starts,4,'权威会话重连后低generation须可播放');
  await pipe.dispose();
  const budgetEvents=[];
  const bounded=exportsObj.useVoiceInput((type,payload)=>budgetEvents.push({type,...payload}));
  const streamed={...frame(1),streaming:true,stream_id:'budget',volumes:[.1]};
  for(let i=0;i<200;i++)bounded.enqueueReplyAudio(streamed);
  for(let i=0;i<20;i++)await flush();
  const beforeStop=bounded.playbackBudgetState();
  assert.ok(beforeStop.scheduled<=22,'两秒之后必须等待音频时钟，不能无限提前解码');
  assert.ok(beforeStop.queued_bytes>0&&beforeStop.decode_waiters===1);
  bounded.stopPlayback();await flush();
  assert.equal(bounded.playbackBudgetState().queued_bytes,0);
  assert.equal(bounded.playbackBudgetState().decode_waiters,0);
  const beforeOverflow=starts;
  bounded.enqueueReplyAudio({...frame(2),wav:'Y'.repeat(9*1024*1024)});
  await flush();assert.equal(starts,beforeOverflow);
  assert.ok(budgetEvents.some(e=>e.reason==='audio-buffer-budget'));
  assert.equal(bounded.playbackBudgetState().queued_bytes,0);
  await bounded.dispose();
  const resetting=exportsObj.useVoiceInput();
  resetting.enqueueReplyAudio(frame(1));await flush();
  let releaseClose;closeGate=new Promise(resolve=>{releaseClose=resolve;});
  resetting.resetPlaybackSession();const beforeReset=contexts.length;
  resetting.enqueueReplyAudio(frame(0));await flush();
  assert.equal(contexts.length,beforeReset,'旧图关闭完成前不得重建输出');
  const disposed=resetting.dispose();releaseClose();await disposed;await flush();closeGate=null;
  assert.equal(contexts.length,beforeReset,'等待关闭期间dispose不能迟到重建');
  const result={kind:'actual_useVoiceInput_with_controlled_AudioContext',passed:true,
    assertions:['late-network-frame-rejected','successor-generation-plays',
      'late-decode-rejected','same-generation-after-stop-rejected',
      'cancel-before-first-frame-request-gate','legacy-untagged-compatible',
      'authoritative-session-reset-allows-lower-generation','send-before-session-ready-rejected',
      'bounded-decode-ahead','stop-wakes-decode-budget','audio-buffer-overflow-explicit',
      'authoritative-session-closes-old-output-context','dispose']};
  fs.writeFileSync(path.join(root,'docs/plan/playback-admission-probe.json'),JSON.stringify(result,null,2));
  console.log(result);
}
main().catch(e=>{console.error(e);process.exitCode=1;});
