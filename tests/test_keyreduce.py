# -*- coding: utf-8 -*-
"""keyreduce 单元测试 / 基准（不依赖 Blender）。

用法：
    python tests/test_keyreduce.py            # 跑测试
    python tests/test_keyreduce.py --bench    # 顺带跑真实数据基准
"""
import json
import os
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "runtime"))
import keyreduce  # noqa: E402

FAILS = []


def check(name, cond, detail=""):
    if cond:
        print("  PASS  %s %s" % (name, detail))
    else:
        print("  FAIL  %s %s" % (name, detail))
        FAILS.append(name)


def rot_x(deg):
    a = np.radians(deg)
    c, s = np.cos(a), np.sin(a)
    return np.array([[1, 0, 0], [0, c, -s], [0, s, c]], dtype=float)


def rot_z(deg):
    a = np.radians(deg)
    c, s = np.cos(a), np.sin(a)
    return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]], dtype=float)


def make_gm(n_frames, bone_motion, n_bones=3):
    """构造合成 GM：每骨绕 Z 轴按 bone_motion(bone_index, frame) 旋转。"""
    gm = {}
    for f in range(n_frames):
        d = {}
        for b in range(n_bones):
            R = rot_z(bone_motion(b, f)) @ rot_x(5.0 * b)
            M = np.eye(4)
            M[:3, :3] = R
            M[:3, 3] = [10.0 * b + 0.1 * f, 20.0, 30.0]
            d["bone_%02d" % b] = M.tolist()
        gm[str(f)] = d
    return gm


def test_static():
    print("\n[1] 静止数据：应当只剩首尾两帧")
    gm = make_gm(50, lambda b, f: 10.0 * b, n_bones=3)
    keys, st = keyreduce.reduce_keys(gm, key_angle_deg=1.5, key_pos_cm=1.0)
    check("静态 -> 2 关键帧", len(keys) == 2, "got %d" % len(keys))
    check("静态 -> 无超标", st["violations"] == 0, "violations=%d" % st["violations"])


def test_linear():
    print("\n[2] 匀速变化：插值应当几乎无损")
    gm = make_gm(120, lambda b, f: 0.5 * f, n_bones=3)
    keys, st = keyreduce.reduce_keys(gm, key_angle_deg=1.5, key_pos_cm=1.0)
    check("匀速 -> 少量关键帧", len(keys) <= 12, "keys=%d" % len(keys))
    check("匀速 -> 无超标", st["violations"] == 0, "violations=%d" % st["violations"])


def test_spike():
    print("\n[3] 中间有突变：突变帧必须被保留")
    def motion(b, f):
        return 0.2 * f + (60.0 if (b == 0 and f == 60) else 0.0)
    gm = make_gm(121, motion, n_bones=3)
    keys, st = keyreduce.reduce_keys(gm, key_angle_deg=1.5, key_pos_cm=1.0)
    check("突变帧被选中", 60 in keys, "keys 附近=%s" % [k for k in keys if 55 <= k <= 65])


def test_thresholds():
    print("\n[4] 阈值语义：角度与位置分开判定")
    # 用非线性运动（正弦），线性运动插值本就无损，测不出阈值差异
    gm = make_gm(160, lambda b, f: 40.0 * np.sin(f / 7.0) + 1.5 * b, n_bones=3)
    loose, st_l = keyreduce.reduce_keys(gm, key_angle_deg=5.0, key_pos_cm=5.0)
    tight, st_t = keyreduce.reduce_keys(gm, key_angle_deg=0.3, key_pos_cm=0.1)
    check("松阈值帧更少", len(loose) < len(tight), "loose=%d tight=%d" % (len(loose), len(tight)))
    # 注意：min_gap=2 是硬约束，阈值再紧也未必能压到 0 超标，
    # 所以这里比"最大误差"而不是"超标数"
    check("紧阈值最大误差更小", st_t["max_angle_err"] <= st_l["max_angle_err"],
          "loose=%.2f tight=%.2f" % (st_l["max_angle_err"], st_t["max_angle_err"]))
    check("紧阈值超标数有界", st_t["violations_angle"] < 160,
          "violations_angle=%d（受 min_gap 限制）" % st_t["violations_angle"])


def test_min_gap():
    print("\n[5] min_gap 不再让算法提前退出")
    gm = make_gm(200, lambda b, f: 3.0 * np.sin(f / 6.0), n_bones=3)
    keys, st = keyreduce.reduce_keys(gm, key_angle_deg=0.2, key_pos_cm=0.2, min_gap=5)
    gaps = np.diff(keys)
    check("min_gap 被遵守", (gaps >= 5).all(), "min gap=%d" % int(gaps.min()))
    check("没有因为 min_gap 停摆", len(keys) > 10, "keys=%d" % len(keys))


def test_reconstruction():
    print("\n[6] reconstruction_error 与 reduce 统计自洽")
    gm = make_gm(100, lambda b, f: 2.0 * np.sin(f / 9.0), n_bones=4)
    keys, st = keyreduce.reduce_keys(gm, key_angle_deg=1.0, key_pos_cm=1.0)
    err = keyreduce.reconstruction_error(gm, keys)
    check("平均误差一致", abs(err["mean_deg"] - st["mean_angle_err"]) < 0.05,
          "reduce=%.3f recon=%.3f" % (st["mean_angle_err"], err["mean_deg"]))
    check("最大误差一致", abs(err["max_deg"] - st["max_angle_err"]) < 0.05,
          "reduce=%.3f recon=%.3f" % (st["max_angle_err"], err["max_deg"]))


def bench(path):
    print("\n[BENCH] %s" % path)
    if not os.path.exists(path):
        print("  跳过：文件不存在")
        return
    t0 = time.time()
    gm = json.load(open(path, encoding="utf-8"))
    gm = {k: v for k, v in gm.items() if v}
    t1 = time.time()
    print("  载入 %.1f s，帧 %d" % (t1 - t0, len(gm)))
    t2 = time.time()
    keys, st = keyreduce.reduce_keys(gm, key_angle_deg=1.5, key_pos_cm=1.0)
    t3 = time.time()
    print("  reduce_keys %.2f s -> %d keys (%.1f%%)" % (t3 - t2, len(keys), st["ratio_pct"]))
    print("  统计:", {k: st[k] for k in ("mean_angle_err", "max_angle_err",
                                        "mean_pos_err_cm", "max_pos_err_cm",
                                        "violations_angle", "violations_pos")})
    t4 = time.time()
    err = keyreduce.reconstruction_error(gm, keys)
    print("  reconstruction_error %.2f s ->" % (time.time() - t4), err)


if __name__ == "__main__":
    test_static()
    test_linear()
    test_spike()
    test_thresholds()
    test_min_gap()
    test_reconstruction()

    if "--bench" in sys.argv:
        i = sys.argv.index("--bench")
        gm_path = sys.argv[i + 1] if i + 1 < len(sys.argv) else None
        if not gm_path:
            print("\n用法: python tests/test_keyreduce.py --bench <你的全局矩阵 GM.json>")
        else:
            bench(gm_path)

    print("\n" + "=" * 60)
    if FAILS:
        print("FAILED: %d 项 -> %s" % (len(FAILS), ", ".join(FAILS)))
        sys.exit(1)
    print("ALL TESTS PASSED")
