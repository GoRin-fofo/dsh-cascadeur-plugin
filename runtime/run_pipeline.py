# -*- coding: utf-8 -*-
"""run_pipeline —— 插件在 Blender 无头进程里执行的入口。

用法（由 DSH 插件调用，不直接交互）：
  blender -b --factory-startup --python run_pipeline.py -- --mode inspect --casc X.casc
  blender -b --factory-startup --python run_pipeline.py -- --mode dump   --casc X.casc --gm X_gm.json
  blender -b --factory-startup --python run_pipeline.py -- --mode blend  --casc X.casc --blend-out Y.blend
  blender -b --factory-startup --python run_pipeline.py -- --mode export --casc X.casc --fbx-out Y.fbx
  blender -b --factory-startup --python run_pipeline.py -- --mode verify --casc X.casc

输出：最后一行 `RESULT_JSON {...}`（JS 侧解析）。
"""
import json
import os
import sys
import traceback

import numpy as np

import bpy


# ─────────────────────────── 参数 ───────────────────────────
def parse_args():
    argv = sys.argv
    if "--" in argv:
        argv = argv[argv.index("--") + 1:]
    else:
        argv = []
    out = {}
    i = 0
    while i < len(argv):
        k = argv[i]
        if k.startswith("--"):
            key = k[2:].replace("-", "_")
            val = argv[i + 1] if i + 1 < len(argv) and not argv[i + 1].startswith("--") else "true"
            out[key] = val
            i += 2
        else:
            i += 1
    return out


ARGS = parse_args()
HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import casc_core  # noqa: E402


def emit(**kw):
    print("RESULT_JSON " + json.dumps(kw, ensure_ascii=False))


# ─────────────────────────── 模式：inspect ───────────────────────────
def mode_inspect():
    casc = ARGS["casc"]
    js = casc_core.load_scene_json(casc)
    meshes = casc_core.parse_meshes(js)
    model = casc_core.load_model_pose(js)
    tl = casc_core.load_json_entry(casc, "scene/timeline/timeline.json", {}) or {}
    tl_data = tl.get("Data", {}) if isinstance(tl, dict) else {}
    settings = casc_core.load_json_entry(casc, "scene/scene_settings.json", {}) or {}
    fps = (settings.get("Data", {}) or {}).get("FPS")
    layers = [{"name": l.get("name"), "visible": l.get("visible"),
               "objects": len(l.get("object_ids") or [])} for l in js.get("layers", [])]
    characters = []
    for m in meshes:
        characters.append({
            "name": m["object"],
            "verts": m["verts"],
            "skinned_bones": m["skinned_bones"],
        })
    emit(ok=True, mode="inspect", casc=casc,
         frames={"start": tl_data.get("StartFrame", 0),
                 "end": tl_data.get("EndFrame", 100),
                 "current": tl_data.get("CurrentFrame", 0),
                 "fps": fps},
         characters=characters,
         joints=len(model),
         joint_names=sorted(model.keys())[:12],
         joint_names_truncated=max(0, len(model) - 12),
         layers=layers,
         objects_total=len(js.get("objects", [])))


