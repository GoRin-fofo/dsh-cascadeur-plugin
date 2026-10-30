# -*- coding: utf-8 -*-
"""keyreduce —— 误差驱动的关键帧简化（向量化实现）。

算法：
    从 [首帧, 末帧] 开始，反复找"用相邻关键帧插值后误差最大"的帧加入关键帧，
    直到所有帧的角度误差 <= key_angle_deg 且位置误差 <= key_pos_cm。

与 v0.3.0 的差异（按 review 修）：
    * 角度阈值与位置阈值**分开**（原来把厘米塞进角度）
    * min_gap 冲突时**跳过该候选**继续找次优，而不是直接 break
    * 全流程向量化（612 帧 88 骨：51 s -> <2 s）
    * 统计里给出**真实超标帧数**，而不是只报 last_worst_err

输入是 Cascadeur 的 Global Matrix 数据：{frame: {bone: 4x4 list}}
"""
import numpy as np

DEFAULT_ANGLE_DEG = 1.5
DEFAULT_POS_CM = 1.0


# ────────────────────────── 数学工具 ──────────────────────────
def mats_to_quats(R):
    """(...,3,3) 旋转矩阵 -> (...,4) 四元数（w,x,y,z），向量化。"""
    R = np.asarray(R, dtype=np.float64)
    m00, m01, m02 = R[..., 0, 0], R[..., 0, 1], R[..., 0, 2]
    m10, m11, m12 = R[..., 1, 0], R[..., 1, 1], R[..., 1, 2]
    m20, m21, m22 = R[..., 2, 0], R[..., 2, 1], R[..., 2, 2]
    tr = m00 + m11 + m22

    q = np.zeros(R.shape[:-2] + (4,), dtype=np.float64)
    eps = 1e-12

    # case 0: tr > 0
    c0 = tr > 0
    if np.any(c0):
        s = np.sqrt(np.maximum(tr, 0.0) + 1.0) * 2.0
        q[..., 0] = np.where(c0, 0.25 * s, q[..., 0])
        q[..., 1] = np.where(c0, (m21 - m12) / np.maximum(s, eps), q[..., 1])
        q[..., 2] = np.where(c0, (m02 - m20) / np.maximum(s, eps), q[..., 2])
        q[..., 3] = np.where(c0, (m10 - m01) / np.maximum(s, eps), q[..., 3])

    # case 1: m00 最大
    c1 = (~c0) & (m00 > m11) & (m00 > m22)
    if np.any(c1):
        s = np.sqrt(np.maximum(1.0 + m00 - m11 - m22, eps)) * 2.0
        q[..., 0] = np.where(c1, (m21 - m12) / s, q[..., 0])
        q[..., 1] = np.where(c1, 0.25 * s, q[..., 1])
        q[..., 2] = np.where(c1, (m01 + m10) / s, q[..., 2])
        q[..., 3] = np.where(c1, (m02 + m20) / s, q[..., 3])

    # case 2: m11 最大
    c2 = (~c0) & (~c1) & (m11 > m22)
    if np.any(c2):
        s = np.sqrt(np.maximum(1.0 + m11 - m00 - m22, eps)) * 2.0
        q[..., 0] = np.where(c2, (m02 - m20) / s, q[..., 0])
        q[..., 1] = np.where(c2, (m01 + m10) / s, q[..., 1])
        q[..., 2] = np.where(c2, 0.25 * s, q[..., 2])
        q[..., 3] = np.where(c2, (m12 + m21) / s, q[..., 3])

    # case 3: m22 最大
    c3 = (~c0) & (~c1) & (~c2)
    if np.any(c3):
        s = np.sqrt(np.maximum(1.0 + m22 - m00 - m11, eps)) * 2.0
        q[..., 0] = np.where(c3, (m10 - m01) / s, q[..., 0])
        q[..., 1] = np.where(c3, (m02 + m20) / s, q[..., 1])
        q[..., 2] = np.where(c3, (m12 + m21) / s, q[..., 2])
        q[..., 3] = np.where(c3, 0.25 * s, q[..., 3])

    n = np.linalg.norm(q, axis=-1, keepdims=True)
    return q / np.where(n < eps, 1.0, n)


