# Changelog

## Unreleased

### Behaviour changes that can alter results

- **Topography → device.** `run_recipe` now carries the structure's doping,
  contacts and metadata onto the processed mesh. Neighbouring materials there
  share their interface nodes, so the solver couples them.
  - Before, a mesh from topography steps was undoped and had no contacts.
  - Before, its materials were meshed separately: a deposited MOS capacitor
    gave C = 0. It now matches the layered device within 10 %.
- **Material files.** A missing required field raises `MaterialFileError`
  instead of taking silicon's value. Omitted model blocks are listed in
  `MaterialParams.defaulted`, and models that need them refuse to run on that
  material.
- **Process variants.** `load_material(symbol, process="x")` raises
  `FileNotFoundError` when `x/<symbol>.yaml` doesn't exist. Before, it fell back
  silently to the base file.
- **MeshField files.** `save` writes every contact field (`flat_band_shift_V`
  used to be dropped) and a `meshfield_format` version. Older files still load.
- **Implants** are checked when the step is created: an unknown species or an
  energy outside its table is an error immediately.
- **Chained analyses.** Each analysis on a solver starts from zero bias, so a
  second sweep on the same solver converges and gives the same answer as the
  first.

### Added

- **Simulation files and CLI.** YAML/JSON simulation files, checked before they
  run (`opentcad check | run`). Parameter sweeps with extracted metrics
  (`opentcad sweep`).
- **Plugins.** Registries for process steps, analyses, physics models, metrics
  and data folders, with entry-point discovery (`opentcad.plugins`).
- **Field snapshots.** The potential and carrier densities at any bias, as a
  MeshField (`DeviceSolver.snapshot`, the `fields` analysis).
- **Extraction.** Threshold-voltage extraction (`opentcad.device.extract`).
- **SKY130 check.** The Phase 2 threshold check against SKY130 `nfet_01v8`
  (`validation/sky130/`).
- **Figures and GUI.**
  - Figures computed exactly on the mesh (`opentcad.viz`).
  - Interactive Plotly figures.
  - A GUI assistant page that drafts simulation files with a local open-weights
    model and flags every value you didn't state.
- **Process catalog.** A private process catalog: records, import, checks,
  pinned exports, runsheets.
- **Packaging.** The wheel and sdist build and install cleanly without optional
  extras.
- **Documentation.** Rewritten as a GitBook manual: installation, quickstart,
  five tutorials, user guide, an API reference generated from the docstrings
  (`tools/gen_api_docs.py`), and contributor docs. `tests/docs` checks:
  - links and anchors;
  - that every page is in the sidebar;
  - that the tutorial code runs;
  - that the API pages match the code.

### Numerical behavior change: electron/hole continuity

The device solver now uses opposite electron and hole recombination/generation
source signs and a positive hole time-charge sign. The earlier shared source
sign could violate terminal-current conservation when recombination was active.
This correction can change previously generated dark as well as illuminated
results. Re-run affected drift-diffusion studies; do not combine old and new
results as if they used the same equations. Optical charge-conservation and
analytical regressions cover the corrected convention. Historical results have
not all been recalculated or retrospectively validated.

### Photovoltaic and microrobot experiments

Add prescribed Beer-Lambert generation, explicit 2D current conversion and a
reusable ideal-diode terminal model/fit/SPICE exporter. A separate microrobot
application demonstrates conceptual device physics, paper-derived terminal
fitting, circuit blocks and physical verification of a bias macro. The TCAD
structure is uncalibrated; the complete autonomous controller remains unfinished.
