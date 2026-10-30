# @dsh-external/dsh-cascadeur-plugin

**English** | [简体中文](README.zh-CN.md)

Move **Cascadeur `.casc` animations** into **Blender / UE5**.

> How it works: read each joint's **`Global Matrix`** through Cascadeur's built-in
> **MCP script server** (`127.0.0.1:8765`), rebuild the pose in Blender on the
> **original FBX**, then export FBX. It does not modify or bypass any of
> Cascadeur's licensing mechanisms.
>
> **Accuracy: 0.000 cm per-vertex error** (compared against Cascadeur's own `calc_skinned_mesh`).
> That number is not a promise on trust: `verify/verify_rebuild.py` turns it into an
> executable assertion (see §Verification).

<p align="center">
  <img src="docs/demo.gif" width="1000" alt="Cascadeur .casc → rebuilt in Blender → FBX (612-frame fencing mocap)">
</p>

<p align="center">
  <sub>Left: Cascadeur playing the <code>.casc</code> (the inset is the reference video driving it)　·　Right: the rebuilt <code>.blend</code> / exported <code>.fbx</code> in Blender</sub><br>
  <sub>Same 612-frame fencing mocap, frame-synced. Full 30 fps version: <a href="docs/demo.mp4">docs/demo.mp4</a></sub>
</p>

---

## 1. Prerequisites

| Item | Requirement |
|---|---|
| Cascadeur | Any version (Free included); its script server must be running (automatable, see below) |
| Blender | 5.x (its Python must ship `zstandard`; 5.4 bundles it) |
| Original model FBX | The very FBX that was imported into Cascadeur (**not a modified copy**) |
| DSH | 0.1.7+ |

### Starting the Cascadeur script server

**Option A (manual, fastest)**

Cascadeur menu bar → **Scripts** → **MCP** → **Start script server**

**Option B (automatic, configure once)**

Copy [`cascadeur_autostart/autostart.py`](cascadeur_autostart/) into
`<Cascadeur install dir>\resources\scripts\python\scripts\mcp\`;
from then on every Cascadeur launch opens port 8765 by itself (ready in ~60 s).

See [cascadeur_autostart/README.md](cascadeur_autostart/README.md) for details.

> If the server is not running, the tools tell you exactly how to start it.

---

## 2. Tools

| Tool | Purpose |
|---|---|
| `casc_status` | Environment check: is Cascadeur reachable / Blender path / current settings |
| `casc_inspect` | Read-only `.casc` parsing: characters, bones, frame range, LODs, layers. **Cascadeur does not need to be running** |
| `casc_dump` | Dump animation data only (`Global Matrix` → JSON) |
| `casc2blend` | **One-shot**: read → rebuild → `.blend` (keyframe reduction optional) |
| `casc2fbx` | **One-shot**: read → rebuild → `.fbx` (UE5-ready) |
| `casc_verify` | Verify: bone positions vs Cascadeur data (normally < 0.01 cm) |
| `casc_config` | Read/write default settings (persisted; later exports use them) |

---

## 3. Typical usage

### 1. Configure once (applies from then on)

```
casc_config({ set: {
  modelFbx: "D:\\path\\to\\your_original_model.fbx",
  outDir:   "D:\\path\\to\\output",
  lod:      "0"
}})
```

> `modelFbx` must be the **original FBX that was imported into Cascadeur** (not a later modified one).
> Leave `outDir` empty to default to `<directory of the .casc>/casc_out`.

Settings live in `~/.dsh/cascadeur-settings.json` and are used until you change them.

### 2. Inspect a .casc

```
casc_inspect({ casc_path: "D:\\path\\to\\scene.casc" })
```

Returns: character list (vertex counts, skinned bone counts), joint count, frame range, FPS, animation layers.

### 3. One-shot export

```
casc2fbx({ casc_path: "D:\\path\\to\\scene.casc" })
```

Returns: frame count, joint count, LOD, `rest_err_cm` (should be ~0.0001),
`bone_pos_err_cm` (should be ~0.0001), FBX path and size.

**Enabling keyframe reduction** (recommended for Mocap results):

```
casc2fbx({
  casc_path: "D:\\path\\to\\scene.casc",
  reduce_keys: true,     // write only the error-driven keyframes + Bezier(AUTO_CLAMPED)
  key_angle: 2.0,        // allowed max mean angular error (degrees)
  key_pos: 2.0,          // allowed max mean positional error (cm)
  min_gap: 1,            // minimum spacing between keyframes
  despike: true          // repair Mocap single-frame spikes first
})
```

The result then also contains:

- `despike`: `fixed_frames` (frames that were repaired) / `rounds` / `converged`
- `reduce`: `dense` / `keys` / `ratio_pct` / `key_angle_deg` / `key_pos_cm` /
  `min_gap` / `violations` (**actual** frames over threshold) / `mean_angle_err` /
  `max_angle_err` / `mean_pos_err_cm` / `max_pos_err_cm` / `bezier_fcurves`
- `gm`: `cached` (whether the GM cache was reused) / `path`
- `matched_bones` / `missing_bones` / `unmatched_fbx_bones` (reported explicitly when bone names do not line up)

> Only `violations = 0` means "every frame satisfies the thresholds".

### 4. Verify

```
casc_verify({ casc_path: "D:\\...\\scene.casc" })
```

It asserts `rest_err_cm` and `bone_pos_err_max_cm` ≤ 0.01 cm and checks that every bone name
matches (missing bones → `ok=false`). The same assertion can run standalone:

```bash
blender -b --factory-startup --python verify/verify_rebuild.py -- \
  --casc scene.casc --gm scene_gm.json --model-fbx Model.fbx --tolerance-cm 0.01
```

It prints a markdown table and exits non-zero on failure, so it drops straight into CI.

---

## 4. Settings

| Key | Meaning | Default |
|---|---|---|
| `blenderExe` | Blender path | auto-detected (reuses dsh-blender-plugin's config) |
| `modelFbx` | original model FBX | **empty** (must be configured first) |
| `lod` | mesh LOD: `0` / `all` / `0,2` | `0` |
| `outDir` | default output directory | `<next to the .casc>/casc_out` |
| `frames` | frame range: `auto` / `0-10` | `auto` (scene timeline range) |
| `reduceKeys` | enable keyframe reduction by default | `false` |
| `keyAngleDeg` | allowed max mean angular error (degrees) | `2.0` |
| `keyPosCm` | allowed max mean positional error (cm) | `2.0` |
| `keyMinGap` | minimum spacing between keyframes (1 = adjacent frames allowed) | `1` |
| `despike` | automatically repair Mocap single-frame spikes | `true` |
| `fps` | export frame rate (Mocap video is usually 25) | `30` |

---

## 5. Core formulas (do not change)

```python
B4 = [[1,0,0,0],[0,0,-1,0],[0,1,0,0],[0,0,0,1]]   # Y-up → Z-up

W_rest[joint] = W_rest[parent] @ (T(pos) @ Euler(rot,'ZYX').to_matrix())
A(t) = B4 @ M_global(t)          # ⚠️ LEFT-multiply only! @ B4.T adds an extra 90° and twists the whole model
D(t) = A(t) @ inv(W_rest[joint])
pose_bone.matrix = D(t) @ bone.matrix_local
```

> **The trap we hit**: `B4 @ M @ B4.T` (a similarity transform) adds a 90° roll to every bone.
> The symptom is "every joint is twisting", while all position checks still pass
> (positions are always correct). This bug cost this project a dozen-plus hours.
> How to diagnose it:
>
> ```
> rest(statics)   ↔ Blender bind  = ~0°    ← normal
> GM(bind frame)  ↔ Blender bind  = 90°    ← B4 is being applied wrong
> ```

---

## 6. Keyframe reduction (essential for Mocap results)

Cascadeur's Video-mocap writes **per-frame keys** (612 frames in our sample), with human-estimation jitter.
Using that directly feels bad and is hard to edit. The plugin ships **error-driven** keyframe reduction:

```
Start from [first frame, last frame]
→ for every frame, compute the error of interpolating from its neighbouring keyframes
  (angle and position are normalised separately)
→ add the frame with the largest normalised violation as a keyframe
→ repeat until max(angle/threshold, position/threshold) ≤ 1 for every frame
```

This is steadier than "speed only": **slow but articulated passages (a slow sword withdrawal) are not thrown away**.

### Measured (612-frame fencing Mocap, after repairing 5 spike frames)

| Angle threshold | Position threshold | Keyframes | Ratio | Measured max error | Violations |
|---|---|---|---|---|---|
| 1.0° | 0.5 cm | 355 | 58% | 0.97° / 0.49 cm | 0 |
| 1.5° | 1.0 cm | 257 | 42% | 1.47° / 0.99 cm | 0 |
| **2.0°** | **2.0 cm** | **184** | **30%** | **1.97° / 1.97 cm** | **0** |
| 3.0° | 3.0 cm | 142 | 23% | 2.96° / 2.78 cm | 0 |
| 5.0° | 5.0 cm | 100 | 16% | 4.88° / 4.98 cm | 0 |

(`min_gap=1`; raising `min_gap` cuts more frames but sacrifices accuracy — it is a hard constraint.)

### Mocap spike repair

Mocap occasionally has **single-frame tracking failures**: that frame jumps tens of centimetres and comes back.
Left unfixed, the FBX shows a visible twitch.

```
detect_spikes: per-frame displacement vs a local rolling median;
               ratio > 4 lasting ≤ 8 frame gaps → classified as a spike
repair_spikes: replace with interpolation from the neighbouring frames, iterate until convergence
```

On the 612-frame sample above, `257, 258, 259, 597, 598` were detected and repaired
(worst angular error before repair: 27.7°; after: 1.97°). The repaired frame numbers are reported in
`despike.fixed_frames` — nothing is changed silently.

How to enable:

```
casc2fbx({ casc_path: "...", reduce_keys: true, key_angle: 2.0, key_pos: 2.0, despike: true })
```

Or persist it in the defaults: `casc_config({set:{reduceKeys:true, keyAngleDeg:2.0, keyPosCm:2.0}})`.

> In `.blend` you get sparse Bezier keys (hand-editable);
> `.fbx` is baked per frame (engine-friendly), but the bake follows the **Bezier curve**, so it stays smooth.

---

## 7. Feeding video into Cascadeur's Mocap (gotchas)

### Gotcha 1: the video time base makes "only the first frame is correct"

QuickTime video often has a `time_base` of `1/12800`; at 25 fps each frame is 512 time units.
When Cascadeur extracts frames it names them by **time code** (`000000.jpg, 000512.jpg, 001024.jpg ...`),
but when reading them back it looks them up by **frame index** (`000001.jpg, 000002.jpg ...`)
→ only frame 0 lines up.

**Fix**: re-encode before importing so the time base equals the frame rate:

```bash
ffmpeg -i original.mp4 -c:v libx264 -crf 16 -r 25 -video_track_timescale 25 -an fixed.mp4
```

### Gotcha 2: two storage formats for mesh assets inside `.casc`

| Format | Fields | Notes |
|---|---|---|
| Old | `mesh` (base64 binary blob) | `[ver][count][16B/vertex][indices]` |
| New | `vertices` / `normals` / `texture_coords` / `triangles_vertex_indices` | plain arrays |

Both are supported; video objects (no geometry data) are skipped automatically.

### Gotcha 3: Mocap is local CPU inference and eats memory

The model is 787 MB (`resources\mocap.pt`) and must be downloaded on first use;
~700 frames take about 23 minutes (i5-10500H, 6 cores) and peak memory exceeds 9 GB, which can trip
Cascadeur's 6 GB limit and **wipe the undo history**. Split long clips into chunks.

---

## 8. Install / uninstall

Install (add the package to a DSH profile):

```powershell
# 1. add the dependency + bundle entry to the profile's package.json (the script backs up first)
# 2. create a junction in node_modules pointing at this directory
# 3. restart DSH
```

See `install.ps1` / `uninstall.ps1`.

---

## 9. Verification & tests

```bash
# Node-side pure logic (28 assertions; no DSH / Blender required)
node tests/test_core.mjs          # or npm test

# Keyframe reduction (12 assertions; --bench runs the real 612-frame data)
python tests/test_keyreduce.py

# .casc parsing (25 assertions; needs numpy + zstandard, or Blender's bundled Python)
python tests/test_casc_core.py
```

Accuracy acceptance (needs a real `.casc` + the original FBX; not part of CI):

```bash
blender -b --factory-startup --python verify/verify_rebuild.py -- \
  --casc scene.casc --gm scene_gm.json --model-fbx Model.fbx --tolerance-cm 0.01
```

CI: `.github/workflows/ci.yml` (Windows runner) runs the three suites above plus `ast.parse` over every script.

> Read [`AGENTS.md`](AGENTS.md) before changing code — it lists the things that bite as
> symptom → code location (left-multiply-only B4, bone-name matching, frame-range semantics,
> keyreduce unit mixing, Mocap spikes, the BOM ban, ...).

---

## 10. Limitations

- **Not** cross-machine: it reads live data from Cascadeur on the same machine.
- With several characters in one `.casc`, all skinned meshes are exported (`lod` only affects
  meshes whose names carry a LOD suffix; prop meshes are always kept; `MeshObject(N)`
  reference-video planes with ≤ 4 vertices are skipped automatically).
- Timing assumes 30 fps (Cascadeur's default); non-30 fps scenes are read from `scene_settings.json`.
- No IK re-solve: it uses Cascadeur's evaluated `Global Matrix` as-is (that is exactly why it is accurate).
- `keyreduce`'s `min_gap` is a hard constraint: setting it too high invalidates the threshold
  promise (the `violations` field in the result reports it honestly).
