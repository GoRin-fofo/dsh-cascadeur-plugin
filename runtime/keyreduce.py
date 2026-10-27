# -*- coding: utf-8 -*-
"""keyreduce —— 误差驱动的关键帧简化。

思路：从 [首帧, 末帧] 开始，反复找"用相邻关键帧插值后误差最大"的帧加入关键帧，
直到所有帧的插值误差都低于阈值。比"只看速度"稳，慢速细节段落也能保住。

输入是 Cascadeur 的 Global Matrix 数据：{frame: {bone: 4x4 list}}
"""
import numpy as np


def mat_to_quat(m):
    """单个 3x3 旋转矩阵 -> 四元数 (w,x,y,z)。"""
    t = m[0, 0] + m[1, 1] + m[2, 2]
    if t > 0:
        s = np.sqrt(t + 1.0) * 2
        return np.array([0.25 * s, (m[2, 1] - m[1, 2]) / s,
                         (m[0, 2] - m[2, 0]) / s, (m[1, 0] - m[0, 1]) / s])
    if m[0, 0] > m[1, 1] and m[0, 0] > m[2, 2]:
        s = np.sqrt(1.0 + m[0, 0] - m[1, 1] - m[2, 2]) * 2
        return np.array([(m[2, 1] - m[1, 2]) / s, 0.25 * s,
                         (m[0, 1] + m[1, 0]) / s, (m[0, 2] + m[2, 0]) / s])
    if m[1, 1] > m[2, 2]:
        s = np.sqrt(1.0 + m[1, 1] - m[0, 0] - m[2, 2]) * 2
        return np.array([(m[0, 2] - m[2, 0]) / s, (m[0, 1] + m[1, 0]) / s,
                         0.25 * s, (m[1, 2] + m[2, 1]) / s])
    s = np.sqrt(1.0 + m[2, 2] - m[0, 0] - m[1, 1]) * 2
    return np.array([(m[1, 0] - m[0, 1]) / s, (m[0, 2] + m[2, 0]) / s,
                     (m[1, 2] + m[2, 1]) / s, 0.25 * s])


def slerp(a, b, t):
    """批量 slerp：a/b 可为 (4,) 或 (B,4)；t 为标量。"""
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


def angle_deg(q1, q2):
    d = min(1.0, abs(float(np.dot(q1, q2))))
    return float(np.degrees(2 * np.arccos(d)))


def build_arrays(gm):
    """把 {frame: {bone: 4x4}} 摊平成 numpy 数组。"""
    frames = sorted(int(f) for f, v in gm.items() if v)
    if not frames:
        raise ValueError("没有可用的帧数据")
    f0, f1 = frames[0], frames[-1]
    frames = [f for f in range(f0, f1 + 1) if str(f) in gm and gm[str(f)]]
    bones = sorted(gm[str(frames[0])].keys())
    n, b = len(frames), len(bones)
    quats = np.zeros((n, b, 4))
    pos = np.zeros((n, b, 3))
    for i, f in enumerate(frames):
        d = gm[str(f)]
        for j, bn in enumerate(bones):
            M = np.array(d[bn], dtype=np.float64)
            quats[i, j] = mat_to_quat(M[:3, :3])
            pos[i, j] = M[:3, 3]
        # 保持四元数同半球
        for j in range(b):
            if i > 0 and np.dot(quats[i, j], quats[i - 1, j]) < 0:
                quats[i, j] = -quats[i, j]
    return frames, bones, quats, pos


def reduce_keys(gm, threshold_deg=1.5, pos_weight=0.5, min_gap=2, max_keys=100000):
    """返回 (关键帧列表, 统计信息)。"""
    frames, bones, quats, pos = build_arrays(gm)
    N = len(frames)
    if N <= 2:
        return frames, {"dense": N, "keys": N, "note": "too few frames"}

    keys = {0, N - 1}
    it = 0
    last_worst = 0.0
    while it < max_keys:
        it += 1
        ks = sorted(keys)
        worst_err, worst_i = -1.0, -1
        for i in range(N):
            if i in keys:
                continue
            lo = max(k for k in ks if k <= i)
            hi = min(k for k in ks if k >= i)
            if hi == lo:
                continue
            t = (i - lo) / (hi - lo)
            qi = slerp(quats[lo], quats[hi], t)
            pi = pos[lo] * (1 - t) + pos[hi] * t
            ang = np.mean([angle_deg(qi[j], quats[i][j]) for j in range(len(bones))])
            dp = float(np.mean(np.linalg.norm(pi - pos[i], axis=-1)))
            err = ang + pos_weight * dp
            if err > worst_err:
                worst_err, worst_i = err, i
        last_worst = worst_err
        if worst_i < 0 or worst_err <= threshold_deg:
            break
        lo = max(k for k in keys if k <= worst_i)
        hi = min(k for k in keys if k >= worst_i)
        if worst_i - lo < min_gap and hi - worst_i < min_gap:
            break
        keys.add(worst_i)

    idx = sorted(keys)
    out_frames = [frames[i] for i in idx]
    stats = {
        "dense": N,
        "keys": len(out_frames),
        "ratio_pct": round(100.0 * len(out_frames) / N, 1),
        "threshold_deg": threshold_deg,
        "pos_weight": pos_weight,
        "last_worst_err": round(float(last_worst), 2),
        "first_frame": frames[0],
        "last_frame": frames[-1],
        "bones": len(bones),
    }
    return out_frames, stats


def reconstruction_error(gm, key_frames):
    """在给定关键帧下，逐帧重算插值误差（度）。"""
    frames, bones, quats, pos = build_arrays(gm)
    kf = [f for f in key_frames if f in frames]
    if len(kf) < 2:
        return {"mean": 0.0, "max": 0.0}
    ki = 0
    errs = []
    for i, f in enumerate(frames):
        while ki + 1 < len(kf) and kf[ki + 1] <= f:
            ki += 1
        lo = kf[ki]
        hi = kf[ki + 1] if ki + 1 < len(kf) else kf[-1]
        if lo == hi or f == lo:
            continue
        li, hi_i = frames.index(lo), frames.index(hi)
        t = (i - li) / (hi_i - li)
        qi = slerp(quats[li], quats[hi_i], t)
        e = [angle_deg(qi[j], quats[i][j]) for j in range(len(bones))]
        errs.append(float(np.mean(e)))
    if not errs:
        return {"mean": 0.0, "max": 0.0}
    return {"mean": round(float(np.mean(errs)), 2), "max": round(float(np.max(errs)), 2)}
