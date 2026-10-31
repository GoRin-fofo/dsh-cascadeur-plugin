# -*- coding: utf-8 -*-
"""casc_core —— Cascadeur .casc 解析与姿势重建的核心库。

⚠️ 关键公式（不要改）：
    A = B4 @ M                # 只左乘！相似变换 B4@M@B4.T 会多转 90° 导致扭曲
    D = A @ inv(W_rest)
    pose_bone.matrix = D @ bone.matrix_local

W_rest 来自场景的 model pose（Z-up，欧拉 ZYX），不做任何转换。
"""
import json
import struct

import numpy as np
import zstandard

B4 = np.array([[1, 0, 0, 0],
               [0, 0, -1, 0],
               [0, 1, 0, 0],
               [0, 0, 0, 1]], dtype=np.float64)


# ────────────────────────────── .casc 解包 ──────────────────────────────
def read_casc_entry(casc_path, want_name):
    """从 .casc 里取出一个文件并解压（按条目声明的压缩方式分派）。"""
    buf = open(casc_path, "rb").read()
    eocd = buf.rfind(b"PK\x05\x06")
    if eocd < 0:
        raise ValueError("不是 ZIP 文件（找不到 EOCD）：%s" % casc_path)
    n_entries, cd_size, cd_off = struct.unpack_from("<HII", buf, eocd + 10)
    p = cd_off
    for _ in range(n_entries):
        if buf[p:p + 4] != b"PK\x01\x02":
            break
        method, = struct.unpack_from("<H", buf, p + 10)
        csize, usize = struct.unpack_from("<II", buf, p + 20)
        nlen, elen, clen = struct.unpack_from("<HHH", buf, p + 28)
        lho, = struct.unpack_from("<I", buf, p + 42)
        name = buf[p + 46:p + 46 + nlen].decode("utf-8", "replace")
        if name == want_name:
            n2, e2 = struct.unpack_from("<HH", buf, lho + 26)
            off = lho + 30 + n2 + e2
            comp = buf[off:off + csize]
            if method == 0:                       # stored
                return comp
            if method == 8:                       # deflate
                import zlib
                return zlib.decompress(comp, -15)
            if method != 93:                      # 93 = Zstandard
                raise RuntimeError(
                    "条目 %r 使用了不支持的压缩方式（%d）"
                    % (want_name, method))
            try:
                return zstandard.ZstdDecompressor().decompress(comp, max_output_size=usize + 1024)
            except Exception as exc:
                # 绝不能把解压失败的原始字节当成 JSON 往下传（会静默产出垃圾）
                raise RuntimeError(
                    "无法解压 .casc 内的条目 %r（%d 字节压缩 / %d 字节原始）：%r\n"
                    "可能是 zstandard 版本不匹配，或文件不完整。"
                    % (want_name, csize, usize, exc))
        p += 46 + nlen + elen + clen
    return None


def load_scene_json(casc_path):
    raw = read_casc_entry(casc_path, "scene/scene.json")
    if raw is None:
        raise ValueError("这个 .casc 里没有 scene/scene.json：%s" % casc_path)
    return json.loads(raw)


def load_json_entry(casc_path, name, default=None):
    raw = read_casc_entry(casc_path, name)
    if raw is None:
        return default
    try:
        return json.loads(raw)
    except Exception:
        return default


# ────────────────────────────── model pose ──────────────────────────────
def load_model_pose(scene_json):
    """从 statics 读出每骨骼的 model pose 局部变换 (pos, rot)。

    返回 {joint_name: (pos_tuple, rot_tuple)}，单位厘米，欧拉顺序 ZYX。
    """
    statics = scene_json.get("statics", {})
    model = {}
    for o in scene_json.get("objects", []):
        if o.get("type_name") != "Joint":
            continue
        name, pos, rot = o.get("name"), None, None
        for d in o.get("data", []):
            n, idx = d.get("name", ""), d.get("index")
            if idx is None:
                continue
            v = statics.get(str(idx))
            if v is None:
                continue
            if n == "Model Pose Local Position":
                pos = (v["x"], v["y"], v["z"])
            elif n == "Model Pose Local Rotation":
                rot = (v["x"], v["y"], v["z"])
        if pos is not None and rot is not None:
            model[name] = (pos, rot)
    return model