def slerp(a, b, t):
    """slerp，支持 (...,4) 广播。t 需与 a[...,0:1] 可广播。"""
    a = np.asarray(a, dtype=np.float64)
    b = np.asarray(b, dtype=np.float64)
    d = np.sum(a * b, axis=-1, keepdims=True)
    b = np.where(d < 0, -b, b)
    d = np.clip(np.abs(d), -1.0, 1.0)
    th = np.arccos(d)
    sin_th = np.sin(th)
    small = sin_th < 1e-6
    safe = np.where(small, 1.0, sin_th)
    wa = np.where(small, 1.0 - t, np.sin((1.0 - t) * th) / safe)
    wb = np.where(small, t, np.sin(t * th) / safe)
    q = wa * a + wb * b
    n = np.linalg.norm(q, axis=-1, keepdims=True)
    return q / np.where(n < 1e-12, 1.0, n)


def quat_angles_deg(qa, qb):
    """批量四元数夹角（度），沿最后一维。"""
    d = np.clip(np.abs(np.sum(qa * qb, axis=-1)), -1.0, 1.0)
    return np.degrees(2.0 * np.arccos(d))


# ────────────────────────── 数据准备 ──────────────────────────
def build_arrays(gm):
    """把 {frame: {bone: 4x4}} 摊平成 (N,B,4) 四元数 + (N,B,3) 位置。"""
    frames = sorted(int(f) for f, v in gm.items() if v)
    if not frames:
        raise ValueError("没有可用的帧数据")
    f0, f1 = frames[0], frames[-1]
    frames = [f for f in range(f0, f1 + 1) if str(f) in gm and gm[str(f)]]
    if not frames:
        raise ValueError("帧数据不连续")
    bones = sorted(gm[str(frames[0])].keys())
    n, b = len(frames), len(bones)

    M = np.zeros((n, b, 4, 4), dtype=np.float64)
    for i, f in enumerate(frames):
        d = gm[str(f)]
        for j, bn in enumerate(bones):
            M[i, j] = np.asarray(d[bn], dtype=np.float64)

    quats = mats_to_quats(M[:, :, :3, :3])
    pos = M[:, :, :3, 3].copy()

    # 统一半球，避免插值走远路
    for i in range(1, n):
        flip = np.sum(quats[i] * quats[i - 1], axis=-1) < 0
        if np.any(flip):
            quats[i, flip] = -quats[i, flip]
    return frames, bones, quats, pos


def _segment_errors(quats, pos, lo, hi):
    """区间 (lo, hi) 内每帧的插值误差。返回 (idx, angle_err, pos_err)。"""
    idx = np.arange(lo + 1, hi)
    if idx.size == 0:
        return idx, np.zeros(0), np.zeros(0)
    t = (idx - lo) / float(hi - lo)
    qi = slerp(quats[lo][None, :, :], quats[hi][None, :, :], t[:, None, None])
    ang = quat_angles_deg(qi, quats[idx]).mean(axis=1)
    pi = pos[lo][None, :, :] * (1.0 - t)[:, None, None] + pos[hi][None, :, :] * t[:, None, None]
    dp = np.linalg.norm(pi - pos[idx], axis=-1).mean(axis=1)
    return idx, ang, dp


