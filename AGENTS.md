# AGENTS.md —— 给后续 agent / 协作者的「会咬人」约定

这个仓库的核心是一组**坐标与格式转换**。下面每条都配了「症状 → 去哪看」，
碰到奇怪现象先来这里对号，别从零开始猜。

---

## 1. 核心公式（改任何一行前先读）

```
B4 = [[1,0,0,0],[0,0,-1,0],[0,1,0,0],[0,0,0,1]]      # Y-up → Z-up

W_rest[joint] = W_rest[parent] @ (T(pos) @ Euler(rot,'ZYX').to_matrix())
A(t)  = B4 @ M_global(t)                              # ⚠️ 只左乘！
D(t)  = A(t) @ inv(W_rest[joint])
pose_bone.matrix = D(t) @ bone.matrix_local
```

**症状：每个关节都在扭，但所有位置检查都通过**
→ 说明你写成了 `B4 @ M @ B4.T`（相似变换）。位置永远对，旋转多 90°。
→ 代码：`runtime/casc_core.py` 的 `compose_rest_world` / `apply_pose`，
   `runtime/run_pipeline.py` 的 `rebuild`。

**自检**：`rest(stastics) ↔ Blender bind ≈ 0°` 且 `GM(绑定帧) ↔ bind ≈ 0°`；
如果第二个是 90°，就是 B4 用错了。

---

## 2. `.casc` 是 ZIP + Zstandard，且**网格资产有两种格式**

| 格式 | 字段 | 出现场合 |
|---|---|---|
| 旧 | `mesh`（base64 二进制） | Cascadeur 早期保存 |
| 新 | `vertices` / `normals` / `texture_coords` / `triangles_vertex_indices` | 新版本或另存后 |

**症状：`KeyError: 'mesh'`**
→ 遇到新版格式或视频对象（没有几何）。代码：`casc_core.parse_meshes`。

**症状：`zstandard` 解压报错**
→ 不要吞异常返回原始字节（会静默产出垃圾 JSON）。
→ 代码：`casc_core.read_casc_entry`，按 method 分派 93/8/0。

---

## 3. 骨骼名必须**完全一致**

**症状：重建出来的东西整体走样 / 完全不动**
→ `.casc` 里的关节名与 FBX 里的骨骼名对不上。回执里看
   `matched_bones` / `missing_bones` / `unmatched_fbx_bones`（v0.4.0 起有）。
→ 注意 Blender 会给重名骨骼加 `.001` 后缀。

**症状：keyframe 插了但动画不动**
→ `pose_bone.rotation_mode` 不是 `QUATERNION`，而代码只写
   `rotation_quaternion`。`rebuild` 会自动纠正并告警，别删这段。

---

## 4. 帧范围语义

* `timeline.json` 的 `StartFrame/EndFrame` 是**时间轴范围**，不是"有数据的帧"。
* `layers_viewer().frames_count()` 返回的可能是**有键的帧数**，不等于时间轴长度。
* 扩展时间轴：改 `.casc` 里的 `Data.EndFrame`（`Mocap` 前常用）。
* **不要**用 `Actions.Timeline.Increase scroll bar max frame`（只滚动，不改长度）。
* `Timeline.Expand selection left/right` 在时间轴末端会**顺带延长**时间轴。

---

## 5. 关键帧简化（keyreduce）的契约

* 判据是**两条**：`key_angle_deg`（度）与 `key_pos_cm`（厘米），**不能混用单位**。
* 停止条件是**归一化违约度** `max(角度/阈值, 位置/阈值) > 1`；
  改成"按加权分挑帧"会漏掉"角度达标但位置超标"的帧（v0.3.0 的 bug）。
* `min_gap` 是**硬约束**：它挡住候选时应**跳过该候选**继续找次优，
  直接 `break` 会让算法提前退出（v0.3.0 的 bug）。
* 输出必须带 `violations`（真实超标帧数）；`violations=0` 才配说"满足阈值"。

**症状：README 说"误差 ≤1.5°"但实测 40% 帧超标**
→ 就是上面两条之一。数据：`tests/test_keyreduce.py --bench`。

---

## 6. Mocap 数据有单帧跳变，先修再用

**症状：导出的 FBX 在某一帧"抽搐"**
→ Mocap 追踪失败的单帧。`keyreduce.detect_spikes`（局部位移比 > 4 且持续 ≤ 8 帧）
   + `repair_spikes`（前后帧插值），迭代至收敛。
→ 回执里 `despike.fixed_frames` 会有帧号。实测 612 帧样例里是 257/258/259/597/598。

---

## 7. 视频喂给 Cascadeur Mocap

**症状：只有第一帧正常**
→ 视频 `time_base=1/12800`，Cascadeur 抽帧按时间码命名（0,512,1024…），
   读取按帧序号。修复：`ffmpeg -i in.mp4 -c:v libx264 -crf 16 -r 25 -video_track_timescale 25 -an out.mp4`。

**症状：Mocap 说 "unrecognized poses"**
→ 视频没被正确读入；先确认帧随轴变化，再跑 Mocap。

**症状：Mocap 跑完内存爆 / 历史被清**
→ 787 MB 模型 + 视频纹理，峰值 9 GB+。分段跑，跑前重启 Cascadeur。

---

## 8. 环境硬约束

* **不要往 JSON 文件写 BOM**（`package.json` 带 BOM 会让 DSH 启动崩溃）。
  用 `[System.IO.File]::WriteAllText(path, text, UTF8Encoding($false))`。
* PowerShell 5.1 读 `.ps1` 按 GBK 解码：`.ps1` 里**只用 ASCII**。
* 动作 id **不带** `Actions.` 前缀：`View.MocapTool` ✓，`Actions.View.MocapTool` ✗。
* Blender 4.4+ 的 Action 没有 `action.fcurves`：要用
  `action.layers[].strips[].channelbags[].fcurves`（见 `iter_action_fcurves`）。

---

## 9. 改完必须跑

```bash
node tests/test_core.mjs          # JS 纯逻辑（28 项）
python tests/test_keyreduce.py    # 关键帧简化（12 项，--bench 跑真实数据）
python tests/test_casc_core.py    # .casc 解析（25 项，需要 numpy+zstandard）
```

带 Blender 的精度验收（需要真实资产，不进 CI）：

```bash
blender -b --factory-startup --python verify/verify_rebuild.py -- \
  --casc scene.casc --gm scene_gm.json --model-fbx Model.fbx --tolerance-cm 0.01
```

**任何声称"0.000 cm / ≤1.5°"的改动，都必须先让上面两件事通过再写进文档。**
