/**
 * @dsh-external/dsh-cascadeur-plugin —— 阶段 1（host 侧）
 *
 * 把 Cascadeur 的 .casc 动画搬进 Blender / UE5。
 * 原理：通过 Cascadeur 的 MCP 脚本服务器（127.0.0.1:8765）读 Global Matrix，
 *       在 Blender 里用原版 FBX 重建姿势，再导出 FBX。
 *       （逐顶点误差 0.000 cm，详见 README）
 *
 * 工具：
 *   casc_status   环境自检（Cascadeur 端口 / Blender / 设置）
 *   casc_inspect  列出 .casc 里的角色、骨骼、帧范围、LOD
 *   casc_dump     只导出动画数据（Global Matrix → JSON）
 *   casc2blend    一条龙：读 → 重建 → .blend
 *   casc2fbx      一条龙：读 → 重建 → FBX
 *   casc_verify   验证重建结果（骨骼位置 vs Cascadeur 数据）
 *   casc_config   读写默认设置（持久化，后续导出默认用它）
 */
import { execFile } from 'node:child_process'
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import { defineTool } from '@deepseek-ai/dsh-tools'

const PLUGIN_VERSION = '0.2.0'
const HERE = path.dirname(fileURLToPath(import.meta.url))
const RUNTIME = path.join(HERE, '..', 'runtime')
const PIPELINE = path.join(RUNTIME, 'run_pipeline.py')
const SETTINGS_FILE = path.join(os.homedir(), '.dsh', 'cascadeur-settings.json')
const CASC_URL = 'http://127.0.0.1:8765'

export const name = '@dsh-external/dsh-cascadeur-plugin'
export const inject = ['tools']

// ───────────────────────────── 设置 ─────────────────────────────
const DEFAULT_SETTINGS = {
  blenderExe: '',
  // 原版模型 FBX：必须是当初导入 Cascadeur 用的那个（不要用改过的）
  // 首次使用请通过 casc_config({set:{modelFbx:"..."}}) 配置
  modelFbx: '',
  lod: '0',
  // 空 = 默认输出到 <casc 所在目录>/casc_out
  outDir: '',
  frames: 'auto',
  character: 'auto',
  autoVerify: true,
}

function readSettings() {
  try {
    const raw = JSON.parse(readFileSync(SETTINGS_FILE, 'utf8'))
    return { ...DEFAULT_SETTINGS, ...raw }
  } catch {
    return { ...DEFAULT_SETTINGS }
  }
}

function writeSettings(patch) {
  const cur = readSettings()
  const next = { ...cur, ...(patch || {}) }
  mkdirSync(path.dirname(SETTINGS_FILE), { recursive: true })
  writeFileSync(SETTINGS_FILE, JSON.stringify(next, null, 2), 'utf8')
  return next
}

// ───────────────────────────── Blender 路径 ─────────────────────────────
function resolveBlender() {
  const s = readSettings()
  const candidates = [
    s.blenderExe,
    process.env.DSH_BLENDER_EXE,
    (() => {
      // 复用 dsh-blender-plugin 的配置（如果同机装了它）
      const cands = [
        process.env.DSH_BLENDER_CONFIG,
        path.join(os.homedir(), '.dsh', 'dsh-blender.config.json'),
        path.join(path.sep, 'dsh-plugins', 'dsh-blender-plugin', 'dsh-blender.config.json'),
      ].filter(Boolean)
      for (const p of cands) {
        try {
          const cfg = JSON.parse(readFileSync(p, 'utf8'))
          if (cfg.blenderExe) return cfg.blenderExe
        } catch { /* ignore */ }
      }
      return ''
    })(),
    'C:\\Program Files\\Blender Foundation\\Blender 5.4\\blender.exe',
    'C:\\Program Files\\Blender Foundation\\Blender 5.3\\blender.exe',
  ]
  for (const c of candidates) {
    if (c && existsSync(c)) return c
  }
  return null
}

