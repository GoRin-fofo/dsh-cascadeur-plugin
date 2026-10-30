## What does this PR do?

<!-- One or two sentences. Link the issue it fixes: Fixes #123 -->

## Type

- [ ] Bug fix
- [ ] Feature
- [ ] Documentation
- [ ] CI / packaging

## How was it verified?

- [ ] `node tests/test_core.mjs`
- [ ] `node tests/test_packaging.mjs`
- [ ] `python tests/test_keyreduce.py`
- [ ] `python tests/test_casc_core.py`
- [ ] Accuracy run (only if keyreduce / casc_core / matrix logic changed):
      `blender -b --factory-startup --python verify/verify_rebuild.py -- --casc ... --model-fbx ...`

## Checklist

- [ ] `CHANGELOG.md` updated (version matches `package.json`)
- [ ] No new runtime file omitted from `package.json#files`
- [ ] Comments/docs explain non-obvious conventions (see `AGENTS.md`)
- [ ] I did not weaken the "0.000 cm" assertion or the `violations` report to make tests pass
