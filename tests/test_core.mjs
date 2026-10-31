/**
 * tests/test_core.mjs —— Node 侧纯逻辑单测（不依赖 DSH、不需要 Blender）
 *
 * 运行：node tests/test_core.mjs
 */
import { readFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import {
  DEFAULT_SETTINGS,
  mergeArgs,
  normalizeSettings,
  parseLodSpec,
  reduceArgs,
  summarize,
} from '../lib/core.js'

const HERE = path.dirname(fileURLToPath(import.meta.url))
const ROOT = path.join(HERE, '..')

let fails = 0
function check(name, cond, detail = '') {
  if (cond) {
    console.log(`  PASS  ${name} ${detail}`)
  } else {
    console.log(`  FAIL  ${name} ${detail}`)
    fails++
  }
}

console.log('\n[1] 默认设置完整性')
const required = ['modelFbx', 'lod', 'outDir', 'frames', 'reduceKeys', 'keyAngleDeg',
  'keyPosCm', 'keyMinGap', 'despike', 'fps']
for (const k of required) {
  check(`DEFAULT_SETTINGS.${k} 存在`, k in DEFAULT_SETTINGS, `= ${JSON.stringify(DEFAULT_SETTINGS[k])}`)
}
check('没有遗留的未实现项 character/autoVerify',
  !('character' in DEFAULT_SETTINGS) && !('autoVerify' in DEFAULT_SETTINGS))

console.log('\n[2] normalizeSettings 兜底与钳制')
const dirty = { keyAngleDeg: 'abc', keyPosCm: -5, keyMinGap: 0, fps: 0, despike: false, reduceKeys: 1 }
const n = normalizeSettings(dirty)
check('非法角度回落默认', n.keyAngleDeg === DEFAULT_SETTINGS.keyAngleDeg, `=${n.keyAngleDeg}`)
check('负位置钳到正数', n.keyPosCm > 0, `=${n.keyPosCm}`)
check('minGap 至少 1', n.keyMinGap >= 1, `=${n.keyMinGap}`)
check('fps 至少 1', n.fps >= 1, `=${n.fps}`)
check('despike=false 保留', n.despike === false)
check('reduceKeys 转布尔', n.reduceKeys === true)

console.log('\n[3] mergeArgs 优先级：工具入参 > 已存设置 > 默认')
const stored = normalizeSettings({ modelFbx: 'stored.fbx', keyAngleDeg: 3.0, reduceKeys: false })
const m = mergeArgs(stored, { key_angle: 0.5, reduce_keys: true, lod: 'all' })
check('入参覆盖已存', m.keyAngleDeg === 0.5 && m.reduceKeys === true && m.lod === 'all')
check('未给的沿用已存', m.modelFbx === 'stored.fbx')
const m2 = mergeArgs(stored, {})
check('空入参保持已存', m2.keyAngleDeg === 3.0 && m2.reduceKeys === false)

console.log('\n[4] reduceArgs')
check('未开启简化返回空', reduceArgs({ reduceKeys: false }).length === 0)
const ra = reduceArgs({ reduceKeys: true, keyAngleDeg: 2, keyPosCm: 1.5, keyMinGap: 2, despike: true })
check('包含 --reduce-keys true', ra.includes('--reduce-keys') && ra[ra.indexOf('--reduce-keys') + 1] === 'true')
check('包含阈值参数', ra.includes('--key-angle') && ra.includes('--key-pos') && ra.includes('--key-min-gap'))
check('despike 透传', ra.includes('--despike') && ra[ra.indexOf('--despike') + 1] === 'true')
const ra2 = reduceArgs({ reduceKeys: true, keyAngleDeg: 2, keyPosCm: 2, keyMinGap: 1, despike: false })
check('despike=false 透传', ra2[ra2.indexOf('--despike') + 1] === 'false')

console.log('\n[5] parseLodSpec')
check("'0' -> [0]", JSON.stringify(parseLodSpec('0')) === JSON.stringify({ all: false, lods: [0] }))
check("'all' -> all", parseLodSpec('all').all === true)
check("'0,2' -> [0,2]", JSON.stringify(parseLodSpec('0,2').lods) === JSON.stringify([0, 2]))
check('空值回落 [0]', JSON.stringify(parseLodSpec('').lods) === JSON.stringify([0]))

console.log('\n[6] summarize 人话摘要')
const sm = summarize({
  ok: true, mode: 'export', frames: 612, joints: 88, matched_bones: 88, missing_bones: [],
  rest_err_cm: 0.0000991, bone_pos_err_cm: 0.000112, bone_pos_err_max_cm: 0.000367,
  despike: { fixed_frames: [257, 597] },
  reduce: { dense: 612, keys: 184, ratio_pct: 30.1, max_angle_err: 1.97, max_pos_err_cm: 1.97, violations: 0 },
})
check('摘要含骨骼匹配', sm.includes('骨骼匹配 88/88'), sm.split('\n')[1])
check('摘要含 keyreduce', sm.includes('612→184'), sm.split('\n').find((l) => l.includes('keyreduce')) || '')
check('摘要含 despike', sm.includes('修复 2 帧'))

console.log('\n[7] 版本单一来源')
const pkg = JSON.parse(readFileSync(path.join(ROOT, 'package.json'), 'utf8'))
const indexSrc = readFileSync(path.join(ROOT, 'lib', 'index.js'), 'utf8')
check('index.js 不再硬编码版本号', !/const PLUGIN_VERSION = '\d/.test(indexSrc))
check('index.js 从 package.json 读取版本', indexSrc.includes("new URL('../package.json'"))
check('package.json 版本形如 x.y.z', /^\d+\.\d+\.\d+$/.test(pkg.version), `= ${pkg.version}`)
const changelog = readFileSync(path.join(ROOT, 'CHANGELOG.md'), 'utf8')
check('CHANGELOG 顶部与 package.json 版本一致',
  changelog.includes(`## v${pkg.version}`), `期望 v${pkg.version}`)

console.log('\n[8] package.json 打包完整性')
const files = pkg.files || []
for (const need of ['lib', 'runtime', 'cascadeur_autostart', 'README.md', 'CHANGELOG.md', 'LICENSE']) {
  check(`files 含 ${need}`, files.includes(need))
}
check('有 repository 字段', !!pkg.repository?.url)

console.log('\n[9] 工具 JSON schema 与宿主兼容')
// DSH 宿主要求 object 类型的 schema 显式声明 additionalProperties，
// 否则 defineTool 注册时抛 JsonSchemaError，插件在桌面端显示「异常」。
const objectSchemas = (indexSrc.match(/type:\s*'object'/g) || []).length
const declaredAdditional = (indexSrc.match(/additionalProperties\s*:/g) || []).length
check('每个 object schema 都声明了 additionalProperties',
  objectSchemas === declaredAdditional, `object=${objectSchemas} additionalProperties=${declaredAdditional}`)
check('casc_config.set 是开放对象',
  /set:\s*\{[^}]*type:\s*'object'[^}]*additionalProperties:\s*true/.test(indexSrc))

console.log('\n' + '='.repeat(60))
if (fails) {
  console.log(`FAILED: ${fails} 项`)
  process.exit(1)
}
console.log('ALL JS TESTS PASSED')
