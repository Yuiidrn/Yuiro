const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict')
const ts=require('../../shell/node_modules/typescript')
const source=fs.readFileSync('shell/src/renderer/src/components/Live2DCanvas.vue','utf8')
const start=source.indexOf('let motionPlaybackRevision = 0'),end=source.indexOf('\n/**',source.indexOf('function playMotion(',start))
assert(start>=0&&end>start)
const production=source.slice(start,end)
function fixture(before=false){
 const pending=[],receipts=[],state={motion:'',motionIndex:null},mm={startMotion:()=>new Promise((resolve,reject)=>pending.push({resolve,reject}))}
 const context={model:{internalModel:{motionManager:mm}},modelRevision:1,motionRequestRevision:1,
  listMotions:()=>[{group:'Motion',count:2}],motionDurationMs:()=>2000,avatarState:{value:state},
  console:{warn(){},log(){}},Math,Number,Promise,exports:{}}
 const code=before?production.replace('||request!==motionRequestRevision||playback!==motionPlaybackRevision',''):production
 vm.runInNewContext(ts.transpileModule(code+'\nexports.play=playMotion',{compilerOptions:{module:ts.ModuleKind.CommonJS}}).outputText,context)
 return {pending,receipts,state,context,play:(index,label)=>context.exports.play('Motion',index,3,ok=>receipts.push([label,ok]))}
}
async function flush(){await Promise.resolve();await Promise.resolve()}
async function run(){
 let f=fixture(true);f.play(0,'old');f.play(0,'new');f.pending[1].resolve(true);await flush();f.pending[0].resolve(false);await flush();assert.equal(f.state.motion,'','旧代码复现：同一资源的旧失败清空新动作')
 f=fixture();f.play(0,'old');f.play(0,'new');f.pending[1].resolve(true);await flush();f.pending[0].resolve(false);await flush();assert.equal(f.state.motion,'Motion');assert.equal(f.state.motionIndex,0);assert.deepEqual(f.receipts,[['new',true]])
 for(const reason of ['cancel','model','newPerformance','reject']){
  f=fixture();f.play(0,'old')
  if(reason==='model')f.context.modelRevision++
  else f.context.motionRequestRevision++
  f.state.motion='Motion';f.state.motionIndex=0
  if(reason==='reject')f.pending[0].reject(new Error('late failed load'));else f.pending[0].resolve(reason==='newPerformance')
  await flush();assert.equal(f.state.motion,'Motion',reason);assert.deepEqual(f.receipts,[],reason)
 }
 f=fixture();f.play(1,'current');f.pending[0].resolve(false);await flush();assert.equal(f.state.motion,'');assert.deepEqual(f.receipts,[['current',false]])
 f=fixture();f.play(1,'current');f.pending[0].reject(new Error('current failed load'));await flush();assert.equal(f.state.motion,'');assert.deepEqual(f.receipts,[['current',false]])
 console.log('Production playMotion: baseline stale clearing reproduced; repeated resource, cancellation, model/performance change, stale rejection and current failures passed.')
}
run().catch(e=>{console.error(e);process.exitCode=1})
