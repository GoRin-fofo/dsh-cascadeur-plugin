# 变更记录

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
