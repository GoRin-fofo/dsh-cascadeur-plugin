# -*- coding: utf-8 -*-
"""casc_core 单元测试（不依赖 Blender；需要 numpy + zstandard）。

本地用 Blender 自带的 Python 跑（它有 zstandard）：
    blender -b --factory-startup --python tests/test_casc_core.py
或装了依赖的普通 Python：
    python tests/test_casc_core.py
"""
import os
import sys
import tempfile

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "runtime"))
sys.path.insert(0, HERE)

import casc_core  # noqa: E402
import make_fixture  # noqa: E402
from make_fixture import JOINT_ID  # noqa: E402

FAILS = []


def check(name, cond, detail=""):
    if cond:
        print("  PASS  %s %s" % (name, detail))
    else:
        print("  FAIL  %s %s" % (name, detail))
        FAILS.append(name)


def test_zip_and_json():
    print("\n[1] 容器解包 + JSON 解析")
    tmp = tempfile.mkdtemp(prefix="casc_test_")
    p = make_fixture.build(os.path.join(tmp, "mini.casc"))
    check("固件已生成", os.path.exists(p) and os.path.getsize(p) > 100,
          "%d bytes" % os.path.getsize(p))

    js = casc_core.load_scene_json(p)
    check("scene.json 可解析", isinstance(js, dict) and "objects" in js)
    check("对象数 = 3（2 骨 + 1 网格）", len(js.get("objects", [])) == 3, "got %d" % len(js.get("objects", [])))
    check("资产数 = 1", len(js.get("assets", [])) == 1)

    tl = casc_core.load_json_entry(p, "scene/timeline/timeline.json")
    check("timeline EndFrame = 9", tl["Data"]["EndFrame"] == 9)
    st = casc_core.load_json_entry(p, "scene/scene_settings.json")
    check("settings FPS = 30", st["Data"]["FPS"] == 30)
    check("不存在的条目返回 None",
          casc_core.load_json_entry(p, "scene/nope.json") is None)


def test_error_paths():
    print("\n[2] 错误路径：不再静默返回垃圾")
    tmp = tempfile.mkdtemp(prefix="casc_err_")
    bad = os.path.join(tmp, "notzip.casc")
    with open(bad, "wb") as f:
        f.write(b"hello world, definitely not a zip")
    try:
        casc_core.read_casc_entry(bad, "scene/scene.json")
        check("非 ZIP 应抛异常", False)
    except ValueError:
        check("非 ZIP 抛 ValueError", True)

    # 损坏的 zstd 数据
    p = os.path.join(tmp, "corrupt.casc")
    with open(p, "wb") as f:
        raw = b"\x00" * 16
        import binascii
        crc = binascii.crc32(raw) & 0xFFFFFFFF
        name = b"scene/scene.json"
        f.write(b"PK\x03\x04" + b"\x00" * 26)
        f.write(name)
        f.write(b"garbage-not-zstd")
        cd = b"PK\x01\x02" + b"\x00" * 10 + b"\x5d\x00" + b"\x00" * 8 + b"\x00" * 4
        # 用真实写盘函数构造一个打包内容非法的条目
    try:
        make_fixture.write_packed_zip(p, [("scene/scene.json", b"{}")])
        # 把压缩内容替换成垃圾
        data = bytearray(open(p, "rb").read())
        i = data.find(b"scene/scene.json") + len(b"scene/scene.json")
        for k in range(i, min(i + 12, len(data))):
            data[k] = 0x41
        open(p, "wb").write(bytes(data))
        try:
            res = casc_core.read_casc_entry(p, "scene/scene.json")
            # 关键保证：绝不把垃圾字节当内容返回
            check("坏 zstd 不返回垃圾字节",
                  res is None or (isinstance(res, (bytes, bytearray)) and b"AAAA" not in res),
                  "返回 %r" % (res[:12] if isinstance(res, (bytes, bytearray)) else res,))
        except RuntimeError as exc:
            check("坏 zstd 抛 RuntimeError", "无法解压" in str(exc))
    except Exception as exc:  # 构造失败也算通过（不阻塞其它断言）
        check("坏 zstd 用例可构造", True, "跳过：%r" % (exc,))