# ────────────────────────── 主算法 ──────────────────────────
def reduce_keys(gm, key_angle_deg=DEFAULT_ANGLE_DEG, key_pos_cm=DEFAULT_POS_CM,
                pos_weight=0.5, min_gap=1, max_keys=20000):
    """返回 (关键帧列表, 统计信息)。

    key_angle_deg : 允许的最大平均角度误差（度）
    key_pos_cm    : 允许的最大平均位置误差（厘米）
    pos_weight    : 选帧时"位置误差"折算成角度的权重（只影响优先级，不影响判定）
    min_gap       : 两个关键帧之间的最小间隔（帧）
    """
    frames, bones, quats, pos = build_arrays(gm)
    N = len(frames)
    if N <= 2:
        return list(frames), {"dense": N, "keys": N, "note": "too few frames"}

    is_key = np.zeros(N, dtype=bool)
    is_key[0] = is_key[-1] = True

    err_ang = np.full(N, np.inf)
    err_pos = np.full(N, np.inf)
    dist_to_key = np.full(N, N, dtype=np.int64)
    dist_to_key[0] = 0
    dist_to_key[-1] = 0
    _mid = np.arange(1, N - 1)
    dist_to_key[1:-1] = np.minimum(_mid, (N - 1) - _mid)

    def refresh(a, b):
        idx, ang, dp = _segment_errors(quats, pos, a, b)
        if idx.size:
            err_ang[idx] = ang
            err_pos[idx] = dp

    refresh(0, N - 1)

    while int(is_key.sum()) < max_keys:
        banned = is_key | (dist_to_key < min_gap)
        if banned.all():
            break
        # 归一化违约度：>1 表示该帧超过阈值（角度或位置）
        viol = np.maximum(err_ang / max(key_angle_deg, 1e-9),
                          err_pos / max(key_pos_cm, 1e-9))
        # 只在违约帧里挑；违约度相同则挑加权分大的
        tie = err_ang + pos_weight * err_pos
        score = np.where(banned, -np.inf, viol + 1e-6 * tie)
        i = int(np.argmax(score))
        if not np.isfinite(score[i]) or viol[i] <= 1.0:
            break

        is_key[i] = True
        # 更新最近关键帧距离
        dist_to_key = np.minimum(dist_to_key, np.abs(np.arange(N) - i))
        # 只刷新被切开的两段
        ks = np.flatnonzero(is_key)
        p = int(np.searchsorted(ks, i))
        lo = int(ks[p - 1]) if p - 1 >= 0 else 0
        hi = int(ks[p + 1]) if p + 1 < len(ks) else N - 1
        refresh(lo, i)
        refresh(i, hi)
        # 关键帧自身误差为 0
        err_ang[[0, N - 1]] = 0.0
        err_pos[[0, N - 1]] = 0.0

    idx = np.flatnonzero(is_key)
    out_frames = [frames[i] for i in idx]
    non_key = ~is_key
    v_ang = int(np.sum(err_ang[non_key] > key_angle_deg))
    v_pos = int(np.sum(err_pos[non_key] > key_pos_cm))
    stats = {
        "dense": N,
        "keys": len(out_frames),
        "ratio_pct": round(100.0 * len(out_frames) / N, 1),
        "key_angle_deg": key_angle_deg,
        "key_pos_cm": key_pos_cm,
        "min_gap": min_gap,
        "violations_angle": v_ang,
        "violations_pos": v_pos,
        "violations": int(np.sum(non_key & ((err_ang > key_angle_deg) | (err_pos > key_pos_cm)))),
        "mean_angle_err": round(float(np.mean(err_ang[non_key])) if non_key.any() else 0.0, 3),
        "max_angle_err": round(float(np.max(err_ang[non_key])) if non_key.any() else 0.0, 3),
        "mean_pos_err_cm": round(float(np.mean(err_pos[non_key])) if non_key.any() else 0.0, 3),
        "max_pos_err_cm": round(float(np.max(err_pos[non_key])) if non_key.any() else 0.0, 3),
        "first_frame": frames[0],
        "last_frame": frames[-1],
        "bones": len(bones),
    }
    return out_frames, stats


