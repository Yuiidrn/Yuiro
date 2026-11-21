const fs=require('fs'),vm=require('vm'),assert=require('node:assert/strict'),ts=require('../../shell/node_modules/typescript')
const context={exports:{},WeakMap}
vm.runInNewContext(ts.transpileModule(fs.readFileSync('shell/src/renderer/src/avatar/expressionBlinkOrder.ts','utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText,context)
let eye=1,moving=false,expressive=true,blinkCount=0,lastDelta,order=[]
const listeners=new Set()
const blink={updateParameters(core,dt){assert.equal(core,internal.coreModel);eye=1;blinkCount++;lastDelta=dt;order.push('blink')}}
const manager={update(){if(moving)eye=.4;order.push('motion');return moving}}
const internal={coreModel:{},eyeBlink:blink,motionManager:manager,on:(_,f)=>listeners.add(f),off:(_,f)=>listeners.delete(f),
 update(ms){const changed=manager.update();listeners.forEach(f=>f());order.push('save');if(expressive)eye*=0;order.push('expression');if(!changed)blink.updateParameters(this.coreModel,ms/1000);order.push('draw');return 'frame'}}
internal.update(16);assert.equal(eye,1,'复现SDK眨眼后写覆盖闭眼笑')
const original=[internal.update,manager.update,blink.updateParameters],install=context.exports.installExpressionBlinkOrder
const dispose=install(internal);assert.equal(install(internal),dispose);assert.equal(listeners.size,1)
order=[];blinkCount=0;assert.equal(internal.update(16),'frame')
assert.equal(eye,0);assert.equal(blinkCount,1);assert.equal(lastDelta,.016)
assert(order.indexOf('blink')<order.indexOf('expression'))
moving=true;blinkCount=0;internal.update(16);assert.equal(eye,0);assert.equal(blinkCount,0,'动作控制眼睛时不叠加自动眨眼')
moving=false;expressive=false;internal.update(16);assert.equal(eye,1,'默认状态保留正常眨眼')
dispose();dispose();assert.equal(listeners.size,0)
assert.deepEqual([internal.update,manager.update,blink.updateParameters],original)
assert.doesNotThrow(()=>install({})())
console.log('Expression/blink production adapter: reproduced overwrite, expression owns eyes, one blink/frame, motion exclusion, time units and idempotent teardown passed.')
