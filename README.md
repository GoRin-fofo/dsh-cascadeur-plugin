# @dsh-external/dsh-cascadeur-plugin

把 **Cascadeur 的 `.casc` 动画**搬进 **Blender / UE5**。

> 原理：通过 Cascadeur 内置的 **MCP 脚本服务器**（`127.0.0.1:8765`）读取每个关节的
> `Global Matrix`，在 Blender 里用**原版 FBX** 重建姿势，再导出 FBX。
> 不修改、不破解 Cascadeur 的任何授权机制。
>
> **精度：逐顶点误差 0.000 cm**（与 Cascadeur 自己的 `calc_skinned_mesh` 对比）。

---

## 一、前置条件

| 项 | 要求 |
|---|---|
| Cascadeur | 任意版本（含免费版）；需要**手动开一次**脚本服务器 |
| Blender | 5.x（Python 需带 `zstandard`；5.4 已自带） |
| 原版模型 FBX | 当初导入 Cascadeur 用的那个 FBX（**不要用改过的**） |
| DSH | 0.1.7+ |

### 开 Cascadeur 脚本服务器（唯一的手动步骤）

Cascadeur 菜单栏 → **Scripts** → **MCP** → **Start script server**

开一次就行，插件每次导出都会用它。没开的话工具会明确提示你去开。

---

## 二、工具

| 工具 | 用途 |
|---|---|
| `casc_status` | 环境自检：Cascadeur 是否可达 / Blender 路径 / 当前设置 |
| `casc_inspect` | 只读解析 `.casc`：角色、骨骼、帧范围、LOD、分层。**不需要开 Cascadeur** |
| `casc_dump` | 只导出动画数据（Global Matrix → JSON） |
| `casc2blend` | **一条龙**：读 → 重建 → `.blend` |
| `casc2fbx` | **一条龙**：读 → 重建 → `.fbx`（可直接进 UE5） |
| `casc_verify` | 验证：骨骼位置 vs Cascadeur 数据（正常 < 0.01 cm） |
| `casc_config` | 读写默认设置（持久化，后续导出默认用它） |

---

## 三、典型用法

### 1. 先配置一次（之后一直生效）

```
casc_config({ set: {
  modelFbx: "D:\\path\\to\\your_original_model.fbx",
  outDir:   "D:\\path\\to\\output",
  lod:      "0"
}})
```

> `modelFbx` 必须是**当初导入 Cascadeur 用的那个原始 FBX**（不要用后来改过的）。
> `outDir` 留空则默认输出到 `<casc 所在目录>/casc_out`。

设置存在 `~/.dsh/cascadeur-settings.json`，**不改变就一直按它来**。

### 2. 看一眼 .casc 里有什么

```
casc_inspect({ casc_path: "D:\\path\\to\\scene.casc" })
```

返回：角色列表（含顶点数、蒙皮骨骼数）、关节数、帧范围、FPS、动画分层。

### 3. 一条龙导出

```
casc2fbx({ casc_path: "D:\\path\\to\\scene.casc" })
```

返回：帧数、关节数、LOD、`rest_err_cm`（应 ~0.0001）、
`bone_pos_err_cm`（应 ~0.0001）、FBX 路径与大小。

### 4. 验证

```
casc_verify({ casc_path: "D:\\...\\scene.casc" })
```

---

## 四、设置项

| 键 | 说明 | 默认 |
|---|---|---|
| `blenderExe` | Blender 路径 | 自动探测（复用 dsh-blender-plugin 的配置） |
| `modelFbx` | 原版模型 FBX | **空**（必须先配置） |
| `lod` | 网格 LOD：`0` / `all` / `0,2` | `0` |
| `outDir` | 默认输出目录 | `<casc 同目录>/casc_out` |
| `frames` | 帧范围：`auto` / `0-10` | `auto`（用场景时间轴范围） |
| `character` | 保留（多角色场景用） | `auto` |
| `autoVerify` | 保留 | `true` |

---

## 五、核心公式（不要改）

```python
B4 = [[1,0,0,0],[0,0,-1,0],[0,1,0,0],[0,0,0,1]]   # Y-up → Z-up

W_rest[joint] = W_rest[parent] @ (T(pos) @ Euler(rot,'ZYX').to_matrix())
A(t) = B4 @ M_global(t)          # ⚠️ 只左乘！@ B4.T 会多转 90°，整模扭曲
D(t) = A(t) @ inv(W_rest[joint])
pose_bone.matrix = D(t) @ bone.matrix_local
```

> **踩过的坑**：`B4 @ M @ B4.T`（相似变换）会给每根骨加 90° roll，
> 表现是"每个关节都在扭"，但所有位置检查都通过（位置永远是对的）——
> 这个 bug 曾让整个项目卡了十几个小时。诊断方法：
>
> ```
> rest(stastics) ↔ Blender bind  = ~0°   ← 正常
> GM(绑定帧)     ↔ Blender bind  = 90°   ← 说明 B4 用错了
> ```

---

## 六、安装 / 卸载

安装（把包加入 DSH profile）：

```powershell
# 1. profile 的 package.json 里加依赖 + bundle（脚本会自动备份）
# 2. node_modules 里建 junction 指向本目录
# 3. 重启 DSH
```

见 `install.ps1` / `uninstall.ps1`。

---

## 七、限制

- **不**跨机器：读的是本机 Cascadeur 的实时数据
- 一个 `.casc` 里多个角色时，当前导出所有蒙皮网格（`character` 参数预留）
- 动画节奏按 30fps 假设（Cascadeur 默认）；非 30fps 场景会从 `scene_settings.json` 读取
- 不做 IK 重解算：直接使用 Cascadeur 求值后的 `Global Matrix`（这就是精确的原因）