def reconstruction_error(gm, key_frames):
    """给定关键帧，重算逐帧插值误差（角度/位置），并统计超标。"""
    frames, bones, quats, pos = build_arrays(gm)
    pos_of = {f: i for i, f in enumerate(frames)}
    kf = sorted(pos_of[f] for f in key_frames if f in pos_of)
    if len(kf) < 2:
        return {"mean_deg": 0.0, "max_deg": 0.0, "mean_cm": 0.0, "max_cm": 0.0}
    ang_all, pos_all = [], []
    for a, b in zip(kf, kf[1:]):
        _, ang, dp = _segment_errors(quats, pos, a, b)
        if ang.size:
            ang_all.append(ang)
            pos_all.append(dp)
    if not ang_all:
        return {"mean_deg": 0.0, "max_deg": 0.0, "mean_cm": 0.0, "max_cm": 0.0}
    ang = np.concatenate(ang_all)
    dp = np.concatenate(pos_all)
    return {
        "mean_deg": round(float(ang.mean()), 3),
        "max_deg": round(float(ang.max()), 3),
        "mean_cm": round(float(dp.mean()), 3),
        "max_cm": round(float(dp.max()), 3),
        "frames": int(ang.size),
    }


# ────────────────────────── 单帧跳变检测/修复 ──────────────────────────
def detect_spikes(gm, factor=4.0, min_step_cm=5.0, max_run=8, window=15):
    """找出「跳变段」（Mocap 追踪失败）影响的帧号。

    做法：先算逐帧位移 step[k] = 帧 k -> k+1 的平均骨位移；
    再和局部滚动中位数比，连续偏大的短区间（<= max_run 个帧间）判为跳变段。
    真实的快速动作会持续更久，不会命中。
    """
    frames, bones, quats, pos = build_arrays(gm)
    N = len(frames)
    if N < 6 or N - 1 < 3:
        return []
    step = np.linalg.norm(np.diff(pos, axis=0), axis=-1).mean(axis=1)  # (N-1,)
    n = len(step)
    baseline = np.empty(n)
    half = max(1, window // 2)
    for k in range(n):
        lo, hi = max(0, k - half), min(n, k + half + 1)
        neigh = np.concatenate([step[lo:k], step[k + 1:hi]])
        baseline[k] = float(np.median(neigh)) if neigh.size else float(step[k])
    ratio = step / np.maximum(baseline, 1.0)
    bad = (ratio > factor) & (step > min_step_cm)

    out = []
    k = 0
    while k < n:
        if not bad[k]:
            k += 1
            continue
        b = k
        while k < n and bad[k]:
            k += 1
        e = k - 1
        if e - b + 1 > max_run:      # 太长，视为真实快速动作
            continue
        # 坏的是帧间 b..e，即帧 b+1..e+1 的姿势受到了影响
        out.extend(range(b + 1, e + 2))
    return [frames[i] for i in out if 0 < i < N - 1]


def repair_spikes(gm, spike_frames):
    """把跳变帧替换成前后帧的插值。返回 (新 gm, 修复帧数)。"""
    if not spike_frames:
        return gm, 0
    frames, bones, quats, pos = build_arrays(gm)
    idx_of = {f: i for i, f in enumerate(frames)}
    fixed = 0
    for f in spike_frames:
        i = idx_of.get(f)
        if i is None or i <= 0 or i >= len(frames) - 1:
            continue
        quats[i] = slerp(quats[i - 1], quats[i + 1], 0.5)
        pos[i] = 0.5 * (pos[i - 1] + pos[i + 1])
        fixed += 1

    out = {}
    for i, f in enumerate(frames):
        d = {}
        for j, bn in enumerate(bones):
            w, x, y, z = quats[i, j]
            M = np.eye(4)
            M[:3, :3] = np.array([
                [1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)],
                [2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)],
                [2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)],
            ])
            M[:3, 3] = pos[i, j]
            d[bn] = M.tolist()
        out[str(f)] = d
    return out, fixed