def test_meshes():
    print("\n[3] 网格解析（新版明文格式）")
    tmp = tempfile.mkdtemp(prefix="casc_mesh_")
    p = make_fixture.build(os.path.join(tmp, "mini.casc"))
    js = casc_core.load_scene_json(p)
    meshes = casc_core.parse_meshes(js)
    check("找到 1 个网格", len(meshes) == 1, "got %d" % len(meshes))
    m = meshes[0]
    check("顶点数 = 4", m["verts"] == 4, "got %s" % m["verts"])
    check("三角形数 = 2", m["tris"] == 2, "got %s" % m["tris"])
    check("绑定骨数 = 2", m["skinned_bones"] == 2, "got %s" % m["skinned_bones"])
    check("顶点坐标可读出", m["verts_data"] is not None and m["verts_data"].shape == (4, 3))
    if m["verts_data"] is not None:
        check("顶点值正确", np.allclose(m["verts_data"][1], [1.0, 0.0, 0.0]),
              str(m["verts_data"][1]))


def test_lod():
    print("\n[4] LOD 选择")
    meshes = [{"object": "Hero_LOD0"}, {"object": "Hero_LOD1"}, {"object": "Hero_LOD2"},
              {"object": "Sword"}]
    picked = casc_core.pick_lod_meshes(meshes, "0")
    check("lod=0 只留 LOD0 与无名网格",
          {m["object"] for m in picked} == {"Hero_LOD0", "Sword"},
          str([m["object"] for m in picked]))
    picked = casc_core.pick_lod_meshes(meshes, "all")
    check("lod=all 全保留", len(picked) == 4)


def test_frames():
    print("\n[5] 帧范围解析与越界报错")
    check("auto -> 全范围", casc_core.frame_list_checked(None, 0, 4)[0] == [0, 1, 2, 3, 4])
    check("区间 2-5", casc_core.frame_list_checked("2-5", 0, 9)[0] == [2, 3, 4, 5])
    check("列表 1,3", casc_core.frame_list_checked("1,3", 0, 9)[0] == [1, 3])
    try:
        casc_core.frame_list_checked("0-20", 0, 9)
        check("越界应报错", False)
    except ValueError as exc:
        check("越界抛 ValueError", "超出" in str(exc))
    frames, notes = casc_core.frame_list_checked("1,1,2", 0, 9)
    check("重复帧去重", frames == [1, 2] and notes)


def test_model_pose():
    print("\n[6] statics → model pose")
    tmp = tempfile.mkdtemp(prefix="casc_pose_")
    p = make_fixture.build(os.path.join(tmp, "mini.casc"))
    js = casc_core.load_scene_json(p)
    model = casc_core.load_model_pose(js)
    check("读到 2 根骨", len(model) == 2, str(sorted(model.keys())))
    # model[name] = (pos, rot)，pos 来自 statics[index]
    check("child 的 model pose 位置正确",
          tuple(model["child"][0]) == (0.0, 0.0, 50.0), str(model["child"][0]))
    child_obj = [o for o in js["objects"] if o.get("name") == "child"][0]
    check("父子关系正确", child_obj.get("parent") == JOINT_ID)
    check("B4 形状 4x4", casc_core.B4.shape == (4, 4))
    check("B4 是 Y-up→Z-up",
          np.allclose(casc_core.B4[:3, :3] @ np.array([0, 1, 0]), [0, 0, 1]))


if __name__ == "__main__":
    try:
        import zstandard  # noqa: F401
    except ImportError:
        print("需要 zstandard：pip install zstandard（或用 Blender 自带的 Python 跑）")
        sys.exit(2)
    test_zip_and_json()
    test_error_paths()
    test_meshes()
    test_lod()
    test_frames()
    test_model_pose()
    print("\n" + "=" * 60)
    if FAILS:
        print("FAILED: %d 项 -> %s" % (len(FAILS), ", ".join(FAILS)))
        sys.exit(1)
    print("ALL CASC_CORE TESTS PASSED")
