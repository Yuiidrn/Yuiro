const assert = require('node:assert/strict')
const fs = require('node:fs')
const vm = require('node:vm')
const ts = require('../../shell/node_modules/typescript')
const code = ts.transpileModule(fs.readFileSync('shell/src/renderer/src/avatar/listeningReaction.ts','utf8'),
  {compilerOptions:{module:ts.ModuleKind.CommonJS}}).outputText
const moduleObject={exports:{}}
vm.runInNewContext(code,{module:moduleObject,exports:moduleObject.exports})
const plan=moduleObject.exports.shouldAcknowledgeListening
assert.equal(plan('listening','thinking',true,false,false,20000,0,12000),true)
for(const args of [
  ['idle','thinking',true,false,false,20000,0,12000],
  ['speaking','thinking',true,false,false,20000,0,12000],
  ['listening','thinking',false,false,false,20000,0,12000],
  ['listening','thinking',true,true,false,20000,0,12000],
  ['listening','thinking',true,false,true,20000,0,12000],
  ['listening','thinking',true,false,false,10000,0,12000],
]) assert.equal(plan(...args),false)
console.log('listening reaction: transition, ownership and cooldown passed')
