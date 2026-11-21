const fs=require('fs'),vm=require('vm'),assert=require('node:assert/strict')
const ts=require('../../shell/node_modules/typescript'),audios=[],rejects=[]
class Audio {
 constructor(){audios.push(this)}
 play(){return new Promise((_,reject)=>rejects.push(reject))}
}
const source=fs.readFileSync('shell/src/renderer/src/diary/DiaryApp.vue','utf8')
const begin=source.indexOf('function onMessage('),end=source.indexOf('// ── 输入',begin)
assert(end>begin)
const context={ttsOn:{value:true},replyRequest:{id:1},audioEpoch:0,audioQueue:Promise.resolve(),
 currentAudio:null,audioDone:null,status:{value:'original'},Audio}
vm.runInNewContext(ts.transpileModule(source.slice(begin,end),{compilerOptions:{target:ts.ScriptTarget.ES2022}}).outputText,context)
const flush=async()=>{for(let i=0;i<3;i++)await Promise.resolve()}
;(async()=>{
 context.onMessage({type:'diary:audio',request_id:1,wav:'AA=='});await flush()
 assert.equal(audios.length,1)
 context.audioEpoch++;context.replyRequest={id:2};context.status.value='new-role-status'
 rejects[0](Error('late'));await context.audioQueue
 assert.equal(context.status.value,'new-role-status','旧播放失败不得污染新角色状态')
 context.onMessage({type:'diary:audio',request_id:1,wav:'AA=='});await flush()
 assert.equal(audios.length,1,'旧request_id不得重新播放')
 context.onMessage({type:'diary:audio',request_id:2,wav:'AA=='});await flush()
 rejects[1](Error('current'));await context.audioQueue
 assert.equal(context.status.value,'语音播放失败，文字仍保留','当前播放失败必须仍可见')
 console.log('Diary production audio: stale request rejected, late play rejection isolated, current failure visible. Passed.')
})().catch(error=>{console.error(error);process.exitCode=1})
