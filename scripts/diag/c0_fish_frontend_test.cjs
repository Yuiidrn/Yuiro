/* 执行真实 Vue 函数：迟到试听结果隔离、停播与 Blob 生命周期。 */
const fs = require('node:fs')
const vm = require('node:vm')
const assert = require('node:assert/strict')
const source = fs.readFileSync('shell/src/renderer/src/dev/components/ProviderCard.vue', 'utf8')
function extract(name) {
  const marker = name === 'run' ? 'async function run(): Promise<void> {' : 'function reset(): void {'
  const start = source.indexOf(marker)
  assert(start >= 0)
  let depth = 1, end = start + marker.length
  while (depth && end < source.length) {
    if (source[end] === '{') depth++
    if (source[end] === '}') depth--
    end++
  }
  return source.slice(start, end).replace(': Promise<void>', '').replace(': void', '')
}
async function main() {
  let resolve, paused = 0, revoked = []
  const ctx = vm.createContext({
    result: { value: null }, error: { value: '' }, testing: { value: false },
    player: { value: { pause: () => paused++ } }, audioSrc: { value: '' }, epoch: 0,
    props: { provider: 'tts' }, isTts: { value: true }, lang: { value: 'ja' },
    api: { testProvider: () => new Promise(r => { resolve = r }) },
    URL: { createObjectURL: () => 'blob:test', revokeObjectURL: u => revoked.push(u) },
    Blob, Uint8Array, atob, Error,
  })
  vm.runInContext(extract('reset') + '\n' + extract('run'), ctx)
  const pending = ctx.run()
  ctx.reset() // 切换角色时真实 watch 调用的函数
  resolve({ status: 'ok', audio_base64: 'AA==' })
  await pending
  assert.equal(ctx.result.value, null)
  assert.equal(ctx.audioSrc.value, '')
  ctx.api.testProvider = async () => ({ status: 'ok', audio_base64: 'AA==' })
  await ctx.run()
  assert.equal(ctx.audioSrc.value, 'blob:test')
  const before = paused
  ctx.reset()
  assert.equal(paused, before + 1)
  assert.deepEqual(revoked, ['blob:test'])
  assert.equal(ctx.result.value, null)
  const csp = fs.readFileSync('shell/src/renderer/dev.html', 'utf8')
  assert(csp.includes("media-src 'self' blob:"))
  console.log('Fish frontend: 3 checks passed (late response; stop/revoke; scoped media CSP).')
}
main().catch(e => { console.error(e); process.exitCode = 1 })
