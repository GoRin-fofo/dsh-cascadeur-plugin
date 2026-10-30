# 变更记录

## v0.4.0 — 2026-10-30

按外部评审（REVIEW.md §6）修的「三件事」。核心原则：**把"宣称"变成"可验证"**。

### 新增

- **测试与 CI**
  - `tests/test_keyreduce.py`：6 组不依赖 Blender 的单测（静止/匀速/突变/阈值语义/
    min_gap/重建自洽），`--bench` 可跑真实 612 帧数据
  - `tests/test_core.mjs`：8 组 Node 侧单测（默认设置、参数归一化、优先级、
    CLI 参数拼装、LOD 解析、摘要格式、版本单一来源、打包完整性）
  - `lib/core.js`：把纯逻辑从 `index.js` 抽出，使 Node 侧可脱离 DSH 测试
  - `.github/workflows/ci.yml`：Windows runner 跑 `npm test` + Python 单测

- **`verify/verify_rebuild.py`**：把「0.000 cm」变成可执行断言
  - 断言 `rest_err_cm` / `bone_pos_err_max_cm` ≤ 阈值（默认 0.01 cm）
  - 输出 markdown 表格 + 非 0 退出码，可直接进 CI 或当验收脚本

- **Mocap 跳变修复**（`keyreduce.detect_spikes` / `repair_spikes`）
  - 检出单帧追踪失败（局部位移比 > 4 倍且持续 ≤ 8 帧），用前后帧插值替换
  - 迭代至收敛；修复帧号写进回执 `despike.fixed_frames`
  - 实测：612 帧数据里帧 257/258/259/597/598 是坏的，修完最大角度误差 27.7° → 1.97°

### 修复（评审指出的正确性问题）

- **keyreduce 阈值语义**：角度与位置**分开判定**（原来把厘米混进角度阈值）
  - 新增 `key_angle_deg`（默认 2.0）/ `key_pos_cm`（默认 2.0）
  - `min_gap` 冲突时**跳过该候选**继续找次优（原来直接 `break` 提前退出）
  - 停止条件改为**归一化违约度** `max(角度/阈值, 位置/阈值) > 1`，
    修掉"角度达标但位置超标"的帧被漏掉的问题
  - 统计给出真实超标数：**阈值承诺现在成立**（实测 violations=0）
- **性能**：全向量化，612 帧 × 88 骨 **51.4 s → 0.43 s**（120×）
- **GM 缓存失效**：缓存名带 `.casc` 的 size+mtime 与帧范围，写 `.meta.json` 旁证；
  过期自动重读，`--force` 可强制；回执带 `gm.cached`
- **隐式假设 → 显式断言**：回执新增 `matched_bones` / `missing_bones` /
  `unmatched_fbx_bones`；缺骨时 `ok=false`；`rotation_mode` 非 QUATERNION
  会被强制切换并告警
- **`parse_args`**：布尔开关不再吞掉下一个参数（原来 `i += 2` 会跳过），
  支持 `--key=value`
- **`--frames` 越界**：显式指定的帧超出时间轴范围时**报错**，不再静默回退全范围
- **`casc_core` 解压失败**：抛异常并带上下文，不再把压缩字节当 JSON 往下传
- 删掉 `fetch_gm` 里的无效判断、`b - 0` 之类死代码

### 文档

- 新增 `AGENTS.md`：核心公式 + 「会咬人」的约定（症状 → 代码位置）
- README 修正重复编号、失效链接、未实现设置项；补关键帧简化的权衡表

---

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
