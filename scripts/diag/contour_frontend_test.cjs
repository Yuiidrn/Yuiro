const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict')
const {createRequire}=require('node:module'),path=require('node:path')
const ts=createRequire(path.resolve('shell/package.json'))('typescript')
function extract(file,name){const src=fs.readFileSync(file,'utf8'),ast=ts.createSourceFile(file,src,ts.ScriptTarget.Latest,true);let found;function visit(n){if(ts.isFunctionDeclaration(n)&&n.name?.text===name)found=n.getText(ast);ts.forEachChild(n,visit)}visit(ast);assert(found);return found.replace(/^export /,'')}
function run(source,ctx={}){return vm.runInNewContext(ts.transpileModule(source,{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS}}).outputText,ctx)}
const hit=extract('shell/src/renderer/src/utils/alphaHit.ts','alphaHit')
const alphaHit=run(hit+'\nalphaHit')
const alpha=new Uint8Array(25);alpha[6]=255;alpha[8]=100;alpha[18]=255
const mask={width:5,height:5,alpha,left:10,top:20,cssWidth:50,cssHeight:50}
assert.equal(alphaHit(mask,25,35,24,0),true)
assert.equal(alphaHit(mask,35,45,24,0),false) // 包围盒内部透明间隙
assert.equal(alphaHit(mask,45,35,150,0),false)
assert.equal(alphaHit(mask,45,35,50,0),true)
assert.equal(alphaHit(mask,35,35,24,0),false)
assert.equal(alphaHit(mask,35,35,24,10),true)
assert.equal(alphaHit(null,25,35,24,10),false)
const rel=run(extract('shell/src/renderer/src/composables/useElectronRelativeMouse.ts','relativeCss')+'\nrelativeCss')
assert.equal(rel(230,100,650,500),100) // 130% 页面缩放
assert.equal(rel(-270,-400,650,500),100) // 负坐标副屏
const cursor=run(extract('shell/src/main/overlayCoordinates.ts','overlayCursor')+'\noverlayCursor')
const mixed={getCursorScreenPoint:()=>({x:300,y:200}),dipToScreenPoint:()=>({x:900,y:500}),dipToScreenRect:()=>({x:600,y:200,width:900,height:600})}
assert.equal(cursor(mixed,{getBounds:()=>({x:0,y:0,width:600,height:400})},true).u,1/3)
assert.equal(cursor(mixed,{getBounds:()=>({x:0,y:0,width:600,height:400})},true).v,.5)
const fractions={u:{value:1/3},v:{value:.5},x:{value:999},y:{value:999}}
const cssMouse=run(extract('shell/src/renderer/src/composables/useElectronRelativeMouse.ts','useElectronRelativeMouse')+'\nuseElectronRelativeMouse()',{
 useElectronMouse:()=>fractions,useElectronWindowBounds:()=>({x:{value:0},y:{value:0},width:{value:600},height:{value:800}}),
 useWindowSize:()=>({width:{value:300},height:{value:400}}),computed:f=>({get value(){return f()}}),relativeCss:rel,
})
assert.equal(cssMouse.x.value,100);assert.equal(cssMouse.y.value,200)
fractions.u.value=null;fractions.v.value=null;fractions.x.value=200;fractions.y.value=400
assert.equal(cssMouse.x.value,100);assert.equal(cssMouse.y.value,200)
let ui=false,body=false,drag=false,open=0,last=null
const options={chatOpen:{value:false},menuOpen:{value:false},fadeActive:{value:false},hitModel:()=>body,openIsland:()=>open++}
const listeners={}
const window={yuiro:{setMousePassthrough:v=>last=v,setFocusable(){}},addEventListener:(n,f)=>listeners[n]=f,removeEventListener(){}}
Object.defineProperty(window,'__yuiroDragging',{get:()=>drag})
const api=run(extract('shell/src/renderer/src/composables/useMousePassthrough.ts','useMousePassthrough')+'\nuseMousePassthrough(options)',{
 options,window,document:{elementsFromPoint:()=>ui?[{closest:()=>true}]:[]},
 useElectronRelativeMouse:()=>({x:{value:20},y:{value:20}}),watch(){},onMounted:f=>f(),onBeforeUnmount(){},
})
api.updateFromPointer(20,20);assert.equal(last,true)
body=true;api.updateFromPointer(20,20);assert.equal(last,false)
options.fadeActive.value=true;api.updateFromPointer(20,20);assert.equal(last,true)
ui=true;api.updateFromPointer(20,20);assert.equal(last,false);assert.equal(open,0)
ui=false;drag=true;api.updateFromPointer(20,20);assert.equal(last,false)
drag=false;body=false;listeners['yuiro-contour-updated']();assert.equal(last,true)
console.log('Contour production-function checks passed (holes/alpha/tolerance/zoom/UI/fade/drag/stationary refresh).')
