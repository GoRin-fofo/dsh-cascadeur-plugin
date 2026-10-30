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
        if not k.startswith("--"):
            i += 1
            continue
        if "=" in k:                       # --key=value
            key, val = k[2:].split("=", 1)
            out[key.replace("-", "_")] = val
            i += 1
            continue
        key = k[2:].replace("-", "_")
        if i + 1 < len(argv) and not argv[i + 1].startswith("--"):
            out[key] = argv[i + 1]
            i += 2
        else:                              # 布尔开关
            out[key] = "true"
            i += 1
    return out


def _truthy(v):
    return str(v).lower() in ("1", "true", "yes", "on")


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
    last = (load_out.strip().splitlines() or [""])[-1].strip().lower()
    if last not in ("true", "ok"):
        raise RuntimeError(
            "Cascadeur 加载场景失败（返回：%r）。\n"
            "请确认：Cascadeur 正在运行、MCP 脚本服务器已启动（127.0.0.1:8765）、\n"
            "且该 .casc 路径存在。原始输出：\n%s" % (last, load_out[-800:]))
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


# ─────────────────────────── GM 缓存（按 .casc 内容指纹命名）───────────────────────────
def casc_fingerprint(casc_path):
    st = os.stat(casc_path)
    return "%d_%d" % (st.st_size, int(st.st_mtime))


def gm_cache_path(casc_path, frames_spec=None):
    """缓存文件名里带上 .casc 的 size+mtime 与帧范围，避免读到过期缓存。"""
    d = os.path.join(os.path.dirname(os.path.abspath(casc_path)), "_dsh_cache")
    os.makedirs(d, exist_ok=True)
    base = os.path.splitext(os.path.basename(casc_path))[0]
    spec = (frames_spec or "all").replace(",", "-").replace(" ", "")
    return os.path.join(d, "%s_%s_f%s_gm.json" % (base, casc_fingerprint(casc_path), spec))


def resolve_gm_path(casc_path, force=False):
    """返回 (gm 路径, 是否可直接复用)。"""
    explicit = ARGS.get("gm")
    if explicit:
        return explicit, (os.path.exists(explicit) and not force)
    path = gm_cache_path(casc_path, ARGS.get("frames"))
    return path, (os.path.exists(path) and not force)


