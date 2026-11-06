# Releasing to PyPI

OpenTCAD builds as a standard wheel and source package. Publishing is a
maintainer step that needs your PyPI account; nothing in the repo uploads
automatically.

## Checked on 2026-11-06 (version 0.1.0.dev0)

- `python -m build` produces `opentcad-0.1.0.dev0-py3-none-any.whl` (72
  files) and an sdist. Both pass `twine check`.
- **Wheel contents:** the package, its data tables (materials,
  implant/diffusion) and the example simulation files under
  `opentcad/_examples/decks/`, which are also the assistant's templates
  (see `opentcad.io.deck.example_decks_dir`). It also provides the
  `opentcad` command.
- **Dependencies:** numpy, scipy, pyvista, pydantic, gmsh, devsim,
  matplotlib, pyyaml. The extras are `topography` (ViennaLS, whose current
  wheels are GPL v3, so it's kept optional), `gui` (streamlit, plotly) and
  `dev`.
- **Clean install check:** a fresh Python 3.14 venv with only the wheel, so
  no ViennaLS.
  - `opentcad check` and `opentcad run` work on the packaged examples.
  - The diode current matches the source tree.
  - The NMOS example runs (its recipe is doping-only).
- **Tests from the sdist against that install:** 287 passed, 12 skipped
  (topography tests skip without ViennaLS, Plotly tests without the `gui`
  extra), 0 failed, slow tests excluded. `tests/integration` is left out of
  the sdist because it exercises the microrobot application in `examples/`,
  which isn't part of the library.
- The name `opentcad` had no distribution on PyPI.

## Before the first upload

- README links are relative (`examples/…`, `docs/…`). They work on GitHub
  but will 404 on the PyPI project page. Make them absolute GitHub URLs, or
  rewrite them at build time.
- Pick the version (`project.version` in `pyproject.toml`; PEP 440, e.g.
  `0.1.0`).
- Check again that the name is free, and decide who owns the PyPI project.

## Steps

```bash
git clone https://github.com/abhineet-agarwal/opentcad.git && cd opentcad
# (a clean clone: untracked files in docs/ would otherwise go into the sdist)
python -m pip install build twine
python -m build
python -m twine check dist/*

# smoke test in a fresh environment
python -m venv /tmp/otc && /tmp/otc/bin/pip install dist/*.whl
EX=$(/tmp/otc/bin/python -c "from opentcad.io.deck import example_decks_dir; print(example_decks_dir())")
/tmp/otc/bin/opentcad check "$EX/nmos_implanted.yaml"
/tmp/otc/bin/opentcad run "$EX/pn_diode.yaml" -o /tmp/diode.json

# upload (your API token): TestPyPI first, then PyPI
python -m twine upload --repository testpypi dist/*
python -m twine upload dist/*
```
