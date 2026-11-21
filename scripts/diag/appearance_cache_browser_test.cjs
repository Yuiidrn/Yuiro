const {app,BrowserWindow}=require('electron')
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict')
const root=process.cwd(),dir=path.join(root,'.env-local','preview-cache-check')
fs.mkdirSync(dir,{recursive:true});app.setPath('userData',dir)
const ts=require(path.join(root,'shell/node_modules/typescript'))
const code=ts.transpileModule(fs.readFileSync(path.join(root,'shell/src/renderer/src/avatar/previewCache.ts'),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText
app.whenReady().then(async()=>{
 const win=new BrowserWindow({show:false,webPreferences:{contextIsolation:false,nodeIntegration:true,backgroundThrottling:false}})
 const file=path.join(dir,'fixture.html');fs.writeFileSync(file,'<!doctype html><title>Preview cache verification</title>')
 await win.loadFile(file)
 const result=await win.webContents.executeJavaScript(`(async()=>{
   const load=()=>{const exports={};new Function('exports',${JSON.stringify(code)})(exports);return exports}
   const first=load(),key='test:'+Date.now(),image='data:image/png;base64,fixture'
   const t=performance.now();await first.writePreview(key,image)
   const roundtrip=await first.readPreview(key),second=load(),reopened=await second.readPreview(key)
   const missing=await first.readPreview(key+':missing')
   const original=IDBDatabase.prototype.transaction
   IDBDatabase.prototype.transaction=function(...args){const tx=original.apply(this,args);queueMicrotask(()=>tx.abort());return tx}
   const aborted=await first.readPreview(key)
   await first.writePreview(key,image)
   IDBDatabase.prototype.transaction=original
   const elapsedMs=performance.now()-t
   const savedOpen=indexedDB.open;indexedDB.open=()=>({})
   const fallbackStart=performance.now(),fallback=await load().readPreview(key)
   const fallbackMs=performance.now()-fallbackStart;indexedDB.open=savedOpen
   return {roundtrip:roundtrip===image,reopened:reopened===image,missing:missing==='',aborted:aborted==='',elapsedMs,stalledOpenFallback:fallback==='',fallbackMs}
 })()`)
 assert(result.roundtrip&&result.reopened&&result.missing&&result.aborted&&result.stalledOpenFallback)
 const report=path.join(root,'docs/plan/appearance-studio-artifacts/cache-browser-check.json')
 fs.writeFileSync(report,JSON.stringify({date:new Date().toISOString(),surface:'isolated hidden Electron renderer; real IndexedDB',...result},null,2)+'\n')
 console.log(JSON.stringify(result));win.destroy();app.quit()
}).catch(error=>{console.error(error);app.exit(1)})
