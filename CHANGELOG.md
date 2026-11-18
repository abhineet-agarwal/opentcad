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
- **Anneals keep dopant in the silicon.** Both anneal models used to diffuse
  over the mesh's whole bounding box, so dopant crossed into the gate oxide
  (with silicon's diffusivity) and into empty space such as an etched
  trench, and that dose was lost from the silicon. Now silicon is the only
  material dopants move in, and every other material is a no-flux wall. On
  meshes that aren't all silicon, the anneal runs on the silicon triangles
  with linear finite elements, so the wall sits exactly on the interface and
  the dose is conserved to rounding. Results change for every annealed
  structure that isn't all silicon. In the SKY130 NMOS the boron at the Si
  surface goes from 3.5×10¹⁷ to 4.8×10¹⁷ cm⁻³ (the 1-D design value is
  5.0×10¹⁷), and the threshold from 0.679 to 0.697 V (max-gm) and from
  0.588 to 0.599 V (constant current). All-silicon meshes are unchanged.
- **Lombardi coefficients** are read from the material file's
  `mobility_lombardi` block instead of being built into the model. Si.yaml
  carries the same values, so silicon results don't change; a material file
  without the block is refused by `Lombardi`.
- **Canali velocity saturation** is driven by the gradient of the carrier's
  quasi-Fermi potential by default (`driving_force="quasi_fermi"`), instead
  of the electric field along each mesh edge (`driving_force="efield"`, still
  available). On meshes whose edges aren't aligned with the current, oblique
  edges in a MOSFET channel picked up the vertical gate field. In the SKY130
  NMOS, Ion goes from 86.7 to 134.5 µA/µm (SkyWater: 139.6). Where carrier
  densities are far below `density_ref_cm3` (default 10¹⁵ cm⁻³) the force
  tends to the field, so minority diffusion at ohmic contacts isn't
  throttled. Results change for every simulation that uses Canali. Uniform
  regions (a resistor) are unchanged. Convergence is slower (about 3× on the
  example NMOS) because the force's density dependence is left out of the
  Jacobian.
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
- **Calibration.** `opentcad.calibrate`: bounded least-squares fits of model
  parameters with parallel device simulations, and calibrated material files
  (process variants with a `calibration` block). The first use is the SKY130
  calibration (`validation/sky130/calibrate.py`): the stand-in channel implant
  from SkyWater's body effect, then the Lombardi surface mobility. Vth, SS
  and Ion end within 10 % of SkyWater's model card (Ion −3.6 % with Canali's
  quasi-Fermi driving force). The fitted
  mobility values are effective, not physical. The SKY130 reference now also
  has Id–Vgs curves and a body-effect table.
- **Device design.** `opentcad design check | run | draft` (`opentcad.design`):
  a plan names existing numeric geometry, doping or recipe fields of one
  simulation file, with bounds, and targets on its IV/CV analyses.
  `run` is a bounded adaptive coordinate search with real simulations; the
  file's physics, mesh and analyses stay fixed. Every candidate, failed ones
  included, is kept as evidence. `draft` asks a configured model for a plan
  in a schema narrowed to the file. The plan is checked but never run, and the
  model's questions block a run until resolved. Example:
  `examples/design/pn_current.yaml`; guide: docs/design.md.
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
