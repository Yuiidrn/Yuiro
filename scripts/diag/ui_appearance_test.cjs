/* Exercise the production schema/styles/layout, including persisted partial/bad preferences. */
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict'),path=require('node:path')
const {createRequire}=require('node:module')
const ts=createRequire(path.resolve('shell/package.json'))('typescript')
function load(file){const ctx={exports:{}};vm.runInNewContext(ts.transpileModule(fs.readFileSync(file,'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS}}).outputText,ctx);return ctx.exports}
const {normalizeUiAppearance:normalize,panelAppearance,UI_APPEARANCE_DEFAULTS:defaults}=load('shell/src/shared/uiAppearance.ts')
assert.equal(JSON.stringify(normalize(null)),JSON.stringify(defaults))
assert.equal(JSON.stringify(normalize([])),JSON.stringify(defaults))
const bad=normalize({theme:'url(evil)',gap:Infinity,speech:{fontSize:'url(evil)',padding:-10,maxHeight:99999},source:{width:NaN,summaryLines:999,showDate:'false'}})
assert.equal(bad.theme,'light');assert.equal(bad.gap,12);assert.equal(bad.speech.fontSize,15)
assert.equal(bad.speech.padding,4);assert.equal(bad.speech.maxHeight,900);assert.equal(bad.source.width,280)
assert.equal(bad.source.summaryLines,8);assert.equal(bad.source.showDate,true)
const partial=normalize({results:{fontSize:18},source:{fontSize:20,independent:false}})
assert.equal(panelAppearance(partial,'source','light')['--panel-font'],'18px')
partial.source.independent=true
assert.equal(panelAppearance(partial,'source','light')['--panel-font'],'20px')
partial.theme='auto';assert.equal(panelAppearance(partial,'speech','dark')['--panel-rgb'],'36, 32, 29')
partial.theme='light';assert.equal(panelAppearance(partial,'speech','dark')['--panel-rgb'],'255, 255, 255')
for(let i=-200;i<1000;i+=7){
 const p=normalize({gap:i,speech:{fontSize:i,maxHeight:i},results:{seconds:i},source:{summaryLines:i,width:i}})
 assert(p.gap>=4&&p.gap<=48&&p.speech.fontSize>=10&&p.speech.fontSize<=36)
 assert(p.source.width>=160&&p.source.width<=420&&p.results.seconds>=0&&p.results.seconds<=120)
 assert.equal(JSON.stringify(normalize(p)),JSON.stringify(p),'normalization must be idempotent')
}
const {placeDetached,overlaps}=load('shell/src/main/detachedLayout.ts')
for(const gap of [4,12,48,NaN,999,-50])for(const side of ['left','right']){
 const model={x:500,y:100,width:200,height:450},work={x:0,y:0,width:1400,height:900}
 const a=placeDetached(model,work,{width:320,height:300},side,0,0,[],gap)
 assert(a&&!overlaps(a,model))
 const b=placeDetached(model,work,{width:300,height:200},side,0,0,[a],gap)
 assert(b&&!overlaps(b,model)&&!overlaps(a,b))
}
console.log('UI appearance: partial/invalid storage, bounded styles, source inheritance, theme and gap/non-overlap passed.')
const app=fs.readFileSync('shell/src/renderer/src/App.vue','utf8')
const timerBody=app.match(/function scheduleResultHide\(\):void \{([\s\S]*?)\n\}/)[1]
const waits=[]
const timer={resultTimer:0,clearTimeout(){},setTimeout(fn,ms){waits.push(ms);return 1},
 resultCard:{value:{kind:'song'}},officialPlayback:{value:{playback_id:'owned'}},uiAppearance:{settings:{value:normalize({results:{seconds:1}})}}}
timer.window={setTimeout:timer.setTimeout}
vm.runInNewContext('function run(){'+timerBody+'};run()',timer)
assert.equal(waits.length,0,'owned client controls must never auto-hide')
timer.officialPlayback.value=null
vm.runInNewContext('function run(){'+timerBody+'};run()',timer)
assert.equal(waits[0],1000)
timer.uiAppearance.settings.value.results.seconds=0
vm.runInNewContext('function run(){'+timerBody+'};run()',timer)
assert.equal(waits.length,1,'0 means keep until dismissed')
console.log('UI timers: owned playback retained; ordinary card duration and manual dismissal passed.')
const sourceBody=app.match(/function scheduleSourceHide\(\):void \{([\s\S]*?)\n\}/)[1]
const callbacks=[],source={sourceTimer:0,sourceCard:{value:{kind:'source'}},clearTimeout(){},clearSourceCard(){source.sourceCard.value=null},uiAppearance:{settings:{value:normalize({source:{seconds:2}})}},window:{setTimeout(fn,ms){callbacks.push({fn,ms});return 1}}}
vm.runInNewContext('function run(){'+sourceBody+'};run()',source)
assert.equal(callbacks[0].ms,2000)
callbacks[0].fn();assert.equal(source.sourceCard.value,null)
assert.equal(timer.resultCard.value.kind,'song','source expiration must not dismiss music')
source.sourceCard.value={kind:'source'};source.uiAppearance.settings.value.source.seconds=0
vm.runInNewContext('function run(){'+sourceBody+'};run()',source)
assert.equal(callbacks.length,1)
console.log('Independent source timer: expiration/manual lifetime cannot dismiss music.')

const {dialogueLine,dialogueOffset}=load('shell/src/shared/dialogueLine.ts')
const speech=normalize({speech:{mode:'line',anchorY:-.3,lineRise:40,lineBend:.25}}).speech
const h=600,offset=dialogueOffset(speech,'live2d/hiyori/model.json',h)
const oldY=h*(-.3-.14),oldDelta=Math.abs(h*.14+oldY+18*1.25+8-h*.24)
const newDelta=Math.abs(h*.14+offset+speech.fontSize*1.25+8-h*.24)
assert(newDelta<oldDelta/2,'line text is placed closer to mouth than old bubble anchor')
const model={x:100,y:100,width:200,height:600},text={x:312,y:200,width:250,height:120}
const flat=dialogueLine(model,text,.7,.24,18,0),bent=dialogueLine(model,text,.7,.24,18,.8)
assert.notEqual(flat.path,bent.path);assert(!/[zZ]/.test(flat.path));assert.equal((flat.path.match(/C/g)||[]).length,1)
assert.equal(normalize({speech:{lineRise:-10,lineBend:Infinity}}).speech.lineRise,0)
assert.equal(normalize({speech:{lineBend:Infinity}}).speech.lineBend,.25)
console.log('Dialogue: compact mouth-based placement, adjustable curvature, bounded settings passed.')

const {resolveSkin}=load('shell/src/shared/uiAppearance.ts')
assert.equal(resolveSkin('auto','hotaru'),'lily');assert.equal(resolveSkin('auto','hiyori'),'cream')
assert.equal(resolveSkin('cream','hotaru'),'cream');assert.equal(normalize({skin:'javascript:bad'}).skin,'auto')
assert.equal(panelAppearance(normalize({}),'speech','light','lily')['--panel-text'],'#35434c')
const {mangaBubble}=load('shell/src/shared/mangaBubble.ts')
for(const w of [160,260,700])for(const h of [112,300,900])for(const t of [0,28,120]){
 const d=mangaBubble(w,h,t,30)
 assert(!/NaN|Infinity/.test(d));assert.equal((d.match(/M/g)||[]).length,1);assert.equal((d.match(/Z/g)||[]).length,1)
 assert(t===0?!d.includes(' C '):d.includes(' C '),'tail is part of the same closed path')
}
console.log('Character skins: auto/manual mapping, safe tokens and single-contour manga geometry passed.')

const {contourBands}=load('shell/src/renderer/src/utils/contourBands.ts')
const alpha=new Uint8Array(128*256)
for(let y=12;y<230;y++)for(let x=(y<90?50:35);x<(y<90?72:88);x++)alpha[y*128+x]=255
const mask={width:128,height:256,alpha,left:0,top:0,cssWidth:256,cssHeight:512}
const bands=contourBands(mask);assert(bands.length<=16&&bands.length>0)
assert.equal(contourBands(mask),bands,'unchanged mask reuses cached band projection')
for(let y=0;y<256;y++)for(let x=0;x<128;x++)if(alpha[y*128+x]>=4)assert(bands.some(r=>x*2>=r.x&&x*2<r.x+r.width&&y*2>=r.y&&y*2<r.y+r.height))
assert.equal(contourBands(null).length,0)
const asset={x:50,y:20,width:300,height:512},solid={x:140,y:20,width:100,height:512}
const near=placeDetached(solid,{x:0,y:0,width:900,height:800},{width:180,height:160},'right',0,0,[],8,[solid])
assert(near&&overlaps(near,asset)&&!overlaps(near,solid),'UI may occupy transparent asset padding, never protected pixels')
console.log('Contour placement: cached conservative bands, opaque coverage and transparent-padding proximity passed.')

assert.equal(normalize({speech:{ornamentAlpha:3}}).speech.ornamentAlpha,1)
assert.equal(normalize({speech:{ornamentAlpha:NaN}}).speech.ornamentAlpha,.6)
const dockScope={exports:{},require:()=>({useLocalStorage:(key,def)=>({value:key==='yuiro-chat-dock-height'?999:def})})}
vm.runInNewContext(ts.transpileModule(fs.readFileSync('shell/src/renderer/src/composables/useChatDockPref.ts','utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS}}).outputText,dockScope)
const dock=dockScope.exports.useChatDockPref();assert.equal(dock.height.value,80)
dock.reset();assert.equal(dock.height.value,44)
assert.equal(dockScope.exports.chatDockCssVars(330,.93,999)['--dock-h'],'80px')
assert.equal(dockScope.exports.chatDockCssVars(330,.93,NaN)['--dock-h'],'44px')
console.log('Dock height: bounded storage/styles/reset; corner opacity bounded and legacy defaults passed.')
const moreDock=dockScope.exports.chatDockCssVars(330,.93,44,9999,-999,999,NaN)
assert.equal(moreDock['--dock-x'],'1000px');assert.equal(moreDock['--dock-y'],'-50px')
assert.equal(moreDock['--dock-radius'],'40px');assert.equal(moreDock['--dock-font'],'14px')
dock.offsetX.value=80;dock.offsetY.value=120;dock.radius.value=0;dock.fontSize.value=24;dock.reset()
assert.equal(dock.offsetX.value,0);assert.equal(dock.offsetY.value,0);assert.equal(dock.radius.value,28);assert.equal(dock.fontSize.value,14)
console.log('Dock position/style: bounded CSS and grouped reset passed.')
