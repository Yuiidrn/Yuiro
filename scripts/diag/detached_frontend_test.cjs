/* Exercise production layout, not a copied algorithm. Run from repo root. */
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict')
const {createRequire}=require('node:module'),path=require('node:path')
const ts=createRequire(path.resolve('shell/package.json'))('typescript')
const source=fs.readFileSync('shell/src/main/detachedLayout.ts','utf8')
const ctx={exports:{}};vm.runInNewContext(ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.CommonJS}}).outputText,ctx)
const {placeDetached,overlaps}=ctx.exports
let count=0
for(const origin of [0,-1920])for(const ax of [8,300,1500,1670])for(const ay of [8,350,650])for(const side of ['left','right']){
 const work={x:origin,y:0,width:1920,height:1080},a={x:origin+ax,y:ay,width:240,height:420}
 const r=placeDetached(a,work,{width:240,height:180},side)
 assert(r,'normal desktop must have room');assert(!overlaps(r,a))
 assert(r.x>=origin&&r.y>=0&&r.x+r.width<=origin+1920&&r.y+r.height<=1080)
 const second=placeDetached(a,work,{width:224,height:280},side,0,0,[r])
 if(second){assert(!overlaps(second,a));assert(!overlaps(second,r))}
 count++
}
assert.equal(placeDetached({x:0,y:0,width:320,height:300},{x:0,y:0,width:320,height:300},{width:200,height:200},'right'),null)
assert.equal(placeDetached({x:100,y:100,width:200,height:400},{x:0,y:0,width:1200,height:800},{width:200,height:200},'left').x,312)
console.log(`Detached layout: ${count} edge/negative-display scenarios + no-space/fallback passed.`)