// ───────────────────────────── Cascadeur 健康检查 ─────────────────────────────
async function cascHealth(timeoutMs = 1500) {
  const ctrl = new AbortController()
  const t = setTimeout(() => ctrl.abort(), timeoutMs)
  try {
    const r = await fetch(CASC_URL + '/health', { signal: ctrl.signal })
    const text = await r.text()
    return { ok: r.ok, status: r.status, body: text.slice(0, 300) }
  } catch (e) {
    return { ok: false, error: String((e && e.message) || e) }
  } finally {
    clearTimeout(t)
  }
}

// ───────────────────────────── 跑 Blender ─────────────────────────────
function runBlender(args, timeoutMs = 15 * 60 * 1000) {
  return new Promise((resolve) => {
    const exe = resolveBlender()
    if (!exe) {
      resolve({ ok: false, error: '找不到 blender.exe。请设置 casc_config({blenderExe:"..."}) 或环境变量 DSH_BLENDER_EXE' })
      return
    }
    const argv = ['-b', '--factory-startup', '--python', PIPELINE, '--', ...args]
    const t0 = Date.now()
    execFile(exe, argv, { timeout: timeoutMs, maxBuffer: 64 * 1024 * 1024 }, (err, stdout, stderr) => {
      const ms = Date.now() - t0
      const lines = String(stdout || '').split(/\r?\n/)
      let result = null
      for (let i = lines.length - 1; i >= 0; i--) {
        const line = lines[i]
        if (line && line.startsWith('RESULT_JSON ')) {
          try { result = JSON.parse(line.slice('RESULT_JSON '.length)) } catch { /* ignore */ }
          break
        }
      }
      if (!result) {
        resolve({
          ok: false, ms,
          error: (err && err.message) || 'Blender 没有返回结果',
          stderr: String(stderr || '').slice(-1500),
          stdout: String(stdout || '').slice(-1500),
        })
        return
      }
      result.ms = ms
      result.blender = exe
      resolve(result)
    })
  })
}

// ───────────────────────────── 工具辅助 ─────────────────────────────
function out(obj) {
  return JSON.stringify(obj, null, 2)
}

function needCasc(args) {
  const p = args && (args.casc_path || args.casc)
  if (!p) throw new Error('缺少参数 casc_path（.casc 文件路径）')
  if (!existsSync(p)) throw new Error('文件不存在：' + p)
  return path.resolve(p)
}

function defaultOut(casc, kind) {
  const s = readSettings()
  const dir = s.outDir || path.join(path.dirname(casc), 'casc_out')
  mkdirSync(dir, { recursive: true })
  const base = path.basename(casc, path.extname(casc))
  return path.join(dir, base + (kind === 'fbx' ? '.fbx' : '.blend'))
}

function pickSettings(args) {
  const s = readSettings()
  return {
    modelFbx: (args && args.model_fbx) || s.modelFbx,
    lod: (args && args.lod) || s.lod,
    frames: (args && args.frames) || s.frames,
  }
}

const NO_SERVER_HINT =
  '连不上 Cascadeur 的脚本服务器（127.0.0.1:8765）。\n' +
  '处理办法（二选一）：\n' +
  '  A) 在 Cascadeur 里点：Scripts 菜单 → MCP → Start script server\n' +
  '  B) 装自动启动模块（推荐，装一次永久生效）：\n' +
  '     把 cascadeur_autostart\\autostart.py 复制到\n' +
  '     <Cascadeur安装目录>\\resources\\scripts\\python\\scripts\\mcp\\\n' +
  '     之后每次启动 Cascadeur 会自动开 8765（约 60 秒后就绪）\n' +
  '  诊断日志：%TEMP%\\dsh_mcp_autostart.log'

async function ensureServer() {
  const h = await cascHealth()
  if (!h.ok) {
    const err = new Error(NO_SERVER_HINT)
    err.cascadeurDown = true
    throw err
  }
  return h
}