def compose_rest_world(arm, model):
    """把 model pose 合成世界矩阵（Z-up 厘米）。arm 是 bpy 的骨架对象。"""
    from mathutils import Euler, Matrix, Vector

    parent = {b.name: (b.parent.name if b.parent else None) for b in arm.data.bones}
    order = []

    def walk(b):
        order.append(b.name)
        for c in b.children:
            walk(c)

    for b in arm.data.bones:
        if b.parent is None:
            walk(b)

    W = {}
    for n in order:
        if n not in model:
            continue
        pos, rot = model[n]
        L = Matrix.Translation(Vector(pos)) @ Euler(rot, 'ZYX').to_matrix().to_4x4()
        p = parent.get(n)
        W[n] = np.array(L) if p is None or p not in W else W[p] @ np.array(L)
    return W, order, parent


# ────────────────────────────── 蒙皮网格 ──────────────────────────────
def parse_meshes(scene_json):
    """解析场景里的网格对象（顶点数、蒙皮骨数、可选的顶点/权重数据）。

    返回 [{id, name(若可推断), verts, tris, joints(linked_objects 名字), weights}]
    """
    import base64

    assets = {a["id"]: a for a in scene_json.get("assets", []) if "id" in a}
    by_id = {o["id"]: o for o in scene_json.get("objects", []) if "id" in o}

    out = []
    for o in scene_json.get("objects", []):
        if o.get("type_name") != "Mesh Object":
            continue
        beh = next((b for b in o.get("behaviours", []) if b.get("type") == "MeshObject"), None)
        if beh is None:
            continue
        mesh_asset = assets.get((beh.get("mesh") or "").strip()) if beh.get("mesh") else None
        dep_asset = assets.get(beh.get("mesh_dependency"))
        # 没有几何数据的对象（例如参考视频）直接跳过
        if mesh_asset is None or ("mesh" not in mesh_asset and "vertices" not in mesh_asset):
            continue
        info = {
            "object": o.get("name"),
            "mesh_id": beh.get("mesh"),
            "verts": 0,
            "tris": 0,
            "skinned_bones": len(beh.get("linked_objects") or []),
            "bone_names": [],
            "verts_data": None,
            "weights": None,
        }
        if "mesh" in mesh_asset:
            # ── 变体 A ──
            raw = base64.b64decode(mesh_asset["mesh"])
            ver, count = struct.unpack_from("<II", raw, 0)
            info["verts"] = count
            rest = (len(raw) - 8) - count * 16
            # 注意：网格资产里除索引外还有法线/UV 等块，三角形数无法简单推算
            info["extra_bytes"] = rest
            info["verts_data"] = np.frombuffer(raw, dtype=np.float32, count=count * 4, offset=8) \
                .reshape(count, 4)[:, 1:4].astype(np.float64)
        else:
            # ── 变体 B ──
            def _num(x):
                while isinstance(x, list):
                    if not x:
                        return 0.0
                    x = x[0]
                return float(x)

            verts = mesh_asset.get("vertices") or []
            info["verts"] = len(verts)
            try:
                info["verts_data"] = np.array(
                    [[_num(v[0]), _num(v[1]), _num(v[2])] for v in verts], dtype=np.float64)
            except Exception:
                info["verts_data"] = None
            tris = mesh_asset.get("triangles_vertex_indices") or []
            info["tris"] = len(tris) // 3
        if dep_asset is not None and "dependency" in dep_asset:
            raw = base64.b64decode(dep_asset["dependency"])
            nv, _ = struct.unpack_from("<II", raw, 0)
            pos = 8
            weights = []
            for _ in range(nv):
                n, _pad = struct.unpack_from("<II", raw, pos)
                pos += 8
                pairs = []
                for _ in range(n):
                    b, w = struct.unpack_from("<If", raw, pos)
                    pos += 8
                    pairs.append((b, w))
                weights.append(pairs)
            info["weights"] = weights
            info["bone_names"] = [by_id.get(oid, {}).get("name") for oid in (beh.get("linked_objects") or [])]
        out.append(info)
    return out