# ─────────────────────────── HTTP → Cascadeur ───────────────────────────
def casc_post(code, timeout=600):
    import urllib.request
    body = json.dumps({"code": code}).encode("utf-8")
    req = urllib.request.Request("http://127.0.0.1:8765/run", data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def casc_run(code, timeout=600):
    data = casc_post(code, timeout)
    lines = []
    for m in data.get("messages", []):
        lines.append(m.get("text", "") if isinstance(m, dict) else str(m))
    if data.get("error"):
        lines.append("ERROR: " + str(data["error"]))
    return "\n".join(lines)


def fetch_gm(casc_path, frames):
    """通过 Cascadeur 的 MCP 脚本服务器读 Global Matrix。"""
    casc_abs = os.path.abspath(casc_path).replace("\\", "/")
    # 1) 加载场景
    load_out = casc_run("import csc\n"
                        "mp = csc.app.get_application()\n"
                        "print(mp.get_data_source_manager().load_scene(%r))\n" % casc_abs)
    if "rror" in load_out or "False" in load_out.splitlines()[-1:][0] if load_out.splitlines() else False:
        pass  # 加载失败会在下面取不到数据时暴露
    # 2) 逐帧读
    code = '''
import csc, json, numpy as np
frames = %s
mv = scene.model_viewer(); dv = scene.data_viewer()
objs = [(mv.get_object_name(o), mv.get_object_type_name(o), o) for o in mv.get_objects()]
joints = [(n, o) for n, t, o in objs if t == "Joint"]
out = {}
for fr in frames:
    scene.set_current_frame(fr)
    d = {}
    for n, o in joints:
        ch = None
        for dd in dv.get_all_data_id(o):
            if dv.get_data_name(dd) == "Global Matrix":
                ch = dd
                break
        if ch is None:
            continue
        try:
            d[n] = np.array(dv.get_data_value(ch, fr), dtype=float).reshape(4, 4).tolist()
        except Exception:
            pass
    out[str(fr)] = d
print("DUMPJSON" + json.dumps(out))
''' % json.dumps(list(frames))
    text = casc_run(code, timeout=900)
    for line in text.splitlines():
        if line.startswith("DUMPJSON"):
            return json.loads(line[len("DUMPJSON"):]), load_out
    raise RuntimeError("从 Cascadeur 读数据失败。返回如下：\n" + text[-1500:])


def detect_frames_from_casc(casc_path):
    tl = casc_core.load_json_entry(casc_path, "scene/timeline/timeline.json", {}) or {}
    data = tl.get("Data", {}) if isinstance(tl, dict) else {}
    return int(data.get("StartFrame", 0)), int(data.get("EndFrame", 100))


# ─────────────────────────── 模式：dump ───────────────────────────
def mode_dump():
    casc = ARGS["casc"]
    a, b = detect_frames_from_casc(casc)
    frames = casc_core.frame_list(ARGS.get("frames"), b - 0)
    frames = [f for f in frames if a <= f <= b] or list(range(a, b + 1))
    gm, load_out = fetch_gm(casc, frames)
    out = ARGS.get("gm") or (os.path.splitext(casc)[0] + "_gm.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(gm, f)
    emit(ok=True, mode="dump", casc=casc, gm=out, frames=len(frames),
         joints=len(next(iter(gm.values()))) if gm else 0, load_out=load_out[-200:])


# ─────────────────────────── 模式：blend / export ───────────────────────────
def load_model_fbx(path):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.fbx(filepath=path)
    arm = max((o for o in bpy.data.objects if o.type == 'ARMATURE'),
              key=lambda o: len(o.data.bones))
    meshes = [o for o in bpy.data.objects if o.type == 'MESH']
    return arm, meshes


def iter_action_fcurves(act):
    """Blender 4.4+ 的 slotted action 兼容层。"""
    try:
        legacy = list(act.fcurves)
        if legacy:
            return legacy
    except Exception:
        pass
    out = []
    for layer in getattr(act, "layers", []):
        for strip in getattr(layer, "strips", []):
            bags = []
            try:
                bags = list(strip.channelbags)
            except Exception:
                bags = []
            if not bags:
                for slot in getattr(act, "slots", []):
                    try:
                        cb = strip.channelbag(slot)
                    except Exception:
                        cb = None
                    if cb is not None:
                        bags.append(cb)
            for cb in bags:
                out.extend(list(cb.fcurves))
    return out


def rebuild(casc, gm_path, model_fbx, lod_spec, fbx_out=None, blend_out=None,
            use_reduce=False, key_threshold=1.5, fps=30):
    js = casc_core.load_scene_json(casc)
    model = casc_core.load_model_pose(js)
    gm = json.load(open(gm_path, encoding="utf-8"))

    arm, meshes = load_model_fbx(model_fbx)
    if arm.animation_data:
        arm.animation_data_clear()

    W_rest, order, parent = casc_core.compose_rest_world(arm, model)
    if not W_rest:
        raise RuntimeError("model pose 为空：.casc 里没有读到 statics")

    # 校验 rest 与绑定姿势
    rest_err = np.array([
        np.linalg.norm(W_rest[n][:3, 3] - np.array(arm.data.bones[n].matrix_local)[:3, 3])
        for n in W_rest if n in arm.data.bones
    ])

    # 选 LOD 网格
    casc_meshes = casc_core.pick_lod_meshes(casc_core.parse_meshes(js), lod_spec)
    keep_names = {m["object"] for m in casc_meshes}
    picked = [o for o in meshes if o.name in keep_names] or meshes
    for o in meshes:
        o.hide_render = o not in picked
        o.hide_viewport = o not in picked

    sc = bpy.context.scene
    frame_keys = sorted(int(f) for f in gm.keys())
    sc.frame_start = frame_keys[0]
    sc.frame_end = frame_keys[-1]
    sc.render.fps = int(fps)
    sc.render.fps_base = 1.0

    # ── 关键帧简化 ──
    write_frames = frame_keys
    reduce_stats = None
    if use_reduce:
        import keyreduce
        try:
            write_frames, reduce_stats = keyreduce.reduce_keys(gm, threshold_deg=float(key_threshold))
            err = keyreduce.reconstruction_error(gm, write_frames)
            reduce_stats.update({"mean_err_deg": err["mean"], "max_err_deg": err["max"]})
            print("keyreduce: %d -> %d frames (threshold %.2f deg)" % (
                reduce_stats["dense"], reduce_stats["keys"], float(key_threshold)), flush=True)
        except Exception as exc:
            print("keyreduce failed, falling back to dense keys:", repr(exc), flush=True)
            write_frames = frame_keys
            reduce_stats = {"error": str(exc)}

    for fr in write_frames:
        sc.frame_set(fr)
        casc_core.apply_pose(arm, gm[str(fr)], W_rest, order)
        bpy.context.view_layer.update()
        for n in order:
            pb = arm.pose.bones.get(n)
            if pb is None:
                continue
            pb.keyframe_insert("rotation_quaternion", frame=fr)
            pb.keyframe_insert("location", frame=fr)

    # 简化模式下设为 Bezier（AUTO_CLAMPED，不过冲）
    if use_reduce and reduce_stats and "error" not in reduce_stats:
        n_fc = 0
        for act in bpy.data.actions:
            for fc in iter_action_fcurves(act):
                for kp in fc.keyframe_points:
                    kp.interpolation = 'BEZIER'
                    kp.handle_left_type = 'AUTO_CLAMPED'
                    kp.handle_right_type = 'AUTO_CLAMPED'
                fc.update()
                n_fc += 1
        reduce_stats["bezier_fcurves"] = n_fc
        print("set BEZIER on %d fcurves" % n_fc, flush=True)

    # 校验骨骼位置 vs API
    sc.frame_set(frame_keys[0])
    bpy.context.view_layer.update()
    pos_err = []
    for n in order:
        M = gm[str(frame_keys[0])].get(n)
        if M is None or n not in arm.pose.bones:
            continue
        A = casc_core.B4 @ np.array(M, dtype=np.float64)
        my = np.array(arm.matrix_world @ arm.pose.bones[n].head) * 100.0
        pos_err.append(np.linalg.norm(A[:3, 3] - my))

    result = dict(ok=True, frames=len(frame_keys), joints=len(W_rest),
                  lod=[m["object"] for m in casc_meshes],
                  rest_err_cm=float(rest_err.mean()) if len(rest_err) else None,
                  bone_pos_err_cm=float(np.mean(pos_err)) if pos_err else None,
                  bone_pos_err_max_cm=float(np.max(pos_err)) if pos_err else None)
    if reduce_stats is not None:
        result["reduce"] = reduce_stats
        result["keyframes"] = (len(write_frames) if "error" not in reduce_stats else len(frame_keys))
        result["interpolation"] = "BEZIER(AUTO_CLAMPED)" if "error" not in reduce_stats else "default"

    if blend_out:
        bpy.ops.wm.save_as_mainfile(filepath=blend_out)
        result["blend"] = blend_out
    if fbx_out:
        sc.frame_set(frame_keys[0])
        for o in bpy.data.objects:
            o.select_set(False)
        arm.select_set(True)
        for o in picked:
            o.select_set(True)
        bpy.context.view_layer.objects.active = arm
        bpy.ops.export_scene.fbx(
            filepath=fbx_out, use_selection=True,
            apply_scale_options='FBX_SCALE_NONE', global_scale=1.0,
            bake_space_transform=False, object_types={'ARMATURE', 'MESH'},
            use_mesh_modifiers=False, mesh_smooth_type='OFF',
            add_leaf_bones=False, bake_anim=True,
            bake_anim_use_all_actions=False, bake_anim_use_nla_strips=False,
            bake_anim_force_startend_keying=True, bake_anim_step=1.0)
        result["fbx"] = fbx_out
        result["fbx_mb"] = round(os.path.getsize(fbx_out) / 1024 / 1024, 2)
    return result


def mode_blend():
    casc = ARGS["casc"]
    gm = ARGS.get("gm") or (os.path.splitext(casc)[0] + "_gm.json")
    if not os.path.exists(gm):
        mode_dump()
        # mode_dump 里 emit 过一次，这里继续（JS 侧以最后一次为准）
    model_fbx = ARGS["model_fbx"]
    blend_out = ARGS["blend_out"]
    r = rebuild(casc, gm, model_fbx, ARGS.get("lod", "0"), blend_out=blend_out,
                use_reduce=(ARGS.get("reduce_keys", "false").lower() in ("1", "true", "yes")),
                key_threshold=float(ARGS.get("key_threshold", 1.5)),
                fps=int(ARGS.get("fps", 30)))
    r["mode"] = "blend"
    emit(**r)


def mode_export():
    casc = ARGS["casc"]
    gm = ARGS.get("gm") or (os.path.splitext(casc)[0] + "_gm.json")
    if not os.path.exists(gm):
        mode_dump()
    model_fbx = ARGS["model_fbx"]
    fbx_out = ARGS["fbx_out"]
    r = rebuild(casc, gm, model_fbx, ARGS.get("lod", "0"), fbx_out=fbx_out,
                use_reduce=(ARGS.get("reduce_keys", "false").lower() in ("1", "true", "yes")),
                key_threshold=float(ARGS.get("key_threshold", 1.5)),
                fps=int(ARGS.get("fps", 30)))
    r["mode"] = "export"
    emit(**r)


def mode_verify():
    casc = ARGS["casc"]
    gm = ARGS.get("gm") or (os.path.splitext(casc)[0] + "_gm.json")
    if not os.path.exists(gm):
        mode_dump()
    r = rebuild(casc, gm, ARGS["model_fbx"], ARGS.get("lod", "0"))
    r["mode"] = "verify"
    ok = (r.get("bone_pos_err_max_cm") is not None and r["bone_pos_err_max_cm"] < 0.01)
    r["ok"] = bool(ok)
    emit(**r)


MODES = {"inspect": mode_inspect, "dump": mode_dump, "blend": mode_blend,
         "export": mode_export, "verify": mode_verify}

if __name__ == "__main__":
    mode = ARGS.get("mode", "inspect")
    try:
        MODES[mode]()
    except Exception as e:
        emit(ok=False, mode=mode, error=str(e), traceback=traceback.format_exc()[-1500:])
        sys.exit(1)
