# -*- coding: utf-8 -*-
"""verify_rebuild.py —— 把「0.000 cm」变成可执行断言。

用法（必须用 Blender 的 Python 跑，因为要导入 bpy）：

    blender -b --factory-startup --python verify/verify_rebuild.py -- \
        --casc  "D:\\path\\scene.casc" \
        --gm    "D:\\path\\scene_gm.json" \
        --model-fbx "D:\\path\\Model.fbx" \
        --tolerance-cm 0.01

退出码：
    0 = 全部断言通过
    1 = 有断言失败
    2 = 参数/环境问题

输出：一段 markdown 表格（可直接贴进 README 或 CI 的 job summary），
并在最后打印 `VERIFY_JSON {...}` 供脚本解析。
"""
import json
import os
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN_ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(PLUGIN_ROOT, "runtime"))

import run_pipeline  # noqa: E402  （导入时解析 -- 之后的参数）
import casc_core     # noqa: E402


def arg(name, default=None):
    return run_pipeline.ARGS.get(name, default)


def main():
    casc = arg("casc")
    gm = arg("gm")
    model_fbx = arg("model_fbx")
    tol = float(arg("tolerance_cm", 0.01))
    lod = arg("lod", "0")

    missing = [k for k, v in (("casc", casc), ("gm", gm), ("model-fbx", model_fbx)) if not v]
    if missing:
        print("缺少参数：%s" % ", ".join("--" + m for m in missing))
        return 2
    for k, v in (("casc", casc), ("gm", gm), ("model-fbx", model_fbx)):
        if not os.path.exists(v):
            print("文件不存在：--%s %s" % (k, v))
            return 2

    try:
        r = run_pipeline.rebuild(casc, gm, model_fbx, lod)
    except Exception:
        print(traceback.format_exc())
        return 2

    checks = []

    def add(name, value, ok, detail=""):
        checks.append({"name": name, "value": value, "ok": bool(ok), "detail": detail})

    rest = r.get("rest_err_cm")
    bpos = r.get("bone_pos_err_cm")
    bmax = r.get("bone_pos_err_max_cm")
    matched = r.get("matched_bones")
    joints = r.get("joints")
    missing_bones = r.get("missing_bones") or []

    add("rest 姿势误差 vs 绑定姿势 (cm)", rest, rest is not None and rest <= tol,
        "<= %.4f" % tol)
    add("骨骼位置误差 平均 (cm)", bpos, bpos is not None and bpos <= tol, "<= %.4f" % tol)
    add("骨骼位置误差 最大 (cm)", bmax, bmax is not None and bmax <= tol, "<= %.4f" % tol)
    add("骨骼名匹配", "%s/%s" % (matched, joints), bool(joints) and not missing_bones,
        "缺 %d 根" % len(missing_bones))
    add("帧数", r.get("frames"), bool(r.get("frames")))

    failed = [c for c in checks if not c["ok"]]

    print("\n### verify_rebuild 结果\n")
    print("| 断言 | 实测 | 结果 | 判据 |")
    print("|---|---|---|---|")
    for c in checks:
        print("| %s | %s | %s | %s |" % (
            c["name"], c["value"], "✅" if c["ok"] else "❌", c["detail"]))
    if missing_bones:
        print("\n缺失骨骼（前 10）：`%s`" % json.dumps(missing_bones[:10], ensure_ascii=False))
    print("\n**结论：%s**（%d/%d 通过，容差 %.4f cm）\n" % (
        "PASS" if not failed else "FAIL", len(checks) - len(failed), len(checks), tol))

    print("VERIFY_JSON " + json.dumps({
        "ok": not failed,
        "checks": checks,
        "tolerance_cm": tol,
        "result": {k: r.get(k) for k in
                   ("frames", "joints", "lod", "rest_err_cm", "bone_pos_err_cm",
                    "bone_pos_err_max_cm", "matched_bones", "missing_bones")},
    }, ensure_ascii=False))
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
