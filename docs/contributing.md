# Contributing to OpenTCAD

OpenTCAD is built to be continued by others. This guide is everything you need
to make a change that will be accepted: how to set up, the ground rules, how to
add each kind of extension, and where help is most useful.

## Set up

```bash
git clone https://github.com/abhineet-agarwal/opentcad.git && cd opentcad
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev,topography,gui]"
pytest tests -q -m "not slow"           # a few minutes
```

All three extras give the full environment; the core works without `topography`
and `gui` ([Architecture](architecture.md#optional-dependencies)).

### Running tests

```bash
pytest tests -q                          # everything (~8 min; the SKY130 check is the slowest)
pytest tests -q -m "not slow"            # skip the long end-to-end checks
pytest tests/device -q                   # one area
pytest -m requires_devsim -q             # only DEVSIM-backed tests
```

- **Folders:** each area has its own: `geometry`, `process`, `device`,
  `materials`, `io`, `plugins`, `viz`, `assist`, `catalog`, `validation`, `gui`
  and `bridge`. `tests/integration` covers the microrobot application in
  `examples/`.
- **Markers:** `slow`, `requires_devsim`, `requires_viennaps` and `integration`,
  declared in `pyproject.toml`.
- **Optional backends:** tests that need ViennaLS or Streamlit skip when it's
  missing. Keep it that way for new tests (`pytest.importorskip`).
- **Docs:** `tests/docs` checks the documentation (see [Documentation](#documentation)).

## Ground rules

These are what a reviewer checks. They exist so results stay trustworthy as more
people contribute.

1. **Units are fixed:** µm, cm⁻³, K (device temperature), °C (process
   temperatures), eV, V. Name fields with their unit (`thickness_um`,
   `dose_cm2`). Convert at the boundary of the code that needs another unit.
2. **`MeshField` is the contract between layers.** Don't pass raw arrays between
   modules. If the contract needs a new field, extend `formats.py` deliberately
   and keep `save`/`load` lossless.
3. **Never invent values.**
   - A parameter in a data file needs its unit and a source in the file's
     `sources` and `cite` sections ([Sources and provenance](provenance.md));
     add an uncertainty where known. Runs list every value without one.
   - Missing inputs are an error or a flagged assumption, never a silent
     default. Loaders and checkers fail loudly with a message that says what to
     add.
   - Silicon's numbers are only silicon's.
4. **Physics needs evidence.**
   - A new model or process step comes with a test that compares it against an
     analytic result, a published table or a reference model, with a stated
     tolerance.
   - Add a row to [Validation](validation.md), including what the check does
     *not* show.
   - Approximations go in the docstring and the docs' "Limits" section.
5. **The core stays independent.**
   - `opentcad/` must not import `examples/` or application code.
   - Optional front ends (`gui/`, `assist/`) must not be imported by the core.
   - Optional backends are imported lazily.
6. **Extend through the registries.** New steps, analyses, physics models,
   metrics and data go through `opentcad.plugins`, as the built-ins do
   ([Plugins](plugins.md)).
7. **Check files, don't trust them.** Simulation files and catalog imports
   reject unknown keys and report every problem with its location. Keep new
   fields checkable.
8. **Update the docs with the code.** If behaviour changes, change the relevant
   page, regenerate the API reference, and add a
   [CHANGELOG](https://github.com/abhineet-agarwal/opentcad/blob/main/CHANGELOG.md) entry when results can change.

## How to add…

### A material

1. Add `opentcad/materials/params/<Symbol>.yaml`, following `Si.yaml`: units in
   comments, and a source for each value in the `sources` and `cite` sections
   (with a DOI where there is one). Leave a value uncited rather than guess;
   runs report it.
2. Give the required fields: `permittivity_relative`; for a semiconductor also
   the band structure, constant mobilities and SRH lifetimes. Add the model blocks
   (Klaassen, velocity saturation, Auger/radiative, avalanche) you have sources
   for. Models that need a missing block will refuse to run on it.
3. If it's a new region material, it needs a `Material` enum entry and a display
   name in `opentcad/geometry/formats.py`.
4. Test that it loads and that `defaulted` lists exactly what you left out
   (`tests/materials`).

Lab-specific variants go in `params/<process>/<Symbol>.yaml` and are selected with
`material_process` in simulation files.

### A dopant species

Add `<Sym>_in_Si.yaml` (Pearson moments vs energy, with sources) and
`<Sym>_diffusion.yaml` (intrinsic D₀, Eₐ, plus Fair coefficients if you have them)
to `opentcad/process/doping/data/` or to a registered data folder. The species name
and symbol become accepted names in `implant(...)`.

### A process step, analysis, physics model or metric

Write it as a plugin (a dataclass step with an `apply` handler; a function
`fn(solver, **kw)`; a model class; a metric `fn(result, **kw)`) and register it.
[Plugins](plugins.md) has a worked example of each, and packaging as an
installable plugin. Built-in additions register in
`opentcad/process/builtin_steps.py` and the `opentcad/device/builtin_*.py` files.

### An example or simulation file

Put scripts in `examples/` (numbered) and simulation files in `examples/decks/`.
State which values are illustrative stand-ins rather than real process data. Make
sure `opentcad check` passes.

## Good places to start

Real gaps, roughly from smallest to largest. Each is documented in the relevant
"Limits" section.

- **SRH trap level:** `Et_eV` in material files is ignored, and SRH assumes a
  mid-gap trap. Use it for n₁ and p₁, with a test against the analytic SRH rate.
- **More material files:** Si₃N₄ (insulator), poly-Si, SiGe, GaN, SiC, each with
  cited parameters.
- **Small-signal AC on ohmic/Schottky terminals:** route the continuity fluxes
  into the circuit node.
- **Avalanche:** replace the v_sat·n current proxy with the drift–diffusion
  |J_n|, |J_p| for calibrated breakdown voltages.
- **Lombardi:** a per-element interface-normal projection for curved interfaces.
- **Process physics:**
  - SiO₂ range tables for screen oxides.
  - Segregation at Si/SiO₂.
  - Doping interleaved with later topography.
- **Calibration (Phase 3):** an optimizer over sweep metrics against
  [`validation/sky130/nfet_01v8_tt_reference.json`](https://github.com/abhineet-agarwal/opentcad/blob/main/validation/sky130/nfet_01v8_tt_reference.json).
  Start with surface mobility.
- **ViennaPS backend** for physical etch and deposition. It needs a working
  build: test the Linux wheels, or build from source against one VTK/OpenMP on
  macOS.
- **GDS layout import:** build a `Structure` and masks from a layout file.

## Documentation

The documentation is the `docs/` folder. It is written for GitBook, which reads
it through Git Sync. `gitbook-docs.yaml` at the repository root maps the site's
one space to `docs/` (`.gitbook.yaml` does the same for a sync set up from a
single space), and `docs/SUMMARY.md` is the sidebar. Every page is plain Markdown, so it
also reads on GitHub.

- **Where pages go:**
  - Getting started, tutorials (`docs/tutorials/`), the user guide, the API
    reference (`docs/api/`), development and background. `SUMMARY.md` lists every
    page. A new page must be added there.
  - Link between pages with relative links. Link to anything outside `docs/`
    (source files, examples, images) with its GitHub URL, because GitBook can't see
    files outside `docs/`. The test maps those URLs back to local files and checks
    they exist.
- **The API reference is generated.** Don't edit `docs/api/` by hand. Write
  Google-style docstrings (`Args:`, `Returns:`, `Raises:`), add new public names
  to `PAGES` in `tools/gen_api_docs.py`, and run
  `python tools/gen_api_docs.py` (Python ≥ 3.14).
- **GitBook blocks** render on GitBook and show as plain text on GitHub. Use them
  sparingly:
  - `{% hint style="info" %}` … `{% endhint %}` for notes; `warning` and `danger`
    for things that can give wrong results.
  - `{% tabs %}` for alternatives, such as install variants.
- **`tests/docs` checks:**
  - every link and heading anchor resolves;
  - every page is in `SUMMARY.md`;
  - the quickstart, tutorial and visualization code runs;
  - `docs/api/` matches the code.

## Making the change

- Open an issue first for large changes, so the approach can be agreed.
- Keep a change focused, with tests, docs and (if results can change) a changelog
  entry.
- Run `pytest tests -q -m "not slow"` and `ruff check opentcad`.
- In the description, say what you checked and what you didn't.
