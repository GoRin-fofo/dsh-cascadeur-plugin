# -*- coding: utf-8 -*-
"""casc_core —— Cascadeur .casc 解析与姿势重建的核心库。

⚠️ 关键公式（不要改）：
    A = B4 @ M                # 只左乘！相似变换 B4@M@B4.T 会多转 90° 导致扭曲
    D = A @ inv(W_rest)
    pose_bone.matrix = D @ bone.matrix_local

W_rest 来自 .casc 的 statics（model pose，Z-up，欧拉 ZYX），不做任何转换。
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
    """从 .casc（ZIP + Zstandard method 93）里取出一个文件并解压。"""
    buf = open(casc_path, "rb").read()
    eocd = buf.rfind(b"PK\x05\x06")
    if eocd < 0:
        raise ValueError("不是 ZIP 文件（找不到 EOCD）：%s" % casc_path)
    n_entries, cd_size, cd_off = struct.unpack_from("<HII", buf, eocd + 10)
    p = cd_off
    for _ in range(n_entries):
        if buf[p:p + 4] != b"PK\x01\x02":
            break
        csize, usize = struct.unpack_from("<II", buf, p + 20)
        nlen, elen, clen = struct.unpack_from("<HHH", buf, p + 28)
        lho, = struct.unpack_from("<I", buf, p + 42)
        name = buf[p + 46:p + 46 + nlen].decode("utf-8", "replace")
        if name == want_name:
            n2, e2 = struct.unpack_from("<HH", buf, lho + 26)
            off = lho + 30 + n2 + e2
            comp = buf[off:off + csize]
            try:
                return zstandard.ZstdDecompressor().decompress(comp, max_output_size=usize + 1024)
            except Exception:
                return comp
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
    """解析 assets 里的 mesh / mesh_dependency / materials_link。

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
        mesh_asset = assets.get(beh.get("mesh"))
        dep_asset = assets.get(beh.get("mesh_dependency"))
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
        if mesh_asset is not None:
            raw = base64.b64decode(mesh_asset["mesh"])
            ver, count = struct.unpack_from("<II", raw, 0)
            info["verts"] = count
            rest = (len(raw) - 8) - count * 16
            # 注意：网格资产里除索引外还有法线/UV 等块，三角形数无法简单推算
            info["extra_bytes"] = rest
            info["verts_data"] = np.frombuffer(raw, dtype=np.float32, count=count * 4, offset=8) \
                .reshape(count, 4)[:, 1:4].astype(np.float64)
        if dep_asset is not None:
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


def pick_lod_meshes(meshes, lod_spec):
    """按 lod 参数筛选网格。lod_spec: '0' | 'all' | '0,2'"""
    def lod_of(name):
        u = (name or "").upper()
        if "LOD" in u:
            try:
                return int(u.split("LOD")[-1][0])
            except Exception:
                return 0
        return 0

    named = sorted(meshes, key=lambda m: lod_of(m["object"]))
    if lod_spec in (None, "", "0"):
        return [m for m in named if lod_of(m["object"]) == 0][:1] or named[:1]
    if str(lod_spec).lower() == "all":
        return named
    want = []
    for tok in str(lod_spec).split(","):
        tok = tok.strip()
        if tok.isdigit():
            want.append(int(tok))
    picked = [m for m in named if lod_of(m["object"]) in want]
    return picked or named[:1]


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