def pick_lod_meshes(meshes, lod_spec, drop_reference_planes=True):
    """按 lod 参数筛选网格。

    语义（v0.4.0 修正）：
      * 名字里没有 LOD 的网格（道具、剑等）**始终保留**，不会被 lod 参数误删
      * 有 LOD 的网格：只保留请求的 LOD
      * lod_spec: '0' | 'all' | '0,2'
      * 默认丢掉"参考视频平面"（名字形如 MeshObject(0) 且只有 <=4 个顶点的四边形）
    """
    import re

    def lod_of(name):
        u = (name or "").upper()
        m = re.search(r"LOD[_-]?(\d+)", u)
        if m:
            return int(m.group(1))
        if "LOD" in u:
            try:
                return int(u.split("LOD")[-1][0])
            except Exception:
                return None
        return None

    def is_reference_plane(m):
        nm = m.get("object") or ""
        if not re.match(r"^MeshObject\(\d+\)$", nm):
            return False
        return int(m.get("verts") or 0) <= 4

    keep = []
    for m in meshes:
        if drop_reference_planes and is_reference_plane(m):
            continue
        keep.append(m)

    if str(lod_spec or "0").strip().lower() == "all":
        return sorted(keep, key=lambda m: (lod_of(m["object"]) is None, lod_of(m["object"]) or 0))

    want = []
    for tok in str(lod_spec or "0").split(","):
        tok = tok.strip()
        if tok.isdigit():
            want.append(int(tok))
    if not want:
        want = [0]

    picked = []
    for m in keep:
        lv = lod_of(m["object"])
        if lv is None or lv in want:      # 道具 / 匹配的 LOD
            picked.append(m)
    picked.sort(key=lambda m: (lod_of(m["object"]) is None, lod_of(m["object"]) or 0))
    return picked or keep[:1]


# ────────────────────────────── 姿势应用 ──────────────────────────────
def apply_pose(arm, gm_frame, W_rest, order):
    """把一帧的 Global Matrix 应用到骨架。

    gm_frame: {bone: 4x4 (Y-up 厘米)}
    """
    from mathutils import Matrix

    for n in order:
        M = gm_frame.get(n)
        pb = arm.pose.bones.get(n)
        if M is None or pb is None or n not in W_rest:
            continue
        # ⚠️ 只左乘 B4；@ B4.T 会多转 90°，导致整模扭曲
        A = B4 @ np.array(M, dtype=np.float64)
        D = A @ np.linalg.inv(W_rest[n])
        pb.matrix = Matrix((D @ np.array(arm.data.bones[n].matrix_local, dtype=np.float64)).tolist())
        # 必须每设一根就刷新：子骨矩阵依赖父骨已求值（漏了会导致姿势错 60+ cm）
        import bpy
        bpy.context.view_layer.update()


def frame_list(frames_spec, default_end):
    """'0-10' / '0,5,10' / 'auto' → [int]"""
    if frames_spec in (None, "", "auto"):
        if default_end is None:
            return None
        return list(range(0, default_end + 1))
    s = str(frames_spec)
    if "-" in s:
        a, b = s.split("-")
        return list(range(int(a), int(b) + 1))
    return [int(x) for x in s.split(",") if x.strip()]


def frame_list_checked(frames_spec, start, end):
    """带校验的 frame_list：显式指定范围时，超出或为空都报错（不再静默回退）。

    返回 (frames, notes)。
    """
    notes = []
    if frames_spec in (None, "", "auto"):
        return list(range(start, end + 1)), notes
    frames = frame_list(frames_spec, end)
    if not frames:
        raise ValueError("--frames 解析为空：%r" % (frames_spec,))
    outside = [f for f in frames if f < start or f > end]
    if outside:
        raise ValueError(
            "--frames 指定的帧超出了该 .casc 的时间轴范围 [%d, %d]：%s\n"
            "（如果目标是更长的时间轴，请先在 Cascadeur 里改 timeline 的 EndFrame 并保存）"
            % (start, end, outside[:8]))
    # 去重保序
    seen, uniq = set(), []
    for f in frames:
        if f not in seen:
            seen.add(f)
            uniq.append(f)
    if len(uniq) != len(frames):
        notes.append("frames 去重：%d -> %d（部分帧可能因此不连续，插值会退化）"
                     % (len(frames), len(uniq)))
    return uniq, notes