// Run the actual coordinator with an Electron boundary mock: sender/key/index/ready fencing.
const handlers={},created=[]
class Window {
 constructor(){this.handlers={};this.visible=false;this.bounds={x:300,y:100,width:420,height:560};this.sent=[];this.webContents={id:created.length+1,on(){},setWindowOpenHandler(){},send:(name,data)=>this.sent.push({name,data})};created.push(this)}
 on(n,fn){this.handlers[n]=fn}isDestroyed(){return false}isVisible(){return this.visible}isMinimized(){return false}
 setAlwaysOnTop(){}setContentProtection(){}setIgnoreMouseEvents(v){this.ignore=v}loadFile(){}loadURL(){}hide(){this.visible=false}showInactive(){this.visible=true}
 getBounds(){return this.bounds}setBounds(b){this.bounds=b}
}
const pet=new Window();created.length=0;pet.webContents.id=100;pet.visible=true
const electron={BrowserWindow:Window,ipcMain:{on:(name,f)=>handlers[name]=f},screen:{getDisplayMatching:()=>({workArea:{x:0,y:0,width:1920,height:1080}}),on(){}}}
const lineScope={exports:{}};vm.runInNewContext(ts.transpileModule(fs.readFileSync('shell/src/shared/dialogueLine.ts','utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS}}).outputText,lineScope)
const scope={exports:{},__dirname:'test',process:{env:{}},require:n=>n==='electron'?electron:n==='node:path'?path:n==='./detachedLayout'?ctx.exports:n==='../shared/dialogueLine'?lineScope.exports:null}
vm.runInNewContext(ts.transpileModule(fs.readFileSync('shell/src/main/detachedUi.ts','utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText,scope)
scope.exports.registerDetachedUi(()=>pet)
const publish=s=>handlers['detached:publish']({sender:pet.webContents},s)
const state={key:'role-a-card-1',anchor:{x:80,y:0,width:240,height:500},viewport:{width:420,height:560},speech:{text:'reply',visible:true,width:190,alpha:.92,offsetX:0,offsetY:0},results:{title:'song',kind:'song',items:[{name:'track',song_id:'123'}],width:224,alpha:.92,side:'left',offsetX:0,offsetY:0}}
assert.equal(created.length,0)
handlers['detached:publish']({sender:{id:666}},state);assert.equal(created.length,0)
publish(state);assert.equal(created.length,2)
for(const win of created){handlers['detached:ready']({sender:win.webContents});assert.equal(win.visible,false,'must measure current-key content before first show');handlers['detached:size']({sender:win.webContents},{key:state.key,width:224,height:140});assert.equal(win.visible,true)}
const results=created[1]
function action(a,sender=results.webContents){handlers['detached:action']({sender},a)}
const valid={kind:'results',key:state.key,index:0}
action(valid);assert.equal(pet.sent.length,1)
action({...valid,key:'old'});action({...valid,index:-1});action({...valid,index:99});action({...valid,kind:'speech'});action(valid,{id:666});assert.equal(pet.sent.length,1)
publish({...state,key:'role-b-card-1'});action(valid);assert.equal(pet.sent.length,1,'old-role action must not forward')
publish({...state,key:'role-b-card-1',speech:{...state.speech,visible:false},results:null})
assert(created.every(w=>!w.visible),'empty state must hide both native windows')
console.log('Detached coordinator: lazy creation, measure-before-show, sender/key/index fencing and empty cleanup passed.')

// All three surfaces coexist, source clicks cannot become player commands.
const three={...state,key:'three',sources:{...state.results,title:'sources',kind:'source',items:[{title:'official',url:'https://www.electronjs.org/'}]}}
publish(three);assert.equal(created.length,3)
for(const win of created){handlers['detached:ready']({sender:win.webContents});handlers['detached:size']({sender:win.webContents},{key:three.key,width:224,height:300})}
assert(created.every(w=>w.visible),'three normal panels must fit')
for(let i=0;i<created.length;i++)for(let j=i+1;j<created.length;j++)assert(!overlaps(created[i].bounds,created[j].bounds))
const sources=created[2],beforeSource=pet.sent.length
action({kind:'sources',key:three.key,index:0,action:'pick'},sources.webContents)
assert.equal(pet.sent.length,beforeSource+1)
for(const command of ['client_play','client_pause','client_resume','open_official'])action({kind:'sources',key:three.key,index:0,action:command},sources.webContents)
action({kind:'results',key:three.key,index:0},sources.webContents)
assert.equal(pet.sent.length,beforeSource+1,'source sender cannot control music')
publish({...three,sources:null});assert(!sources.visible);assert(results.visible)
console.log('Three panels: non-overlap, source routing/player fencing and independent dismissal passed.')
const lineState={...three,key:'line-role',speech:{...three.speech,line:{mouthX:.7,mouthY:.16,fontSize:18,color:'#ffffff',stroke:1.2}}}
publish(lineState)
handlers['detached:size']({sender:created[0].webContents},{key:lineState.key,width:224,height:140})
const connector=created[3];assert(connector&&connector.ignore===true)
handlers['detached:ready']({sender:connector.webContents});assert(connector.visible)
const beforeLine=pet.sent.length
action({kind:'results',key:lineState.key,index:0},connector.webContents);assert.equal(pet.sent.length,beforeLine)
assert.equal(connector.sent.at(-1).name,'detached:line')
assert(!connector.sent.at(-1).data.path.includes('Z'))
publish({...lineState,key:'switched',speech:{...lineState.speech,visible:false},results:null,sources:null})
assert(!connector.visible,'role/content cleanup must hide click-through connector')
console.log('Dialogue connector: click-through only, one open curve, sender isolation and role cleanup passed.')

publish({...three,key:'owned',results:{...three.results,playback:{backend:'netease_client',song_id:'36308916',playback_id:'p',liked:false,status:'paused',can_stop:false}}})
const favoriteBefore=pet.sent.length
for(const command of ['client_like','client_unlike'])action({kind:'results',key:'owned',action:command})
assert.equal(pet.sent.length,favoriteBefore+2)
for(const command of ['client_like','client_unlike'])action({kind:'sources',key:'owned',action:command},sources.webContents)
action({kind:'results',key:'previous-role',action:'client_like'})
assert.equal(pet.sent.length,favoriteBefore+2)
publish({...three,key:'unowned'})
action({kind:'results',key:'unowned',action:'client_like'})
assert.equal(pet.sent.length,favoriteBefore+2)
console.log('Favorite actions: owned result sender only; source, stale role and unowned controls denied.')

const headState={...state,key:'head-stable',speech:{...state.speech,headY:.24}}
publish(headState)
for(let i=0;i<3;i++)handlers['detached:size']({sender:created[0].webContents},{key:headState.key,width:198,height:236})
const stableHeadCount=created[0].sent.length
for(let i=0;i<20;i++)handlers['detached:size']({sender:created[0].webContents},{key:headState.key,width:198,height:236})
assert.equal(created[0].sent.length,stableHeadCount,'unchanged measurements must not toggle tip payload endlessly')
assert(Number.isFinite(created[0].sent.at(-1).data.speech.tipY))
console.log('Head pointer: stable payload after measurement; no alternating IPC update loop.')
