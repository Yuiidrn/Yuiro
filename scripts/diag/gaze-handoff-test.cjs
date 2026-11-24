// 用真实过渡函数模拟动作末帧、鼠标目标和中途反向。
const assert = require('node:assert/strict')
const fs = require('node:fs')
const vm = require('node:vm')
const ts = require('../../shell/node_modules/typescript')
const source = fs.readFileSync('shell/src/renderer/src/avatar/gaze.ts', 'utf8')
const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText
const moduleObject = { exports: {} }
vm.runInNewContext(compiled, { module: moduleObject, exports: moduleObject.exports, Math, Number, Set })
const { followPose, gazeTarget, applyGaze } = moduleObject.exports
for (const eye of [false, true]) {
  for (const [start, target] of eye ? [[-.6,.6],[.6,-.6],[.4,.4]] : [[-20,20],[20,-20],[12,12]]) {
    let pose = start
    for (let i = 0; i < 300; i++) {
      const destination = i < 45 ? target : -target
      const next = followPose(pose, destination, 16, eye)
      assert.ok(Math.abs(next-pose) <= (eye ? 2 : 45)*.016+1e-9)
      assert.ok(next >= Math.min(pose,destination)-1e-9 && next <= Math.max(pose,destination)+1e-9)
      pose = next
    }
    assert.ok(Math.abs(pose+target) < (eye ? .01 : .2))
  }
}
const target = gazeTarget(100,20,{left:0,top:0,width:100,height:100},.18)
assert.ok(Math.abs(target[0]-.09)<1e-9 && Math.abs(target[1])<1e-9)
const up = gazeTarget(50,-5,{left:0,top:0,width:100,height:100},.18)
const down = gazeTarget(50,45,{left:0,top:0,width:100,height:100},.18)
assert.ok(up[1] > .1 && down[1] < -.1)
const values = { ParamAngleZ: 12, ParamEyeBallX: 0 }
applyGaze({getParameterValueById:id=>values[id],setParameterValueById:(id,v)=>values[id]=v},new Set(Object.keys(values)),.2,0,1)
assert.equal(values.ParamAngleZ,12)
assert.equal(values.ParamEyeBallX,.4)
console.log('gaze handoff: opposite/same direction, changing target, speed limit and convergence passed')
