// G0 characterization: actual TS functions, controlled fake audio adapter.
// No production source writes, browser, network or physical playback.
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { createRequire } = require('node:module');
const root = path.resolve(__dirname, '../..');
const req = createRequire(path.join(root, 'shell/package.json'));
const ts = req('typescript');
const sourcePath = 'shell/src/renderer/src/composables/useVoiceInput.ts';
const text = fs.readFileSync(path.join(root, sourcePath), 'utf8');
const ast = ts.createSourceFile(sourcePath, text, ts.ScriptTarget.Latest, true);
const names = new Set(['playOne', 'stopPlayback']);
const extracted = [];
function visit(node) {
  if (ts.isFunctionDeclaration(node) && names.has(node.name?.text)) {
    extracted.push({ name: node.name.text, line: ast.getLineAndCharacterOfPosition(node.getStart(ast)).line + 1,
      text: node.getText(ast) });
  }
  ts.forEachChild(node, visit);
}
visit(ast);
if (extracted.length !== 2) throw new Error('Cannot find actual production functions');
const compiled = ts.transpileModule(extracted.map(x => x.text).join('\n'), {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS }
}).outputText;
function loadPure(relative, shared) {
  const original = fs.readFileSync(path.join(root, relative), 'utf8');
  const js = ts.transpileModule(original, {
    compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS }
  }).outputText;
  const exports = {};
  vm.runInNewContext(js, { exports, require: name => {
    if (name === '@shared' && shared) return shared;
    throw new Error(`Unexpected runtime dependency: ${name}`);
  } });
  return exports;
}
function slotInventory() {
  const shared = loadPure('shell/src/shared/live2d.ts');
  const infer = loadPure('shell/src/shared/live2dInfer.ts');
  const resolver = loadPure('shell/src/renderer/src/avatar/avatarSlots.ts', shared);
  const inventory = JSON.parse(fs.readFileSync(path.join(root, 'docs/plan/G0-baseline-artifacts/live2d-inventory.json')));
  return inventory.models.filter(m => m.motions).map(m => {
    const expressions = m.expressions.map(e => ({name: e.Name, slot: infer.inferExpressionSlot(e.Name)}));
    const motions = m.motions.map(x => ({...x, durationMs: Math.round((x.duration_s || 0)*1000),
      slot: infer.inferMotionSlot(x.group, x.file), direction: infer.parseMotionName(x.file).direction}));
    const expressionIndex = {}, motionIndex = {};
    for (const e of expressions) if(e.slot) (expressionIndex[e.slot] ??= []).push(e.name);
    for (const x of motions) if(x.slot) (motionIndex[x.slot] ??= []).push({group:x.group,index:x.index});
    const manifest = {expressions, motions, index: {expression:expressionIndex,motion:motionIndex,
      idle: motions.filter(x => x.slot === 'idle').sort((a,b) => a.durationMs-b.durationMs)}};
    return {model:m.model, reviewed:false,
      expression_candidates:Object.fromEntries(Object.entries(expressionIndex).map(([k,v]) => [k,v.length])),
      motion_candidates:Object.fromEntries(Object.entries(motionIndex).map(([k,v]) => [k,v.length])),
      unmapped_expressions:expressions.filter(x => !x.slot).map(x => x.name),
      unmapped_motions:motions.filter(x => !x.slot).map(x => `${x.group}#${x.index}`),
      selected_greet:resolver.resolveMotion(manifest,{motion_slot:'greet'}),
      selected_comfort:resolver.resolveMotion(manifest,{motion_slot:'comfort'}),
      idle_at_limit_4500:resolver.idleCandidates(manifest,4500)};
  });
}
const prelude = `
let releaseDecode, decodeStartedResolve, finishSource;
let lateStarts = 0, stopped = false;
const decodeStarted = new Promise(r => { decodeStartedResolve = r; });
const decoded = new Promise(r => { releaseDecode = r; });
let audioCtx = {
 destination: {}, decodeAudioData: () => { decodeStartedResolve(); return decoded; },
 createBufferSource: () => ({connect(){}, stop(){}, start(){ if(stopped) lateStarts++; finishSource = this; }})
};
async function ensureAudioCtxRunning(){}
function stopMouthLoop(){} function driveMouth(){} function maybeEmitPlaybackEnd(){}
let mouthVolumes=[], mouthSliceMs=20, mouthStart=0, currentSource=null, currentPlayResolve=null;
let ws=null, playQueue=[], engineSentAll=false, pendingSegments=1, playedThisTurn=true;
`;
const experiment = `
(async () => {
 const pending = playOne('AA==', 24000, 20, [0]);
 await decodeStarted;
 stopPlayback(); stopped = true;
 releaseDecode({});
 for(let i=0; i<6; i++) await Promise.resolve();
 const observedLateStarts = lateStarts;
 if(finishSource?.onended) finishSource.onended();
 await pending;
 return {lateStarts: observedLateStarts, expectedSafeLateStarts: 0,
   observedCurrentDefect: observedLateStarts > 0};
})()
`;
(async () => {
  const context = { Uint8Array, atob: s => Buffer.from(s, 'base64').toString('binary'),
    performance: require('node:perf_hooks').performance };
  const result = await vm.runInNewContext(prelude + compiled + experiment, context, { timeout: 2000 });
  const output = { kind: 'production_function_characterization_with_fake_decode_NOT_browser_E2E',
    source: sourcePath, extracted: extracted.map(({name,line}) => ({name,line})), result,
    limits: 'Isolated functions; surrounding Vue/WS/device lifecycle not executed. Known failure is recorded, not fixed.' };
  const out = path.join(root, 'docs/plan/G0-baseline-artifacts/frontend-race.json');
  fs.mkdirSync(path.dirname(out), { recursive: true });
  fs.writeFileSync(out, JSON.stringify(output, null, 2));
  fs.writeFileSync(path.join(path.dirname(out), 'live2d-slot-candidates.json'), JSON.stringify({
    kind:'actual_TS_inference_and_resolver_candidate_results_NOT_visual_review', models:slotInventory()
  }, null, 2));
  console.log(JSON.stringify(output));
})().catch(error => { console.error(error); process.exitCode = 1; });
