/**
 * lib/core.js —— 纯逻辑（不依赖 DSH / 不碰 fs），供 index.js 与测试共用。
 *
 * 这里只放"可以脱离 DSH 单测"的东西：默认设置、参数归一化、CLI 参数拼装。
 */

/** 默认设置（casc_config 可持久化覆盖） */
export const DEFAULT_SETTINGS = {
  blenderExe: '',
  // 原版模型 FBX：必须是当初导入 Cascadeur 用的那个（不要用改过的）
  modelFbx: '',
  lod: '0',
  // 空 = 默认输出到 <casc 所在目录>/casc_out
  outDir: '',
  frames: 'auto',
  // 关键帧简化：true = 只写"误差驱动选出"的关键帧并设 Bezier
  reduceKeys: false,
  // 允许的最大平均角度误差（度）
  keyAngleDeg: 2.0,
  // 允许的最大平均位置误差（厘米）
  keyPosCm: 2.0,
  // 两个关键帧的最小间隔（1 = 允许相邻帧；越大帧越少但精度越差）
  keyMinGap: 1,
  // 自动修复 Mocap 的单帧跳变（追踪失败），修复帧号会写进回执
  despike: true,
  // 导出 FPS（Mocap 视频通常是 25）
  fps: 30,
}

export function normalizeSettings(raw) {
  const s = { ...DEFAULT_SETTINGS, ...(raw || {}) }
  const num = (v, d) => {
    const n = Number(v)
    return Number.isFinite(n) ? n : d
  }
  return {
    ...s,
    keyAngleDeg: Math.max(0.01, num(s.keyAngleDeg, DEFAULT_SETTINGS.keyAngleDeg)),
    keyPosCm: Math.max(0.001, num(s.keyPosCm, DEFAULT_SETTINGS.keyPosCm)),
    keyMinGap: Math.max(1, Math.trunc(num(s.keyMinGap, DEFAULT_SETTINGS.keyMinGap))),
    fps: Math.max(1, num(s.fps, DEFAULT_SETTINGS.fps)),
    despike: s.despike !== false,
    reduceKeys: !!s.reduceKeys,
  }
}

/** 把参数里的覆盖项并进设置（工具入参 > 已存设置 > 默认） */
export function mergeArgs(settings, args) {
  const a = args || {}
  const out = { ...normalizeSettings(settings) }
  if (a.model_fbx) out.modelFbx = a.model_fbx
  if (a.lod) out.lod = a.lod
  if (a.frames) out.frames = a.frames
  if (a.reduce_keys !== undefined) out.reduceKeys = !!a.reduce_keys
  if (a.key_angle !== undefined) out.keyAngleDeg = Number(a.key_angle)
  if (a.key_pos !== undefined) out.keyPosCm = Number(a.key_pos)
  if (a.min_gap !== undefined) out.keyMinGap = Math.trunc(Number(a.min_gap))
  if (a.despike !== undefined) out.despike = !!a.despike
  return normalizeSettings(out)
}

/** 简化相关的 blender CLI 参数（未开启简化时返回空数组） */
export function reduceArgs(s) {
  if (!s || !s.reduceKeys) return []
  return [
    '--reduce-keys', 'true',
    '--key-angle', String(s.keyAngleDeg),
    '--key-pos', String(s.keyPosCm),
    '--key-min-gap', String(s.keyMinGap),
    '--despike', s.despike ? 'true' : 'false',
  ]
}

/** 解析 LOD 规格：'0' | 'all' | '0,2' → { all, lods:number[] } */
export function parseLodSpec(spec) {
  const s = String(spec ?? '0').trim().toLowerCase()
  if (s === 'all') return { all: true, lods: [] }
  const lods = s.split(',').map((x) => Number.parseInt(x.trim(), 10)).filter((n) => Number.isFinite(n))
  return { all: false, lods: lods.length ? lods : [0] }
}

/** 从回执里提取“人话摘要”，用于工具返回与 verify 报告 */
export function summarize(result) {
  const r = result || {}
  const lines = []
  lines.push(`ok=${r.ok} mode=${r.mode || '?'} frames=${r.frames ?? '?'} joints=${r.joints ?? '?'}`)
  if (r.matched_bones !== undefined) {
    lines.push(`骨骼匹配 ${r.matched_bones}/${r.joints}` +
      (r.missing_bones && r.missing_bones.length ? `（缺 ${r.missing_bones.length}: ${r.missing_bones.slice(0, 5).join(',')}）` : ''))
  }
  if (r.rest_err_cm !== undefined) lines.push(`rest_err=${fmtCm(r.rest_err_cm)}`)
  if (r.bone_pos_err_cm !== undefined) {
    lines.push(`bone_pos_err=${fmtCm(r.bone_pos_err_cm)} (max ${fmtCm(r.bone_pos_err_max_cm)})`)
  }
  if (r.despike && Array.isArray(r.despike.fixed_frames) && r.despike.fixed_frames.length) {
    lines.push(`despike: 修复 ${r.despike.fixed_frames.length} 帧 ${JSON.stringify(r.despike.fixed_frames)}`)
  }
  if (r.reduce && !r.reduce.error) {
    const d = r.reduce
    lines.push(`keyreduce: ${d.dense}→${d.keys} 帧 (${d.ratio_pct}%) ` +
      `max∠${d.max_angle_err}° max_pos ${d.max_pos_err_cm}cm 超标 ${d.violations}`)
  }
  return lines.join('\n')
}

function fmtCm(v) {
  if (v === null || v === undefined) return 'n/a'
  const n = Number(v)
  if (!Number.isFinite(n)) return String(v)
  if (n === 0) return '0 cm'
  return n < 0.01 ? `${(n * 10000).toFixed(1)}e-4 cm` : `${n.toFixed(4)} cm`
}
