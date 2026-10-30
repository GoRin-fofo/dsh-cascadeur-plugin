# Contributing

Thanks for taking the time to contribute! This is a small plugin with a strict rule:
**every headline claim must be executable.**

## Ways to help

- Bug reports: use the [bug report template](.github/ISSUE_TEMPLATE/bug_report.yml) and include
  your environment (OS, Cascadeur version, Blender version, DSH version) plus the exact tool call.
- Feature requests: open an issue describing the workflow, not just the API.
- Pull requests: keep them focused. One behaviour change per PR.
- Documentation: typo fixes and clearer troubleshooting notes are always welcome.

## Development setup

Requirements: Node.js ≥ 20, Python ≥ 3.11 (`numpy`, `zstandard`), Blender 5.x, and a Cascadeur
installation for end-to-end work.

```bash
git clone https://github.com/GoRin-fofo/dsh-cascadeur-plugin.git
cd dsh-cascadeur-plugin

# Node-side unit tests (no DSH, no Blender needed)
node tests/test_core.mjs
node tests/test_packaging.mjs

# Python-side tests (numpy + zstandard)
python tests/test_keyreduce.py
python tests/test_casc_core.py
```

The accuracy assertion needs a real `.casc` file and the original FBX (they are user assets,
so they are not in the repo):

```bash
blender -b --factory-startup --python verify/verify_rebuild.py -- \
  --casc scene.casc --gm scene_gm.json --model-fbx Model.fbx --tolerance-cm 0.01
```

## Before opening a PR

- [ ] `node tests/test_core.mjs` and `node tests/test_packaging.mjs` pass
- [ ] `python tests/test_keyreduce.py` and `python tests/test_casc_core.py` pass
- [ ] If you touched `keyreduce` / `casc_core` / `constraints`, run the accuracy check above
- [ ] `CHANGELOG.md` has an entry under the new version (same version as `package.json`)
- [ ] No new file needs to be added to `package.json#files` unless it ships at runtime

## Code style

- The runtime is plain JavaScript (ESM) and Python; keep it dependency-free beyond `numpy` / `zstandard`.
- Do not embed Chinese-only strings in error messages that JS tools surface to agents — both languages
  are welcome, but the actionable part must be language-neutral (a code, a path, a command).
- The core formulas in `README.md` §5 and `AGENTS.md` are load-bearing: read them before touching matrices.

## Commit messages

Conventional Commits are appreciated but not enforced: `feat:`, `fix:`, `docs:`, `test:`, `ci:`.

## Release process (maintainers)

1. `npm version patch|minor|major` (updates `package.json`, creates a commit and a tag)
2. Add the matching `## vX.Y.Z` section to `CHANGELOG.md`
3. `git push --follow-tags`
4. `.github/workflows/publish.yml` publishes to npm and creates the GitHub Release

## 中文摘要

- 提交前跑 `node tests/test_core.mjs`、`node tests/test_packaging.mjs`、`python tests/test_keyreduce.py`、`python tests/test_casc_core.py`
- 改到矩阵/关键帧逻辑时，务必用真实 `.casc` + 原版 FBX 跑一次 `verify/verify_rebuild.py`
- `CHANGELOG.md` 的版本号要和 `package.json` 一致；一个 PR 只做一件事
