const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict')
const ts=require('../../shell/node_modules/typescript')
const source=fs.readFileSync('shell/src/renderer/src/dev/components/AppearanceStudio.vue','utf8').split('<script setup lang="ts">')[1].split('</script>')[0]
const vue={ref:value=>({value}),computed:get=>({get value(){return get()}}),watch(){},onMounted(){},onBeforeUnmount(){}}
const store={sections:{persona:{model_path:'/hotaru'}},character:{active_id:'hotaru'}}
const context={exports:{},console,setTimeout,clearTimeout,window:{yuiro:{}},require:name=>{
 if(name==='vue')return vue
 if(name==='@vueuse/core')return {useLocalStorage:(_,value)=>({value})}
 if(name.endsWith('/stores/config'))return {useConfigStore:()=>store}
 if(name.endsWith('/useAvatarClickPref'))return {useAvatarClickPref:()=>({})}
 if(name.endsWith('/previewCache'))return {readPreview:async()=>'',writePreview:async()=>{}}
 if(name.endsWith('/avatarSlots'))return {resolveMotion:()=>null,resolveExpression:()=>({name:''})}
 return {}
}}
vm.runInNewContext(ts.transpileModule(source+'\nexports.h={previewIntent,queueThumbnails,stopPreview,stage,loading};',{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText,context)
const h=context.exports.h
const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms))
;(async()=>{
 let calls=0,cancelled=0
 h.loading.value=false
 h.stage.value={preparePreview:async(_,valid)=>{calls++;return valid()},cancelPerformance(){cancelled++},applyAvatarIntent(){}}
 h.queueThumbnails()
 assert.equal(await h.previewIntent({motion:'manual'}),true)
 await sleep(230)
 assert.equal(calls,1,'scheduled batch must not supersede manual playback')
 h.queueThumbnails();h.stopPreview();await sleep(230)
 assert.equal(calls,1);assert.equal(cancelled,1)
 let release
 h.stage.value.preparePreview=async(_,valid)=>{await new Promise(r=>release=r);return valid()}
 const pending=h.previewIntent({motion:'slow'})
 h.stopPreview();release()
 assert.equal(await pending,false,'cancelled async preload must not become current')
 console.log('Appearance studio: manual preview cancels auto timer; stop cancels timer and invalidates pending preload. Passed.')
})().catch(e=>{console.error(e);process.exitCode=1})
