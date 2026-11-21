const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict')
const ts=require('../../shell/node_modules/typescript'),{EventEmitter}=require('node:events')
const sdk=fs.readFileSync('shell/node_modules/pixi-live2d-display/dist/cubism4.es.js','utf8')
const body=sdk.slice(sdk.indexOf('class ExpressionManager extends'),sdk.indexOf('const EPSILON =',sdk.indexOf('class ExpressionManager extends')))
assert(body.includes('reserveExpressionIndex'))
const ctx={exports:{},utils:{EventEmitter},__publicField:(o,k,v)=>o[k]=v,
 __async:(self,args,fn)=>new Promise((resolve,reject)=>{const gen=fn.apply(self,args||[]);function step(method,value){let r;try{r=gen[method](value)}catch(e){reject(e);return}if(r.done)resolve(r.value);else Promise.resolve(r.value).then(v=>step('next',v),e=>step('throw',e))}step('next')})}
vm.runInNewContext(body+';exports.Manager=ExpressionManager',ctx)
vm.runInNewContext(ts.transpileModule(fs.readFileSync('shell/src/renderer/src/avatar/expressionRequests.ts','utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS}}).outputText,ctx)
function fixture(){
 const m=new ctx.exports.Manager({name:'fixture'}),base={},a={},b={};let release
 m.defaultExpression=base;m.currentExpression=base;m.expressions=[a,b];m.definitions=[{},{}]
 m._setExpression=x=>{m.rendered=x};m.loadExpression=i=>new Promise(r=>{release=()=>r(m.expressions[i])})
 return {m,base,a,b,get finish(){return release}}
}
async function run(){
 // 原SDK真实类：reset后旧加载仍生效。
 let f=fixture(),p=f.m.setExpression(0);f.m.resetExpression();f.finish();assert.equal(await p,true);assert.equal(f.m.rendered,f.a)
 for(const action of ['reset','current','dispose','newer']){
  f=fixture();const original=[f.m.setExpression,f.m.resetExpression],dispose=ctx.exports.installExpressionRequests(f.m)
  if(action==='current')f.m.currentExpression=f.b
  p=f.m.setExpression(0);const finishOld=f.finish
  if(action==='reset')f.m.resetExpression()
  if(action==='current')assert.equal(await f.m.setExpression(1),false)
  if(action==='dispose'){dispose();dispose();assert.deepEqual([f.m.setExpression,f.m.resetExpression],original)}
  let latest
  if(action==='newer'){latest=f.m.setExpression(1);f.finish();assert.equal(await latest,true)}
  finishOld();assert.equal(await p,false,action+' must reject pending old load')
  if(action==='reset')assert.equal(f.m.rendered,f.base)
  if(action==='newer')assert.equal(f.m.rendered,f.b)
  dispose()
 }
 assert.doesNotThrow(()=>ctx.exports.installExpressionRequests({})())
 console.log('Actual installed SDK ExpressionManager: baseline reset race reproduced; reset/current/newer/dispose invalidate pending expressions. Passed.')
}
run().catch(e=>{console.error(e);process.exitCode=1})
