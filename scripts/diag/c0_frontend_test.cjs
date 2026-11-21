// C0: test exact production functions with controlled async dependencies.
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const { createRequire } = require('node:module');
const root = path.resolve(__dirname, '../..');
const ts = createRequire(path.join(root, 'shell/package.json'))('typescript');
function extract(file, names) {
  const text = fs.readFileSync(path.join(root, file), 'utf8');
  const ast = ts.createSourceFile(file, text, ts.ScriptTarget.Latest, true);
  const found = [];
  function visit(n) {
    if (ts.isFunctionDeclaration(n) && names.includes(n.name?.text)) found.push(n.getText(ast));
    ts.forEachChild(n, visit);
  }
  visit(ast);
  assert.equal(found.length, names.length);
  return ts.transpileModule(found.join('\n'), {
    compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS }
  }).outputText;
}
const audio = extract('shell/src/renderer/src/composables/useVoiceInput.ts', ['playOne', 'stopPlayback']);
const model = extract('shell/src/renderer/src/components/Live2DCanvas.vue', ['loadModel']);
const config = extract('shell/src/renderer/src/App.vue', ['loadModelPath']);
async function audioTest() {
  const result = await vm.runInNewContext(`
    let release, entered, starts=0, playbackEpoch=0;
    const decoding = new Promise(r=>release=r), started=new Promise(r=>entered=r);
    let audioCtx={destination:{},decodeAudioData(){entered(); return decoding},
      createBufferSource(){return {connect(){},start(){starts++},stop(){}}}};
    async function ensureAudioCtxRunning(){}
    function stopMouthLoop(){} function driveMouth(){} function maybeEmitPlaybackEnd(){}
    let mouthVolumes=[],mouthSliceMs=20,mouthStart=0,currentSource=null,currentPlayResolve=null;
    let ws=null,playQueue=[],engineSentAll=false,pendingSegments=1,playedThisTurn=true;
    ${audio}
    (async()=>{
      const old=playOne('AA==',24000,20,[0]); await started;
      stopPlayback(); pendingSegments=7; release({}); await old;
      return {starts,pendingSegments,currentSource};
    })()
  `, { Uint8Array, atob: s => Buffer.from(s, 'base64').toString('binary'), performance });
  assert.equal(result.starts, 0, 'old decoded audio must not start');
  assert.equal(result.pendingSegments, 7, 'old finally must not decrement new turn');
  assert.equal(result.currentSource, null);
}
async function modelTest() {
  const result = await vm.runInNewContext(`
    let modelRevision=0, model=null, added=[], destroyed=[], pending={};
    const canvasRef={value:{}},currentModelPath={value:''},loadError={value:''},contour={value:null};
    const app={stage:{addChild(m){added.push(m.id)}}};
    function ensureApp(){} function unloadModel(){modelRevision++}
    function layoutModel(){} function releaseToIdle(){} function startIdle(){}
    async function loadManifest(){}
    const Live2DModel={from(p){return new Promise(r=>pending[p]=()=>r({id:p,
      internalModel:{},update(){},destroy(){destroyed.push(p)}}))}};
    ${model}
    (async()=>{
      const a=loadModel('A'),b=loadModel('B');
      pending.B();await b;pending.A();await a;
      return {added,destroyed,active:model.id};
    })()
  `, { fetch: async () => ({ok:true}), console });
  assert.deepEqual(Array.from(result.added), ['B']);
  assert.deepEqual(Array.from(result.destroyed), ['A']);
  assert.equal(result.active, 'B');
}
async function sessionTest() {
  const result = await vm.runInNewContext(`
    let modelConfigRequest=0;
    const ENGINE_API='/api',SESSION_KEY='session';
    const activeCharacter={value:'hiyori'},characterRevision={value:0},modelPath={value:'A'};
    const sessionId={value:'new-authoritative-session'},sessionItems={value:[]};
    const sentMsg={value:null},taskPlan={value:null},modelReady={value:false};
    function stopPlayback(){} function clearActivity(){}
    const localStorage={setItem(){},removeItem(){throw new Error('must not clear new session')}};
    function clearResultCard(){}
    function hideSpeech(){}
    ${config}
    (async()=>{await loadModelPath(); return {session:sessionId.value,role:activeCharacter.value}})()
  `, { fetch: async () => ({ok:true,json:async()=>({character:{active_id:'hotaru',revision:1},
    sections:{persona:{model_path:'B'}}})}), AbortSignal });
  assert.equal(result.session, 'new-authoritative-session');
  assert.equal(result.role, 'hotaru');
}
(async () => {
  await audioTest(); await modelTest(); await sessionTest();
  console.log('C0 frontend: 3 scenarios passed (late decode/old cleanup; late model load; preserve new session). Not browser E2E.');
})().catch(e=>{console.error(e);process.exitCode=1});
