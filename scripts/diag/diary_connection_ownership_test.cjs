const fs=require('fs'),vm=require('vm'),assert=require('node:assert/strict')
const ts=require('../../shell/node_modules/typescript')
const sockets=[],keys=[],messages=[];let cancelled=0,finished=0,reconnects=0
class Socket {
  static OPEN=1;readyState=1;sent=[]
  constructor(url){this.url=url;sockets.push(this)}
  send(value){this.sent.push(JSON.parse(value))}
  close(){this.readyState=3;this.onclose?.()}
}
const context={WebSocket:Socket,disposed:false,connectionEpoch:0,ws:null,reconnectTimer:0,
  ENGINE_WS:'ws://fixture/ws/control',conn:{value:'off'},busy:{value:true},status:{value:''},
  cancelQuip:()=>cancelled++,finishAppend:()=>finished++,onMessage:x=>messages.push(x),
  window:{yuiro:{getEngineSecret:()=>new Promise(resolve=>keys.push(resolve))},clearTimeout(){},setTimeout(){reconnects++;return 1}}}
const source=fs.readFileSync('shell/src/renderer/src/diary/DiaryApp.vue','utf8')
const body=source.slice(source.indexOf('async function wsUrl('),source.indexOf('/** 段落被删'))
vm.runInNewContext(ts.transpileModule(body,{compilerOptions:{target:ts.ScriptTarget.ES2022}}).outputText,context)
;(async()=>{
  const old=context.connect(),newer=context.connect()
  keys[1]('fixture');await newer
  const current=sockets[0];current.onopen()
  keys[0]('fixture');await old
  assert.equal(sockets.length,1,'迟到的旧密钥不能创建/覆盖连接')
  assert.equal(context.ws,current);assert.equal(current.sent[0].type,'diary:start')
  const replacement=context.connect();keys[2]('fixture');await replacement
  const latest=sockets[1];latest.onopen()
  const before={cancelled,finished,reconnects}
  current.onclose();current.onerror();current.onmessage({data:JSON.stringify({type:'diary:audio',request_id:1})})
  assert.equal(context.ws,latest);assert.equal(context.conn.value,'ok')
  assert.equal(messages.length,0);assert.deepEqual({cancelled,finished,reconnects},before)
  latest.onmessage({data:JSON.stringify({type:'diary:state',active:true})});assert.equal(messages.length,1)
  latest.onclose()
  assert.equal(context.ws,null);assert.equal(context.conn.value,'off')
  assert.equal(cancelled,before.cancelled+1);assert.equal(finished,before.finished+1)
  assert.equal(reconnects,before.reconnects+1);assert.equal(context.busy.value,false)
  const pending=context.connect();context.disposed=true;keys[3]('fixture');await pending
  assert.equal(sockets.length,2,'卸载后密钥返回不得新建连接')
  console.log('Diary production connection: out-of-order credential lookup, stale close/error/message, owned cleanup and disposed lookup passed.')
})().catch(error=>{console.error(error);process.exitCode=1})
