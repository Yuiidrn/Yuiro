const fs=require('node:fs'),vm=require('node:vm'),ts=require('../../shell/node_modules/typescript'),assert=require('node:assert/strict')
const ctx={exports:{}};vm.runInNewContext(ts.transpileModule(fs.readFileSync('shell/src/renderer/src/avatar/agentReactions.ts','utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS}}).outputText,ctx)
const planner=new ctx.exports.AgentReactions(),frame={activity_id:'a',tool:'web_search',stage:'tool',outcome:'running',motion_slot:'thinking'}
assert.equal(planner.plan(frame,0,10000).expression_slot,'thinking')
assert.equal(planner.plan(frame,20000,10000),null,'同一消息不重复动作')
const success={...frame,stage:'tool_result',outcome:'success',motion_slot:'greet'}
assert.equal(planner.plan(success,10,10000).expression_slot,'happy','开始与结果可各回应一次')
assert.equal(planner.plan({...success,activity_id:'b'},1000,10000),null,'密集成功不连续挥手')
const error=planner.plan({...success,activity_id:'c',outcome:'error',motion_group:'Motion',motion_index:4},20000,10000)
assert.equal(error.expression_slot,'neutral');assert.equal(error.motion,null);assert.equal(error.motion_slot,null)
planner.reset();const waiting=planner.plan({...success,outcome:'waiting',motion_group:'Motion'},0,10000)
assert.equal(waiting.expression_slot,'thinking');assert.equal(waiting.motion,null)
assert.equal(planner.plan({...frame,activity_id:'z',tool:'avatar_perform'},30000,10000),null)
assert.equal(planner.plan({...success,activity_id:'bad',outcome:'unknown'},30000,10000),null)
const source=fs.readFileSync('shell/src/renderer/src/components/Live2DCanvas.vue','utf8')
const block=source.slice(source.indexOf('playAgentReaction:(intent:'),source.indexOf('preparePreview:async'))
assert(block.includes('agentReactionsEnabled')&&block.includes('reactiveEnabled'))
assert(block.includes('motion.durationMs<=idlePref.agentMaxMs.value')&&block.includes('priority:2'))
console.log('Agent reactions: real outcome choice, batch dedup, independent start/result cooldown, failure/waiting without body motion, reset, explicit performance exclusion, duration/enabled guards passed.')
const storage=new Map(),prefs={exports:{},require:name=>name==='vue'?{computed:spec=>({get value(){return spec.get()},set value(v){spec.set(v)}})}:{useLocalStorage:(key,initial)=>{if(!storage.has(key))storage.set(key,{value:initial});return storage.get(key)}}}
vm.runInNewContext(ts.transpileModule(fs.readFileSync('shell/src/renderer/src/composables/useAvatarIdlePref.ts','utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS}}).outputText,prefs)
const p=prefs.exports.useAvatarIdlePref();p.agentReactionsEnabled.value=false;p.agentCooldownMs.value=7000;p.agentMaxMs.value=2100
storage.get('yuiro-active-character').value='hotaru'
assert.equal(p.agentReactionsEnabled.value,true);assert.equal(p.agentCooldownMs.value,14000);assert.equal(p.agentMaxMs.value,4000)
p.agentCooldownMs.value=19000
storage.get('yuiro-active-character').value='hiyori'
assert.equal(p.agentReactionsEnabled.value,false);assert.equal(p.agentCooldownMs.value,7000);assert.equal(p.agentMaxMs.value,2100)
storage.get('yuiro-active-character').value='hotaru';assert.equal(p.agentCooldownMs.value,19000)
console.log('Production reaction preferences: role switching restores independent enabled/cooldown/duration settings. Passed.')
