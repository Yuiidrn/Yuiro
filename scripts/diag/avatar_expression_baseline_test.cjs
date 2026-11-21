const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict')
const ts=require(require.resolve('typescript',{paths:['./shell']}))
const source=fs.readFileSync('shell/src/renderer/src/avatar/expressionBaseline.ts','utf8')
const context={exports:{}};vm.runInNewContext(ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText,context)
const base=new context.exports.ExpressionBaseline()
base.update('happy',false);base.update('surprise',true);assert.equal(base.current(),'happy')
base.update('',false);assert.equal(base.current(),'')
base.update('sad',false);base.reset();assert.equal(base.current(),'')
console.log('Avatar baseline: persistent expression, temporary action, neutral and model reset passed.')
const presenceContext={exports:{}}
vm.runInNewContext(ts.transpileModule(fs.readFileSync('shell/src/renderer/src/avatar/presence.ts','utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText,presenceContext)
const next=presenceContext.exports.presenceAfter
assert.equal(next('idle','vad:state','active'),'listening')
assert.equal(next('listening','asr:start'),'thinking')
assert.equal(next('thinking','tts:audio'),'thinking','receiving audio is not playing')
assert.equal(next('thinking','tts:playback_start'),'speaking')
assert.equal(next('speaking','tts:playback_buffering'),'thinking')
assert.equal(next('listening','tts:playback_buffering'),'listening')
assert.equal(next('speaking','tts:end'),'speaking','sending complete is not playback complete')
assert.equal(next('speaking','llm:text'),'speaking')
for(const event of ['tts:playback_end','tts:playback_cancelled','tts:interrupted','avatar:reset','ws:closed'])assert.equal(next('speaking',event),'idle')
console.log('Avatar presence: listening/thinking/actual playback/cancellation and reset passed.')
const leaseContext={exports:{}}
vm.runInNewContext(ts.transpileModule(fs.readFileSync('shell/src/renderer/src/avatar/intentLease.ts','utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText,leaseContext)
const lease=new leaseContext.exports.IntentLease()
lease.hold(3,100);assert.equal(lease.accepts(1,50),false);assert.equal(lease.accepts(4,50),true)
assert.equal(lease.accepts(1,100),true);lease.reset();assert.equal(lease.accepts(1,0),true)
console.log('Avatar lease: priority protection, expiration and model reset passed.')
const urlContext={exports:{}}
vm.runInNewContext(ts.transpileModule(fs.readFileSync('shell/src/renderer/src/avatar/modelUrl.ts','utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText,{...urlContext,URL})
const assetUrl=urlContext.exports.modelAssetUrl
assert.equal(assetUrl('/live2d/hiyori/Hiyori.model3.json','file:///D:/Yuiro/out/renderer/index.html'),'file:///D:/Yuiro/out/renderer/live2d/hiyori/Hiyori.model3.json')
assert(assetUrl('/live2d/Hotaru Shiomi/model.json','file:///D:/Yuiro/out/renderer/index.html').includes('Hotaru%20Shiomi'))
assert.equal(assetUrl('/live2d/hiyori/model.json','http://localhost:5173/'),'/live2d/hiyori/model.json')
console.log('Avatar model URLs: built-file root, spaces and development paths passed.')
for(const file of ['micoff','micon','singing']){
 const clip=JSON.parse(fs.readFileSync(`shell/src/renderer/public/live2d/hiyori/motions/${file}.motion3.json`,'utf8'))
 assert.equal(clip.Meta.CurveCount,clip.Curves.length,`${file}: declared curves must match SDK input`)
 assert(clip.Curves.every(c=>typeof c.Target==='string'&&Array.isArray(c.Segments)))
}
console.log('Avatar legacy assets: metadata matches actual curves.')
const lipsContext={exports:{}}
vm.runInNewContext(ts.transpileModule(fs.readFileSync('shell/src/renderer/src/avatar/lipSync.ts','utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText,lipsContext)
const writes=[];const core={setParameterValueById:(id,value)=>writes.push([id,value])}
lipsContext.exports.applyLipSync(core,['mouthA','mouthB'],2)
assert.deepEqual(writes,[['mouthA',1],['mouthB',1]])
lipsContext.exports.applyLipSync(core,['mouthA'],NaN);assert.equal(writes.at(-1)[1],0)
console.log('Avatar lips: Cubism4 parameter API, asset IDs, bounds and silence passed.')
const gazeContext={exports:{}}
vm.runInNewContext(ts.transpileModule(fs.readFileSync('shell/src/renderer/src/avatar/gaze.ts','utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText,gazeContext)
const gaze=gazeContext.exports.gazeTarget,rect={left:100,top:100,width:200,height:500}
assert.equal(JSON.stringify(gaze(200,200,rect,.2)),JSON.stringify([0,0]))
assert.equal(JSON.stringify(gaze(5000,200,rect,.2)),JSON.stringify([0,0]))
assert.equal(JSON.stringify(gaze(NaN,200,rect,.2)),JSON.stringify([0,0]))
const target=gaze(300,300,rect,5);assert(target[0]>0&&target[0]<=.4&&target[1]<0&&target[1]>=-.4)
console.log('Avatar gaze: head anchor, distance cutoff, invalid inputs and amplitude bounds passed.')
const activity=new gazeContext.exports.GazeActivity()
assert.equal(activity.step(100,100,true,0,2000),false)
assert.equal(activity.step(110,100,true,10,2000),true)
assert.equal(activity.step(110,100,true,1900,2000),true)
assert.equal(activity.step(110,100,true,2010,2000),false)
assert.equal(activity.step(120,100,true,2100,2000),true)
assert.equal(activity.step(5000,100,false,2200,2000),false)
activity.reset();assert.equal(activity.step(120,100,true,2300,2000),false)
const params={ParamAngleX:17,ParamEyeBallX:.5,ParamBreath:1}
const gazeCore={getParameterValueById:id=>params[id],setParameterValueById:(id,v)=>params[id]=v}
gazeContext.exports.applyGaze(gazeCore,new Set(['ParamAngleX','ParamEyeBallX']),.2,0,1)
assert.equal(params.ParamAngleX,6);assert.equal(params.ParamEyeBallX,.2);assert.equal(params.ParamBreath,1)
console.log('Avatar gaze ownership: moving/still timeout/far/reset, head override and preserved breathing passed.')
const clickContext={exports:{}}
vm.runInNewContext(ts.transpileModule(fs.readFileSync('shell/src/renderer/src/avatar/clickFeedback.ts','utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText,clickContext)
const clicks=clickContext.exports
const manifest={motions:[{group:'Idle',index:0,slot:'idle',durationMs:1900},{group:'Idle',index:1,slot:'idle',durationMs:9000},{group:'Motion',index:2,slot:'greet',durationMs:4000},{group:'Motion',index:3,slot:'angry',durationMs:1000}]}
assert.equal(JSON.stringify(clicks.recommendedClicks(manifest)),JSON.stringify(['Idle#0','Motion#2']))
assert.equal(JSON.stringify(clicks.validClicks(['Idle#0','Idle#0','OldModel#2'],manifest)),JSON.stringify(['Idle#0']))
assert.equal(clicks.validClicks([],manifest).length,0)
assert.equal(clicks.isPetClick(2,2,150),true);assert.equal(clicks.isPetClick(20,0,150),false);assert.equal(clicks.isPetClick(0,0,1000),false)
console.log('Avatar click pools: positive defaults, model validation, empty pool, deduplication and drag/hold exclusion passed.')
const storage=new Map();const clickPrefContext={exports:{},require:name=>name==='@vueuse/core'?{useLocalStorage:(key,initial)=>{if(!storage.has(key))storage.set(key,{value:initial});return storage.get(key)}}:clicks}
vm.runInNewContext(ts.transpileModule(fs.readFileSync('shell/src/renderer/src/composables/useAvatarClickPref.ts','utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText,clickPrefContext)
const pref=clickPrefContext.exports.useAvatarClickPref();pref.write('/modelA',{enabled:true,motions:[]})
assert.equal(pref.read('/modelA',manifest).motions.length,0)
storage.get('yuiro-active-character').value='hotaru';assert(pref.read('/modelA',manifest).motions.length>0)
pref.write('/modelA',{enabled:false,motions:['Idle#0']});assert.equal(pref.read('/modelA',manifest).enabled,false)
assert.equal(pref.read('/modelB',manifest).enabled,true)
storage.get('yuiro-active-character').value='hiyori';assert.equal(pref.read('/modelA',manifest).motions.length,0)
const listeners={},dragCalls=[],cleanup=[];let clicksCount=0,now=100
const dragWindow={addEventListener:(k,fn)=>listeners[k]=fn,removeEventListener:k=>delete listeners[k],yuiro:{dragPetStart:()=>dragCalls.push('start'),dragPetMove:()=>dragCalls.push('move'),dragPetEnd:()=>dragCalls.push('end')}}
const dragContext={exports:{},window:dragWindow,console,performance:{now:()=>now},require:name=>name==='vue'?{onMounted:fn=>fn(),onBeforeUnmount:fn=>cleanup.push(fn)}:clicks}
vm.runInNewContext(ts.transpileModule(fs.readFileSync('shell/src/renderer/src/composables/usePetDrag.ts','utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText,dragContext)
dragContext.exports.usePetDrag(()=>null,(x,y)=>x>0&&y>0,()=>clicksCount++)
const event=(x=10,button=0,ui=false)=>({button,screenX:x,screenY:10,clientX:x,clientY:10,target:{closest:()=>ui},preventDefault(){}})
listeners.mousedown(event());now=200;listeners.mouseup(event());assert.equal(clicksCount,1);assert.equal(dragCalls.length,0)
listeners.mousedown(event());listeners.mousemove(event(30));listeners.mouseup(event(30));assert.equal(clicksCount,1);assert.equal(JSON.stringify(dragCalls),JSON.stringify(['start','move','end']))
listeners.mousedown(event(10,0,true));listeners.mouseup(event());listeners.mousedown(event(10,2));listeners.mouseup(event(10,2));assert.equal(clicksCount,1)
listeners.mousedown(event());listeners.blur();listeners.mouseup(event());assert.equal(clicksCount,1)
cleanup.forEach(fn=>fn());console.log('Click interaction: role/model persistence, empty pool, UI/right-click/blur exclusion and drag lifecycle passed.')
const catalogContext={exports:{}}
vm.runInNewContext(ts.transpileModule(fs.readFileSync('shell/src/renderer/src/avatar/catalog.ts','utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText,catalogContext)
assert.equal(catalogContext.exports.resourceCategory('greet'),'招呼与回应')
assert.equal(catalogContext.exports.resourceCategory('angry'),'情绪变化')
assert.equal(catalogContext.exports.resourceCategory(''),'待分类')
assert(catalogContext.exports.resourceLabel('motions/mtn_bye01_C.motion3.json','greet').includes('mtn_bye01_C'))
console.log('Appearance catalog: semantic groups, unknown fallback and readable asset labels passed.')

const cropContext={exports:{}}
vm.runInNewContext(ts.transpileModule(fs.readFileSync('shell/src/renderer/src/avatar/previewCrop.ts','utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText,cropContext)
const crop=cropContext.exports.previewCrop({cx:150,cy:200,w:120,h:360},false,750,1000,300,400)
assert.equal(crop.sy,50);assert.equal(crop.sh,900)
assert(Math.abs(crop.dw/crop.dh-1/3)<1e-9);assert(crop.dx>=6&&crop.dy>=6)
const headCrop=cropContext.exports.previewCrop({cx:150,cy:200,w:120,h:360},true,750,1000,300,400)
assert.equal(headCrop.sy,crop.sy);assert(headCrop.dh<=168&&headCrop.dw<=168)
const alpha=new Uint8Array(180*240*4)
assert.equal(cropContext.exports.alphaHeadCrop(alpha,180,240),null)
for(let y=70;y<230;y++)for(let x=65;x<115;x++)alpha[(y*180+x)*4+3]=255
const visibleHead=cropContext.exports.alphaHeadCrop(alpha,180,240)
assert.equal(visibleHead.sy,66,'透明头部留白不得占用头像取景')
assert(visibleHead.sw<90&&visibleHead.sx>=0&&visibleHead.sx+visibleHead.sw<=180)
console.log('Preview crop: canvas-local origin, fractional DPI, aspect ratio, padding and head region passed.')

assert.equal(next('thinking','control:closed'),'idle')
assert.equal(next('listening','control:closed'),'idle')
assert.equal(next('speaking','control:closed'),'speaking')
const appSource=fs.readFileSync('shell/src/renderer/src/App.vue','utf8')
const closeHandler=appSource.split('  socket.onclose = (event) => {')[1].split('  socket.onerror =')[0]
function closeScenario(stale,code){
 const effects=[],owner={},state={socket:stale?{}:owner,connectionSocket:owner,
   officialPending:{value:true},mediaRequestId:0,resultCharacterSwitching:false,
   modelConfigRequest:0,isRecording:{value:true},sessionId:{value:'session'},SESSION_KEY:'session-key',
   connClass:{value:'ok'},connSymbol:{value:'●'},localStorage:{removeItem(){}},
   presenceEvent:e=>effects.push(e),clearResultCard(){},hideSpeech(){},stopPlayback:()=>effects.push('stop'),
   stop:async()=>{},log(){},scheduleReconnect:ms=>effects.push(ms),event:{code}}
 vm.runInNewContext('((event)=>{'+closeHandler.trim().replace(/;$/,'')+')(event)',state)
 return {effects,state}
}
assert.equal(closeScenario(true,1012).effects.length,0)
const closed=closeScenario(false,1006);assert.equal(closed.effects[0],'control:closed');assert.equal(closed.state.officialPending.value,false)
console.log('Control lifecycle: stale close ignored; current close resets waiting presence and preserves actual speaking. Passed.')

const switched=closeScenario(false,1012)
assert(switched.effects.includes('stop'));assert(switched.effects.includes(100))
assert.equal(switched.state.sessionId.value,'');assert.equal(switched.state.resultCharacterSwitching,true)

const idleSlots={exports:{},require:()=>({EMOTION_TO_SLOT:{}})}
vm.runInNewContext(ts.transpileModule(fs.readFileSync('shell/src/renderer/src/avatar/avatarSlots.ts','utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText,idleSlots)
const idleManifest={index:{idle:[{group:'Idle',index:0,durationMs:4700},{group:'Idle',index:2,durationMs:4200}]}}
assert.equal(idleSlots.exports.idleCandidates(idleManifest,4500,'Idle#0')[0].index,0)
assert.equal(idleSlots.exports.idleCandidates(idleManifest,4500,'missing#1').length,0)
assert.equal(idleSlots.exports.idleCandidates(idleManifest,4500)[0].index,2)
console.log('Fixed idle: explicit single clip overrides random pool; missing clip stays quiet; legacy rotation filter preserved.')

const canvasSource=fs.readFileSync('shell/src/renderer/src/components/Live2DCanvas.vue','utf8')
const completeSource='function completeAppearance():void{'+canvasSource.split('function completeAppearance():void{')[1].split('function scheduleRelease(')[0]
const finishCalls=[],finishContext={model:{internalModel:{motionManager:{stopAllMotions:()=>finishCalls.push('stop-sdk')}}},motionRequestRevision:1,sdkMotionActive:true,speechGestureActive:true,finishReceipt:()=>finishCalls.push('receipt'),clearReleaseTimer(){},intentLease:{reset(){}},restorePresenceExpression(){},avatarState:{value:{motion:'Idle',motionIndex:6}},startIdle:()=>finishCalls.push('idle')}
vm.runInNewContext(ts.transpileModule(completeSource+'completeAppearance();',{compilerOptions:{target:ts.ScriptTarget.ES2022}}).outputText,finishContext)
assert.equal(finishCalls[0],'stop-sdk');assert.equal(finishCalls.at(-1),'idle')
assert.equal(finishContext.motionRequestRevision,2);assert.equal(finishContext.avatarState.value.motion,'')
console.log('Appearance finish: stop looping SDK motion before receipt and idle recovery; invalidate pending requests. Passed.')

const levelContext={exports:{}}
vm.runInNewContext(ts.transpileModule(fs.readFileSync('shell/src/renderer/src/utils/inputLevel.ts','utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText,levelContext)
const level=levelContext.exports.inputLevel
assert.equal(level(new Float32Array(4096)),0);assert.equal(level(new Float32Array()),0)
assert.equal(level(new Float32Array([NaN,Infinity])),0)
assert.equal(level(new Float32Array([.25,-.25])),1)
assert(Math.abs(level(new Float32Array([.125,-.125]))-.5)<1e-9)
console.log('Microphone meter: true PCM RMS, silence, invalid samples, gain and saturation passed.')

const replyIdentity={exports:{}}
vm.runInNewContext(ts.transpileModule(fs.readFileSync('shell/src/renderer/src/avatar/replyIdentity.ts','utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText,replyIdentity)
const acceptReply=replyIdentity.exports.acceptsReplySpeech
assert(acceptReply({session_id:'s',generation:2},'s',2))
assert(!acceptReply({session_id:'s',generation:1},'s',2))
assert(!acceptReply({session_id:'old-role',generation:99},'s',2))
assert(!acceptReply({},'s',2));assert(!acceptReply({session_id:'s',generation:NaN},'s',2))
console.log('Reply audio identity: current accepted; stale, cross-session and missing identity rejected.')

function replyHandler(type,ctx){
 const start=appSource.split("      } else if (msg.type === '"+type+"') {")[1]
 const body=start.split("      } else if")[0]
 vm.runInNewContext('(()=>{'+body+'})()',ctx)
}
const audioEffects=[],audioContext={msg:{session_id:'s',generation:1},sessionId:{value:'s'},avatarGeneration:{value:2},speechTtsActive:false,acceptsReplySpeech:acceptReply,enqueueReplyAudio:()=>audioEffects.push('queued'),endReplyAudio:()=>{audioEffects.push('end');return true}}
replyHandler('tts:reply_audio',audioContext);assert.equal(audioEffects.length,0)
assert.equal(audioContext.speechTtsActive,false)
audioContext.msg.generation=3;replyHandler('tts:reply_audio',audioContext)
assert.equal(audioContext.avatarGeneration.value,3);assert.equal(audioEffects[0],'queued')
audioContext.msg.generation=2;replyHandler('tts:reply_end',audioContext);assert.equal(audioEffects.length,1)
audioContext.msg.generation=3;replyHandler('tts:reply_end',audioContext);assert.equal(audioEffects[1],'end')
console.log('Actual reply handlers: stale frames cannot enqueue or end; accepted newer audio raises generation floor.')

assert.equal(next('speaking','mic:stop'),'speaking')
assert.equal(next('thinking','mic:stop'),'thinking')
assert.equal(next('listening','mic:stop'),'idle')
console.log('Mic stop presence: active reply playback/thinking survives; input-only listening resets.')
