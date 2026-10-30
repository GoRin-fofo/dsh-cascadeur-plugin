/**
 * tests/test_packaging.mjs —— 打包 / 分发一致性检查（不依赖 DSH、Blender、网络）
 *
 * 目标：让「npm 上装到的东西」和「仓库里测过的东西」是同一个东西。
 * 运行：node tests/test_packaging.mjs   （npm test:pack）
 */
import { existsSync, readFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const ROOT = path.join(path.dirname(fileURLToPath(import.meta.url)), '..')
const read = (p) => readFileSync(path.join(ROOT, p), 'utf8')

let fails = 0
function check(name, cond, detail = '') {
  if (cond) {
    console.log(`  PASS  ${name} ${detail}`)
  } else {
    console.log(`  FAIL  ${name} ${detail}`)
    fails++
  }
}

const pkg = JSON.parse(read('package.json'))
const name = pkg.name
const version = pkg.version

console.log('\n[1] 包名与版本')
check('包名是无 scope 的 dsh-cascadeur-plugin', name === 'dsh-cascadeur-plugin', `= ${name}`)
check('版本形如 x.y.z', /^\d+\.\d+\.\d+$/.test(version), `= ${version}`)
check('未标记为 private', pkg.private === false)
check('publishConfig 声明公开', pkg.publishConfig?.access === 'public', `= ${JSON.stringify(pkg.publishConfig)}`)

console.log('\n[2] engines：node 与 dsh 都要有')
check('engines.node 存在', !!pkg.engines?.node, `= ${pkg.engines?.node}`)
check('engines.dsh 存在', !!pkg.engines?.dsh, `= ${pkg.engines?.dsh}`)

console.log('\n[3] DSH 插件元数据')
check('dsh.bundle.patch 指向 cordis.patch.yml', pkg.dsh?.bundle?.patch === './cordis.patch.yml')
check('cordis.patch.yml 存在', existsSync(path.join(ROOT, 'cordis.patch.yml')))
check('patch 里的 name 与新包名一致', read('cordis.patch.yml').includes(`name: '${name}'`))
check('lib/index.js export 的 name 与新包名一致',
  new RegExp(`export const name = '${name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}'`).test(read('lib/index.js')))
check('peerDependencies 声明了 @deepseek-ai/dsh-tools',
  !!pkg.peerDependencies?.['@deepseek-ai/dsh-tools'], `= ${pkg.peerDependencies?.['@deepseek-ai/dsh-tools']}`)
check('cordis 是可选的 peer', pkg.peerDependenciesMeta?.cordis?.optional === true)

console.log('\n[4] 入口可解析')
check('main 指向 lib/index.js', pkg.main === './lib/index.js')
check('main 文件存在', existsSync(path.join(ROOT, 'lib', 'index.js')))
check("exports['.'].default 存在", typeof pkg.exports?.['.']?.default === 'string')
check('exports 覆盖 ./package.json', typeof pkg.exports?.['./package.json'] === 'string')

console.log('\n[5] files 清单：该发的发，不该发的不发')
const files = pkg.files || []
for (const need of ['lib', 'runtime', 'cascadeur_autostart', 'cordis.patch.yml',
  'README.md', 'README.zh-CN.md', 'CHANGELOG.md', 'LICENSE']) {
  check(`files 含 ${need}`, files.includes(need))
}
for (const avoid of ['docs', 'tests', 'verify', '.github']) {
  check(`files 不含 ${avoid}`, !files.includes(avoid), '（演示/测试不随 npm 包分发）')
}
check('LICENSE 文件存在', existsSync(path.join(ROOT, 'LICENSE')))
check('license 字段为 MIT', pkg.license === 'MIT', `= ${pkg.license}`)

console.log('\n[6] README 的安装命令与演示链接')
for (const f of ['README.md', 'README.zh-CN.md']) {
  const t = read(f)
  check(`${f} 含 npm 安装命令`, t.includes('dsh plugin --profile web add dsh-cascadeur-plugin'))
  check(`${f} 的演示图用绝对地址（npm 也能显示）`,
    t.includes('raw.githubusercontent.com/GoRin-fofo/dsh-cascadeur-plugin/main/docs/demo.gif'))
}

console.log('\n[7] 版本三方一致（package.json = CHANGELOG 顶部 = 待打 tag）')
const changelog = read('CHANGELOG.md')
check('CHANGELOG 有当前版本小节', changelog.includes(`## v${version}`), `期望 v${version}`)
const m = changelog.match(/^## v(\d+\.\d+\.\d+)/m)
check('CHANGELOG 顶部版本等于 package.json', m && m[1] === version, `= ${m ? m[1] : 'none'}`)

console.log('\n[8] 安装脚本与新包名一致（旧包名做迁移清理）')
const install = read('install.ps1')
check("install.ps1 使用新包名", install.includes(`$pkgName = '${name}'`))
check('install.ps1 会清理旧包名', install.includes('@dsh-external/dsh-cascadeur-plugin'))
const uninstall = read('uninstall.ps1')
check('uninstall.ps1 同时清理新旧包名',
  uninstall.includes(`$pkgName = '${name}'`) && uninstall.includes('@dsh-external/dsh-cascadeur-plugin'))

console.log('\n' + '='.repeat(60))
if (fails) {
  console.log(`FAILED: ${fails} 项`)
  process.exit(1)
}
console.log('ALL PACKAGING CHECKS PASSED')
