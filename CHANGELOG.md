# 变更记录

## v0.3.0 — 2026-10-27

### 新增

- **关键帧简化**（`runtime/keyreduce.py`）
  - 误差驱动：反复挑"用相邻关键帧插值后误差最大"的帧，直到全帧误差 ≤ 阈值
  - `casc2blend` / `casc2fbx` 新增参数 `reduce_keys`、`key_threshold`
  - 设置项新增 `reduceKeys` / `keyThreshold` / `fps`
  - 简化后自动把关键帧插值设为 **Bezier（AUTO_CLAMPED）**，不会过冲
  - 回执新增 `reduce` 字段：`dense` / `keys` / `ratio_pct` / `mean_err_deg` /
    `max_err_deg` / `bezier_fcurves`
  - 实测：612 帧 Mocap → 137 帧（22.4%），平均误差 1.58°、最大 3.19°

- **支持两种 `.casc` 网格资产格式**
  - 旧：base64 二进制 `mesh` blob
  - 新：明文 `vertices` / `normals` / `texture_coords` / `triangles_vertex_indices`
  - 视频对象（无几何）自动跳过，不再报 `KeyError: 'mesh'`

- **导出 FPS 可配置**（`--fps`），Mocap 视频通常是 25

### 修复

- `parse_meshes` 遇到视频对象崩溃
- `keyreduce.slerp` 未做批量处理（`(B,4)` 数组被当成矩阵乘）
- Blender 4.4+ slotted action 的 `fcurves` 访问兼容（用于设置 Bezier）

---

## v0.2.0 — 2026-10-26

### 新增

- **Cascadeur MCP 自动启动**（`cascadeur_autostart/`）
  - 把 `autostart.py` 复制到 Cascadeur 的 `resources/scripts/python/scripts/mcp/`
  - 之后每次启动 Cascadeur 都会自动开 `127.0.0.1:8765`，不用再点菜单
  - 原理：Cascadeur 启动时会 `pkgutil.walk_packages` 递归 import `scripts/` 下每个模块
  - 约 60 秒（场景就绪后）可用；日志写 `%TEMP%\dsh_mcp_autostart.log`
  - 环境变量 `DSH_MCP_AUTOSTART=0` 可关闭；删文件即卸载
  - 不修改任何官方文件，不涉及授权

### 变更

- `casc_status` / 连不上服务器时的提示改为「手动点菜单」和「装自动启动」两种方案
- README 增加自动启动说明

### 已知坑

- 自动启动场景下，脚本里**必须用注入的 `scene` 变量**；
  用 `current_scene()` 可能拿到 `csc.view.Scene`（没有 `model_viewer`）

---

## v0.1.0 — 2026-10-21

首个版本。

- 7 个工具：`casc_status` / `casc_inspect` / `casc_dump` /
  `casc2blend` / `casc2fbx` / `casc_verify` / `casc_config`
- 设置持久化到 `~/.dsh/cascadeur-settings.json`
- 核心链路：Cascadeur `Global Matrix` → Blender 原版 FBX 重建 → 导出 FBX
- 精度：重建蒙皮网格与 Cascadeur `calc_skinned_mesh` **逐顶点 0.000 cm**
- 关键公式：`A = B4 @ M`（只左乘；相似变换会多转 90° 导致整体扭曲）