// ───────────────────────────── 工具定义 ─────────────────────────────
const tools = [
  {
    name: 'casc_status',
    description: '' + PLUGIN_VERSION + ' 环境自检：Cascadeur 脚本服务器是否可达、Blender 路径、当前默认设置。',
    parameters: {},
    isConcurrencySafe: () => true,
    timeoutMs: 15000,
    async execute() {
      const s = readSettings()
      const h = await cascHealth()
      const b = resolveBlender()
      return out({
        plugin: { name, version: PLUGIN_VERSION },
        cascadeur: h.ok ? { reachable: true, url: CASC_URL, health: h.body } : { reachable: false, url: CASC_URL, hint: NO_SERVER_HINT },
        blender: b || null,
        runtime: existsSync(PIPELINE) ? PIPELINE : null,
        settingsFile: SETTINGS_FILE,
        settings: s,
      })
    },
  },
  {
    name: 'casc_inspect',
    description: '' + PLUGIN_VERSION + ' 只读解析 .casc：列出角色/网格、骨骼数、帧范围、LOD、动画分层。不启动 Cascadeur。',
    parameters: {
      casc_path: { type: 'string', description: '.casc 文件路径' },
    },
    isConcurrencySafe: () => true,
    timeoutMs: 120000,
    async execute(args) {
      const casc = needCasc(args)
      const r = await runBlender(['--mode', 'inspect', '--casc', casc])
      return out(r)
    },
  },
  {
    name: 'casc_dump',
    description: '' + PLUGIN_VERSION + ' 只导出动画数据：让 Cascadeur 打开场景并逐帧读 Global Matrix，存成 JSON。需要脚本服务器已启动。',
    parameters: {
      casc_path: { type: 'string', description: '.casc 文件路径' },
      frames: { type: 'string', description: '帧范围，如 "0-10" 或 "0,5,10"；默认用场景的时间轴范围' },
      gm_out: { type: 'string', description: '输出 JSON 路径（可选）' },
    },
    timeoutMs: 20 * 60 * 1000,
    async execute(args) {
      const casc = needCasc(args)
      await ensureServer()
      const a = ['--mode', 'dump', '--casc', casc]
      if (args && args.frames) a.push('--frames', String(args.frames))
      if (args && args.gm_out) a.push('--gm', String(args.gm_out))
      return out(await runBlender(a, 20 * 60 * 1000))
    },
  },
  {
    name: 'casc2blend',
    description: '' + PLUGIN_VERSION + ' 一条龙：读 Cascadeur 动画 → 在 Blender 里重建 → 存成 .blend。默认参数来自 casc_config。',
    parameters: {
      casc_path: { type: 'string', description: '.casc 文件路径' },
      blend_out: { type: 'string', description: '输出 .blend 路径（可选，默认放进设置里的 outDir）' },
      frames: { type: 'string', description: '帧范围（可选，覆盖设置）' },
      lod: { type: 'string', description: '网格 LOD："0"（默认）或 "all" 或 "0,2"' },
      model_fbx: { type: 'string', description: '原版模型 FBX（可选，覆盖设置）' },
    },
    timeoutMs: 30 * 60 * 1000,
    async execute(args) {
      const casc = needCasc(args)
      await ensureServer()
      const s = pickSettings(args)
      if (!s.modelFbx) throw new Error('没有配置原版模型 FBX。请先 casc_config({modelFbx:"D:\\\\path\\\\model.fbx"})')
      if (!existsSync(s.modelFbx)) throw new Error('原版模型 FBX 不存在：' + s.modelFbx)
      const blend = (args && args.blend_out) || defaultOut(casc, 'blend')
      const a = ['--mode', 'blend', '--casc', casc, '--model-fbx', s.modelFbx,
        '--lod', s.lod, '--blend-out', blend]
      if (s.frames) a.push('--frames', s.frames)
      return out(await runBlender(a, 30 * 60 * 1000))
    },
  },
  {
    name: 'casc2fbx',
    description: '' + PLUGIN_VERSION + ' 一条龙：读 Cascadeur 动画 → 重建 → 导出 FBX（可直接进 UE5）。默认参数来自 casc_config。',
    parameters: {
      casc_path: { type: 'string', description: '.casc 文件路径' },
      fbx_out: { type: 'string', description: '输出 .fbx 路径（可选，默认放进设置里的 outDir）' },
      frames: { type: 'string', description: '帧范围（可选，覆盖设置）' },
      lod: { type: 'string', description: '网格 LOD："0"（默认）或 "all" 或 "0,2"' },
      model_fbx: { type: 'string', description: '原版模型 FBX（可选，覆盖设置）' },
    },
    timeoutMs: 30 * 60 * 1000,
    async execute(args) {
      const casc = needCasc(args)
      await ensureServer()
      const s = pickSettings(args)
      if (!s.modelFbx) throw new Error('没有配置原版模型 FBX。请先 casc_config({modelFbx:"D:\\\\path\\\\model.fbx"})')
      if (!existsSync(s.modelFbx)) throw new Error('原版模型 FBX 不存在：' + s.modelFbx)
      const fbx = (args && args.fbx_out) || defaultOut(casc, 'fbx')
      const a = ['--mode', 'export', '--casc', casc, '--model-fbx', s.modelFbx,
        '--lod', s.lod, '--fbx-out', fbx]
      if (s.frames) a.push('--frames', s.frames)
      return out(await runBlender(a, 30 * 60 * 1000))
    },
  },
  {
    name: 'casc_verify',
    description: '' + PLUGIN_VERSION + ' 验证重建：把骨骼位置和 Cascadeur 的数据逐骨比对（正常应 < 0.01 cm）。',
    parameters: {
      casc_path: { type: 'string', description: '.casc 文件路径' },
      lod: { type: 'string', description: '网格 LOD（可选）' },
    },
    timeoutMs: 30 * 60 * 1000,
    async execute(args) {
      const casc = needCasc(args)
      const s = pickSettings(args)
      if (!s.modelFbx || !existsSync(s.modelFbx)) throw new Error('原版模型 FBX 未配置或不存在')
      const a = ['--mode', 'verify', '--casc', casc, '--model-fbx', s.modelFbx, '--lod', s.lod]
      return out(await runBlender(a, 30 * 60 * 1000))
    },
  },
  {
    name: 'casc_config',
    description: '' + PLUGIN_VERSION + ' 读写插件的默认设置（持久化到 ~/.dsh/cascadeur-settings.json）。'
      + '不传 set 就返回当前设置；传 set 就合并保存 —— 之后 casc2fbx/casc2blend 默认都按它来。',
    parameters: {
      set: {
        type: 'object',
        description: '要修改的设置项，如 {"lod":"all","outDir":"D:\\\\out"}；可用键：blenderExe, modelFbx, lod, outDir, frames, character, autoVerify',
      },
      reset: { type: 'boolean', description: 'true = 恢复出厂默认' },
    },
    isConcurrencySafe: () => true,
    timeoutMs: 10000,
    async execute(args) {
      if (args && args.reset) {
        writeFileSync(SETTINGS_FILE, JSON.stringify(DEFAULT_SETTINGS, null, 2), 'utf8')
        return out({ ok: true, reset: true, settings: readSettings(), file: SETTINGS_FILE })
      }
      if (args && args.set) {
        const next = writeSettings(args.set)
        return out({ ok: true, updated: Object.keys(args.set), settings: next, file: SETTINGS_FILE })
      }
      return out({ ok: true, settings: readSettings(), file: SETTINGS_FILE, defaults: DEFAULT_SETTINGS })
    },
  },
]

export function apply(ctx) {
  for (const spec of tools) {
    ctx.effect(() => ctx.tools.register(defineTool({
      ...spec,
      description: spec.description,
      output: { schema: { type: 'string' }, render: (_a, v) => [{ type: 'text', text: String(v) }] },
    })), `${name}: ${spec.name}`)
  }
}