def write_gm(gm, out_path, meta=None):
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(gm, f)
    if meta:
        with open(out_path + ".meta.json", "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False)


def read_gm_meta(out_path):
    try:
        with open(out_path + ".meta.json", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


# ─────────────────────────── 模式：dump ───────────────────────────
def do_dump(casc):
    """读 Global Matrix 并落盘，返回 (路径, 元信息)。"""
    a, b = detect_frames_from_casc(casc)
    frames, notes = casc_core.frame_list_checked(ARGS.get("frames"), a, b)
    gm, load_out = fetch_gm(casc, frames)
    out, _ = resolve_gm_path(casc, force=True)
    meta = {
        "casc": os.path.abspath(casc),
        "fingerprint": casc_fingerprint(casc),
        "frames_requested": frames[0] if frames else None,
        "frames": len(frames),
        "range": [frames[0], frames[-1]] if frames else None,
        "joints": len(next(iter(gm.values()))) if gm else 0,
        "notes": notes,
        "load_out": load_out[-300:],
    }
    write_gm(gm, out, meta)
    return out, meta


def mode_dump():
    casc = ARGS["casc"]
    out, meta = do_dump(casc)
    emit(ok=True, mode="dump", casc=casc, gm=out, frames=meta["frames"],
         joints=meta["joints"], range=meta["range"], notes=meta["notes"],
         load_out=meta["load_out"])


def ensure_gm(casc):
    """blend / export 用：缓存有效就复用，否则重读。"""
    path, reusable = resolve_gm_path(casc, force=_truthy(ARGS.get("force", "false")))
    if reusable:
        meta = read_gm_meta(path)
        print("gm cache hit:", path, flush=True)
        return path, {"cached": True, "path": path, "meta": meta}
    print("gm cache miss -> dumping:", path, flush=True)
    out, meta = do_dump(casc)
    return out, {"cached": False, "path": out, "meta": meta}


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
            use_reduce=False, key_threshold=1.5, fps=30,
            use_despike=True, key_angle_deg=2.0, key_pos_cm=2.0, key_min_gap=1):
    js = casc_core.load_scene_json(casc)
    model = casc_core.load_model_pose(js)
    gm = json.load(open(gm_path, encoding="utf-8"))

    arm, meshes = load_model_fbx(model_fbx)
    if arm.animation_data:
        arm.animation_data_clear()

    W_rest, order, parent = casc_core.compose_rest_world(arm, model)
    if not W_rest:
        raise RuntimeError("model pose 为空：.casc 里没有读到 statics")

    # ── 隐式假设 → 显式断言 ──
    fbx_bones = {b.name for b in arm.data.bones}
    matched = [n for n in W_rest if n in fbx_bones]
    missing = sorted(n for n in W_rest if n not in fbx_bones)
    unmatched_fbx = sorted(fbx_bones - set(W_rest))
    if not matched:
        raise RuntimeError(
            "骨架名对不上：.casc 里 %d 根骨没有一根能在 FBX 里找到。\n"
            ".casc 示例：%s\nFBX 示例：%s\n"
            "（--model-fbx 大概率选错了模型）"
            % (len(W_rest), sorted(W_rest)[:6], sorted(fbx_bones)[:6]))
    if missing:
        print("WARN %d 根骨在 FBX 里不存在，已跳过：%s" % (len(missing), missing[:8]), flush=True)

    # rotation_mode 必须是 QUATERNION，否则 keyframe_insert("rotation_quaternion") 不会生效
    bad_mode = []
    for n in matched:
        pb = arm.pose.bones.get(n)
        if pb is None:
            continue
        if pb.rotation_mode != 'QUATERNION':
            bad_mode.append((n, pb.rotation_mode))
            pb.rotation_mode = 'QUATERNION'
    if bad_mode:
        print("WARN %d 根骨的 rotation_mode 非 QUATERNION，已强制切换：%s" % (
            len(bad_mode), bad_mode[:5]), flush=True)

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

    # ── 跳变修复 + 关键帧简化 ──
    write_frames = frame_keys
    reduce_stats = None
    despike_stats = None
    if use_reduce:
        import keyreduce
        try:
            if use_despike:
                fixed_all, rounds, max_rounds = [], 0, 4
                while rounds < max_rounds:
                    sp = [f for f in keyreduce.detect_spikes(gm) if f not in fixed_all]
                    if not sp:
                        break
                    rounds += 1
                    fixed_all.extend(sp)
                    gm, _ = keyreduce.repair_spikes(gm, sp)
                    print("despike round %d: fixed %s" % (rounds, sp), flush=True)
                despike_stats = {"fixed_frames": sorted(fixed_all),
                                 "rounds": rounds, "max_rounds": max_rounds,
                                 "converged": rounds < max_rounds}
                if fixed_all:
                    with open(gm_path + ".despiked.json", "w", encoding="utf-8") as fh:
                        json.dump(gm, fh)
                    print("despike: %d frames repaired in %d round(s) (%s)" % (
                        len(fixed_all), rounds, sorted(fixed_all)), flush=True)

            write_frames, reduce_stats = keyreduce.reduce_keys(
                gm,
                key_angle_deg=float(key_angle_deg),
                key_pos_cm=float(key_pos_cm),
                min_gap=int(key_min_gap))
            err = keyreduce.reconstruction_error(gm, write_frames)
            reduce_stats.update({
                "mean_deg": err["mean_deg"], "max_deg": err["max_deg"],
                "mean_cm": err["mean_cm"], "max_cm": err["max_cm"],
            })
            print("keyreduce: %d -> %d frames (angle<=%.2f deg, pos<=%.2f cm, violations=%d)" % (
                reduce_stats["dense"], reduce_stats["keys"],
                float(key_angle_deg), float(key_pos_cm), reduce_stats["violations"]), flush=True)
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

    result = dict(ok=(not missing), frames=len(frame_keys), joints=len(W_rest),
                  matched_bones=len(matched), missing_bones=missing,
                  unmatched_fbx_bones=unmatched_fbx[:40],
                  unmatched_fbx_count=len(unmatched_fbx),
                  lod=[m["object"] for m in casc_meshes],
                  rest_err_cm=float(rest_err.mean()) if len(rest_err) else None,
                  bone_pos_err_cm=float(np.mean(pos_err)) if pos_err else None,
                  bone_pos_err_max_cm=float(np.max(pos_err)) if pos_err else None)
    if despike_stats is not None:
        result["despike"] = despike_stats
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
    gm, cache_info = ensure_gm(casc)
    model_fbx = ARGS["model_fbx"]
    blend_out = ARGS["blend_out"]
    r = rebuild(casc, gm, model_fbx, ARGS.get("lod", "0"), blend_out=blend_out,
                use_reduce=(ARGS.get("reduce_keys", "false").lower() in ("1", "true", "yes")),
                key_threshold=float(ARGS.get("key_threshold", 2.0)),
                use_despike=(ARGS.get("despike", "true").lower() in ("1", "true", "yes")),
                key_angle_deg=float(ARGS.get("key_angle", ARGS.get("key_threshold", 2.0))),
                key_pos_cm=float(ARGS.get("key_pos", 2.0)),
                key_min_gap=int(ARGS.get("key_min_gap", 1)),
                fps=int(ARGS.get("fps", 30)))
    r["gm"] = cache_info
    r["mode"] = "blend"
    emit(**r)


def mode_export():
    casc = ARGS["casc"]
    gm, cache_info = ensure_gm(casc)
    model_fbx = ARGS["model_fbx"]
    fbx_out = ARGS["fbx_out"]
    r = rebuild(casc, gm, model_fbx, ARGS.get("lod", "0"), fbx_out=fbx_out,
                use_reduce=(ARGS.get("reduce_keys", "false").lower() in ("1", "true", "yes")),
                key_threshold=float(ARGS.get("key_threshold", 2.0)),
                use_despike=(ARGS.get("despike", "true").lower() in ("1", "true", "yes")),
                key_angle_deg=float(ARGS.get("key_angle", ARGS.get("key_threshold", 2.0))),
                key_pos_cm=float(ARGS.get("key_pos", 2.0)),
                key_min_gap=int(ARGS.get("key_min_gap", 1)),
                fps=int(ARGS.get("fps", 30)))
    r["gm"] = cache_info
    r["mode"] = "export"
    emit(**r)


def mode_verify():
    casc = ARGS["casc"]
    gm, cache_info = ensure_gm(casc)
    r = rebuild(casc, gm, ARGS["model_fbx"], ARGS.get("lod", "0"))
    r["gm"] = cache_info
    r["mode"] = "verify"
    limit = float(ARGS.get("tolerance_cm", 0.01))
    checks = {
        "rest_err_cm": r.get("rest_err_cm"),
        "bone_pos_err_max_cm": r.get("bone_pos_err_max_cm"),
        "missing_bones": r.get("missing_bones", []),
    }
    ok = (r.get("bone_pos_err_max_cm") is not None
          and r["bone_pos_err_max_cm"] < limit
          and not checks["missing_bones"])
    r["ok"] = bool(ok)
    r["tolerance_cm"] = limit
    r["checks"] = checks
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
