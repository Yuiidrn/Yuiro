const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict')
const ts=require('../../shell/node_modules/typescript'),infer={exports:{}},slots={exports:{},require:()=>({EMOTION_TO_SLOT:{}})}
function load(file,ctx){vm.runInNewContext(ts.transpileModule(fs.readFileSync(file,'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS}}).outputText,ctx)}
load('shell/src/shared/live2dInfer.ts',infer);load('shell/src/renderer/src/avatar/avatarSlots.ts',slots)
const {inferMotionSlot,inferExpressionSlot,parseMotionName}=infer.exports
for(const word of ['cry','tear','sad']){
 assert.equal(inferMotionSlot('Motion',`mtn_${word}01_C.motion3.json`),'')
 assert.equal(inferExpressionSlot(`exp_${word}01`),'sad','悲伤表情语义保持')
}
for(const word of ['comfort','pat','hug'])assert.equal(inferMotionSlot('Motion',`${word}.motion3.json`),'comfort')
const results=[]
for(const [role,file] of [['hiyori','shell/src/renderer/public/live2d/hiyori/Hiyori.model3.json'],['hotaru','shell/src/renderer/public/live2d/Hotaru Shiomi/016_casual_spring_01/016_casual_spring_01.model3.json']]){
 const model=JSON.parse(fs.readFileSync(file,'utf8')),motions=[],index={motion:{},expression:{},idle:[]},removed=[]
 for(const [group,defs] of Object.entries(model.FileReferences.Motions))defs.forEach((d,i)=>{
  const word=parseMotionName(d.File).word,slot=inferMotionSlot(group,d.File)
  const meta=JSON.parse(fs.readFileSync(path.join(path.dirname(file),d.File),'utf8')).Meta
  motions.push({group,index:i,file:d.File,durationMs:Math.round(meta.Duration*1000),slot})
  if(slot)(index.motion[slot]??=[]).push({group,index:i})
  if(['sad','cry','tear'].includes(word))removed.push({group,index:i,file:d.File,oldSlot:'comfort',newSlot:slot})
 })
 const manifest={motions,index,expressions:[]}
 assert.equal(slots.exports.resolveMotion(manifest,{motion_slot:'comfort'}),null)
 for(const m of removed){assert.equal(m.newSlot,'');assert.equal(slots.exports.resolveMotion(manifest,{motion:m.group,motion_index:m.index}).from,'concrete')}
 if(role==='hotaru')assert(removed.length>0)
 results.push({role,motionCount:motions.length,removedAutomaticComfort:removed,comfortFallback:'no automatic motion',explicitResourcesRemainSelectable:true})
}
fs.writeFileSync('docs/plan/avatar-comfort-semantics.json',JSON.stringify({scope:'Actual model assets through production inference and resolver; not visual approval of all resources',results},null,2))
console.log('Actual assets: sad/cry/tear excluded from automatic comfort; expressions, explicit actions and comfort/pat/hug inference preserved. Passed. Removed candidates:',results.map(r=>`${r.role}:${r.removedAutomaticComfort.length}`).join(', '))
