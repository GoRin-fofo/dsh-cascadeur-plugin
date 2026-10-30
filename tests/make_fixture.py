# -*- coding: utf-8 -*-
"""生成一个最小的 .casc 测试固件（不依赖 Cascadeur / Blender）。

固件内容：
  scene/scene.json          —— 1 根 Joint + 1 个 Mesh Object（新明文格式）+ statics
  scene/timeline/timeline.json
  scene/scene_settings.json

条目用 Zstandard(method 93) 压缩，和真实 .casc 一致，从而覆盖真实解包路径。
"""
import io
import json
import os
import struct
import zipfile

import zstandard

JOINT_ID = "11111111-1111-1111-1111-111111111111"
MESH_OBJ_ID = "22222222-2222-2222-2222-222222222222"
CHILD_ID = "44444444-4444-4444-4444-444444444444"
MESH_ASSET_ID = "33333333-3333-3333-3333-333333333333"


def scene_json():
    return {
        "objects": [
            {
                "id": JOINT_ID,
                "name": "root",
                "type_name": "Joint",
                "parent": None,
                "data": [
                    {"name": "Model Pose Local Position", "index": 1},
                    {"name": "Model Pose Local Rotation", "index": 2},
                ],
            },
            {
                "id": CHILD_ID,
                "name": "child",
                "type_name": "Joint",
                "parent": JOINT_ID,
                "data": [
                    {"name": "Model Pose Local Position", "index": 3},
                    {"name": "Model Pose Local Rotation", "index": 4},
                ],
            },
            {
                "id": MESH_OBJ_ID,
                "name": "Cube_LOD0",
                "type_name": "Mesh Object",
                "parent": None,
                "behaviours": [
                    {
                        "type": "MeshObject",
                        "mesh": MESH_ASSET_ID,
                        "linked_objects": [JOINT_ID, CHILD_ID],
                    },
                ],
            },
        ],
        "assets": [
            {
                "type": "mesh",
                "id": MESH_ASSET_ID,
                "vertices": [
                    [[0.0], [0.0], [0.0], [1.0]],
                    [[1.0], [0.0], [0.0], [1.0]],
                    [[1.0], [1.0], [0.0], [1.0]],
                    [[0.0], [1.0], [0.0], [1.0]],
                ],
                "normals": [[[0.0], [0.0], [1.0], [0.0]]],
                "texture_coords": [[[0.0], [0.0]], [[1.0], [0.0]], [[1.0], [1.0]], [[0.0], [1.0]]],
                "triangles_vertex_indices": [0, 1, 2, 0, 2, 3],
            },
        ],
        "layers": [{"name": "Scene", "visible": True, "object_ids": [JOINT_ID, CHILD_ID, MESH_OBJ_ID]}],
        "statics": {
            "1": {"x": 0.0, "y": 0.0, "z": 0.0},
            "2": {"x": 0.0, "y": 0.0, "z": 0.0},
            "3": {"x": 0.0, "y": 0.0, "z": 50.0},
            "4": {"x": 0.0, "y": 0.0, "z": 0.0},
        },
    }


def timeline_json(start=0, end=9):
    return {"Data": {"StartFrame": start, "EndFrame": end, "CurrentFrame": start,
                     "VisibleEndFrame": end}}


def settings_json(fps=30):
    return {"Data": {"FPS": fps}}


def _zstd(data):
    return zstandard.ZstdCompressor(level=3).compress(data)


def write_zip93(path, entries):
    """手写 ZIP，条目用 method 93（Zstandard）。"""
    out = io.BytesIO()
    central = io.BytesIO()
    for name, raw in entries:
        comp = _zstd(raw)
        crc = zstandard.__dict__.get("_crc")  # 不用；手算 CRC32
        import binascii
        crc = binascii.crc32(raw) & 0xFFFFFFFF
        name_b = name.encode("utf-8")
        offset = out.tell()
        # local header
        out.write(struct.pack("<IHHHHHIIIHH", 0x04034B50, 45, 0, 93, 0, 0,
                              crc, len(comp), len(raw), len(name_b), 0))
        out.write(name_b)
        out.write(comp)
        # central directory
        central.write(struct.pack("<IHHHHHHIIIHHHHHII", 0x02014B50, 45, 45, 0, 93, 0, 0,
                                  crc, len(comp), len(raw), len(name_b), 0, 0, 0, 0, 0, offset))
        central.write(name_b)
    cd = central.getvalue()
    cd_off = out.tell()
    out.write(cd)
    out.write(struct.pack("<IHHHHIIH", 0x06054B50, 0, 0, len(entries), len(entries),
                          len(cd), cd_off, 0))
    with open(path, "wb") as f:
        f.write(out.getvalue())


def build(path):
    entries = [
        ("scene/scene.json", json.dumps(scene_json()).encode("utf-8")),
        ("scene/timeline/timeline.json", json.dumps(timeline_json()).encode("utf-8")),
        ("scene/scene_settings.json", json.dumps(settings_json()).encode("utf-8")),
    ]
    write_zip93(path, entries)
    return path


if __name__ == "__main__":
    p = build(os.path.join(os.path.dirname(os.path.abspath(__file__)), "_fixture_min.casc"))
    print("wrote", p, os.path.getsize(p), "bytes")
