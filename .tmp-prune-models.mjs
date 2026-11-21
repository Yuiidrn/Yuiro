// 一次性脚本（第二批）：
//   1) 清理 model_dict.json：只留 feiniu / hiyori / mao_pro，default 改为 hiyori；
//   2) 把肥牛的 3 个额外动作（micoff / micon / singing）迁移到 hiyori，
//      迁移时**剥掉 mic1 曲线**（Hiyori 没有这个参数，留着就是死数据）。
import fs from 'node:fs'
import path from 'node:path'

const ROOT = 'shell/src/renderer/public/live2d'
const KEEP_KEYS = ['feiniu', 'hiyori', 'mao_pro']

// ── 1) 清理注册表 ──
const dictPath = path.join(ROOT, 'model_dict.json')
const dict = JSON.parse(fs.readFileSync(dictPath, 'utf8'))
for (const key of Object.keys(dict.models)) {
  if (!KEEP_KEYS.includes(key)) {
    delete dict.models[key]
    console.log(`注册表移除 ${key}`)
  }
}
dict.default = 'hiyori'
fs.writeFileSync(dictPath, `${JSON.stringify(dict, null, 2)}\n`, 'utf8')
console.log(`注册表剩余: ${Object.keys(dict.models).join(', ')}（default=${dict.default}）`)

// ── 2) 迁移额外动作到 hiyori ──
const MIGRATE = ['micoff', 'micon', 'singing']
const srcDir = path.join(ROOT, '肥牛', 'motions')
const dstDir = path.join(ROOT, 'hiyori', 'motions')
for (const name of MIGRATE) {
  const j = JSON.parse(fs.readFileSync(path.join(srcDir, `${name}.motion3.json`), 'utf8'))
  const before = j.Curves.length
  j.Curves = j.Curves.filter((c) => c.Id !== 'mic1')
  fs.writeFileSync(path.join(dstDir, `${name}.motion3.json`), `${JSON.stringify(j, null, 2)}\n`, 'utf8')
  console.log(`迁移 ${name}.motion3.json（${before} → ${j.Curves.length} 条曲线，剥掉 mic1，时长 ${j.Meta.Duration}s）`)
}

// ── 3) 在 Hiyori.model3.json 登记 Extra 组 ──
const mp = path.join(ROOT, 'hiyori', 'Hiyori.model3.json')
const model3 = JSON.parse(fs.readFileSync(mp, 'utf8'))
model3.FileReferences.Motions.Extra = MIGRATE.map((n) => ({
  File: `motions/${n}.motion3.json`,
  FadeInTime: 0.5,
  FadeOutTime: 0.5,
}))
fs.writeFileSync(mp, `${JSON.stringify(model3, null, 2)}\n`, 'utf8')
console.log('Hiyori 动作组:', Object.entries(model3.FileReferences.Motions).map(([k, v]) => `${k}(${v.length})`).join(' '))

// ── 4) 校验 Hiyori 全引用 ──
const base = path.dirname(mp)
const refs = model3.FileReferences
const miss = []
for (const f of [refs.Moc, refs.Physics, refs.Pose, refs.DisplayInfo, refs.UserData].filter(Boolean)) {
  if (!fs.existsSync(path.join(base, f))) miss.push(f)
}
for (const t of refs.Textures) if (!fs.existsSync(path.join(base, t))) miss.push(t)
for (const g of Object.keys(refs.Motions)) for (const it of refs.Motions[g]) if (!fs.existsSync(path.join(base, it.File))) miss.push(it.File)
for (const it of refs.Expressions) if (!fs.existsSync(path.join(base, it.File))) miss.push(it.File)
console.log('Hiyori 引用缺失:', miss.length ? miss : '无 ✓')

// ── 5) 顺带报一下 肥牛 与 mao_pro 的注册表路径是否还在 ──
for (const [k, v] of Object.entries(dict.models)) {
  const rel = String(v.modelPath || '').replace('/live2d/', '')
  console.log(`${k.padEnd(8)} ${fs.existsSync(path.join(ROOT, rel)) ? '✓' : '✗ 路径不存在'} ${v.modelPath}`)
}
