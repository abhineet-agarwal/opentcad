# OpenTCAD

**Open-source TCAD framework for semiconductor process and device simulation.**

OpenTCAD is a modular Python framework that connects process simulation
(topography, implant, diffusion) to device simulation (drift-diffusion,
Poisson) in a single, reproducible pipeline. It is built on a stack of
mature open libraries:

| Layer               | Backend                                |
| ------------------- | -------------------------------------- |
| Meshing             | [Gmsh](https://gmsh.info)              |
| Topography          | [ViennaLS](https://viennatools.github.io/) (level sets) |
| Implant / diffusion | NumPy / SciPy kernels ([FiPy](https://www.ctcms.nist.gov/fipy/) planned) |
| Device solver       | [DEVSIM](https://devsim.org)           |
| Visualization       | [PyVista](https://pyvista.org)         |

The goal is to provide an end-to-end Python API where a single script can
define a structure, simulate fabrication, extract a device mesh, and
produce IV / CV / Vth characteristics.

---

## Status

The [executed microrobot notebook](submission.ipynb) embeds the complete mixed-abstraction demonstration, plots and numerical evidence. Its [scope and limitations](examples/microrobot/SUBMISSION_STATUS.md) identify the unresolved transistor-coupled startup and assumed physics.

**Microrobot/PV development:** prescribed monochromatic optical generation,
explicit 2D current scaling, ideal-diode terminal fitting/SPICE export and a
paper-inspired application are documented in
[`docs/optical_generation.md`](docs/optical_generation.md) and
[`docs/photovoltaic_compact.md`](docs/photovoltaic_compact.md), with results in
[`examples/microrobot/README.md`](examples/microrobot/README.md). This work also
corrects the hole recombination-source sign to enforce terminal-current
conservation. The application reports its executed checks and keeps conceptual
PV/actuator models distinct from foundry-model circuit and layout verification.
The first bias macro now has DRC/LVS, GDS round-trip and extracted electrical
checks; [scope and remaining work](examples/microrobot/PHYSICAL_VALIDATION.md)
include the rejected brownout candidate and unfinished controller assembly.
A [standalone notebook export](examples/microrobot/SETUP.md) includes the required
project source and separates new run outputs from archived evidence; Python 3.12
portability checks and optional-tool skips are recorded explicitly.

Phases 0, 1, 2 and 2a are complete. Process topography (deposit, etch,
oxidation), doping (Pearson implants with tilt and BF₂, per-species
tracking, intrinsic or Fair anneal) and device simulation work
end-to-end, joined by a single `MeshField` data contract. The Phase 2
exit check passes: a 1 µm NMOS built from a recipe lands within 15 % of
the Vth from SkyWater's SKY130 `nfet_01v8` model card
([`validation/sky130/`](validation/sky130/README.md)). OED/TED are
deferred beyond Phase 2. The current release is suitable for research,
teaching, and prototyping. See [PHASES.md](PHASES.md) for the full
roadmap.

| Phase | Scope                                        | Status         |
| ----- | -------------------------------------------- | -------------- |
| 0     | Geometry DSL + DEVSIM device simulation      | **Complete**   |
| 1     | Topography (ViennaLS): deposit + etch + Deal-Grove oxidation | **Complete** |
| 2     | Pearson implant (tilt, BF₂) + per-species intrinsic / Fair anneal + `run_recipe`; SKY130 Vth check | **Complete** |
| 2a    | Transient DC + small-signal AC, Avalanche, Joyce-Dixon, Lombardi E-normal, Fair anneal, physical Qf | **Complete** |
| 3     | Materials calibration vs. SKY130 / IHP       | Planned (SKY130 targets extracted) |

**Executed test count (2026-11-06)**: 420 passing (process 148,
integration 133, device 92, plugins 14, validation 7, geometry 15,
materials 6, bridge 5). The Phase 2a additions —
transient DC sweeps, small-signal AC (`ac_sweep` via DEVSIM circuit
nodes, gated MOS HF-CV path), Avalanche impact ionization, Joyce-Dixon
statistics past the Blakemore ceiling, Lombardi with vector-gradient
E-normal, concentration-coupled Fair anneal, and Qf as a physical
interface surface charge (Gaussian-smeared volumetric) — are all
tested alongside the original optical, charge-conservation,
compact-PV/SPICE and microrobot/RTL regressions. Full execution used ViennaLS 5.9.0; the
environment and remaining limitations are recorded in
[`examples/microrobot/README.md`](examples/microrobot/README.md).

### Device simulation (Phase 0)

- 2-D `Structure` DSL → adaptive Gmsh triangular mesh with
  per-material and per-region overrides (e.g. Si/SiO₂ stacks, n+ S/D
  wells in a p-body).
- Poisson + drift–diffusion via DEVSIM with Scharfetter–Gummel flux,
  automatic Jacobians, and continuous Si/SiO₂ interface conditions.
- Ohmic, Schottky, and metal-on-insulator contacts. `flat_band_shift_V`
  packs Q_f, mid-gap D_it, and φ_MS into one compact-model number.
- Full CMOS mobility stack composable in one expression —
  `Lombardi(base=Canali(base=Klaassen()))` — plus recombination
  (SRH + Auger + Radiative), bandgap narrowing (Slotboom), and
  Fermi–Dirac statistics (Blakemore).
- Analysis: `iv_sweep`, `cv_sweep` (quasi-static / low-frequency),
  MOS-cap regime probes, NMOS Id–Vgs. (`transient_sweep` and
  `ac_sweep` arrived in Phase 2a — see below.)
- YAML-based material parameter database with `pydantic` validation.

Phase 0 exit criteria (all met):

- ✓ 1-D p-n junction IV within 5 % of Shockley
- ✓ 2-D MOS capacitor — three regimes, φ_s ≈ 2·φ_F at strong inversion
- ✓ 2-D NMOS Id–Vgs — clean turn-on, on/off > 10¹⁰ at V_ds = 50 mV
- ✓ MOS-cap LF CV — accumulation → C_ox, depletion minimum, LF
  inversion recovery to C_ox

### Topography simulation (Phase 1)

- Chainable `Recipe` DSL:
  `Recipe().deposit(material, thickness).etch(depth, ...).oxidize(...)`.
- Deposit models: conformal (Minkowski dilation via ViennaLS
  `GeometricAdvect` + `SphereDistribution`).
- Etch models:
  - unmasked isotropic — closed-form Minkowski erosion
  - **masked isotropic** — Lax–Friedrichs advection, textbook
    quarter-circle undercut under the mask edges
  - **masked directional (RIE)** — configurable ion-beam `direction`
    and `sidewall_ratio`; near-vertical trench walls at
    `sidewall_ratio=0`, intermediate profiles for chemical–physical
    mixes.
- Multi-material stacks: a deep masked etch punches through a top
  layer and continues into the material beneath it, via ViennaLS
  multi-level-set advection. Enables hardmask patterning flows.
- Per-material etch selectivity: `etch(..., rates={Material.SI3N4: 1.0,
  Material.SIO2: 0.02})` etches each exposed material at its own
  relative rate, e.g. a nitride etch that stops on oxide
  (`tests/process/test_selectivity.py`).
- **Deal–Grove thermal oxidation**: closed-form linear-parabolic law
  with Arrhenius fits for dry O₂ and wet H₂O on ⟨100⟩ Si. Per-column
  moving boundary — Si consumed downward by 0.44 · Δx, SiO₂ top up
  by 0.56 · Δx. Optional mask window with an exponential bird's-beak
  feathering length, enough for a qualitative LOCOS profile.
- **Zero-glue device coupling**: `topography_to_meshfield` produces a
  standard `MeshField` that `DeviceSolver` consumes unchanged — no
  process-side re-meshing, no manual doping insertion.

Phase 1 exit criteria (all met):

- ✓ LOCOS isolation profile — pad oxide, masked field oxide, bird's
  beak visible in the meshed structure
  ([`examples/05_locos.py`](examples/05_locos.py))
- ✓ Gate-oxide thickness within 5 % of Deal–Grove across dry+wet
  ambients at 1000–1100 °C (verified in `test_oxidation.py`)

See [`examples/04_topography_hello.py`](examples/04_topography_hello.py)
for a side-by-side isotropic-vs-directional trench comparison plus a
two-material through-etch demo, and
[`examples/05_locos.py`](examples/05_locos.py) for the LOCOS flow.

**Backend note (macOS)**: OpenTCAD talks to ViennaLS directly rather
than through ViennaPS, because the ViennaPS macOS wheels crash.
`import viennaps` loads ViennaLS itself, both packages bundle their own
VTK and OpenMP, and the duplicates segfault on the first real operation
(re-tested 2026-11-06 with ViennaPS 4.6.1 and 4.7.0). ViennaPS's
process models (plasma etch, ion-beam etch, flux-based deposition) are
on the backlog as an optional topography backend; the Recipe and
mesh-bridge boundaries won't move.

### Doping — implant and anneal (Phase 2)

- **Implant:** `Recipe.implant(species, energy_keV, dose_cm2,
  window_x_um=…, tilt_deg=…, profile="pearson")`.
  - *Depth profile:* the Pearson curve matched to all four tabulated
    moments (R_p, ΔR_p, γ, β), log-interpolated from per-species YAML
    tables for B, P and As in Si over 10–200 keV. It solves the Pearson
    equation directly, so every valid (γ, β) works. Several tabulated
    rows are type I or VI rather than IV; boron above ~30 keV, for
    example, is type I. `profile="gaussian"` keeps only R_p and ΔR_p.
  - *Lateral straggle and mask edges:* Gaussian lateral straggle with
    σ_lat = 0.7·ΔR_p. The concentration at each node is integrated over
    the beam geometry, so mask windows get the erf edge blur and dose
    per unit wafer area is conserved at any tilt.
  - *Tilt:* |tilt| < 89° in the cross-section plane. Channeling is not
    modelled, so tilt changes only the geometry.
  - *Surface:* depth is measured from the local top of the meshed
    stack, found column by column, so implants into trenches or LOCOS
    land where they should.
  - *BF₂:* treated as boron at the mass-scaled energy, E·11/49.
  - *Screen oxide:* material above the Si is crossed with the Si range
    tables, because no SiO₂ stopping data is shipped.
- **Per-species tracking:** each implant writes a `C_<species>` field
  on the `MeshField` (`C_boron`, `C_phosphorus`, `C_arsenic`). `Nd` and
  `Na` stay the totals the device solver reads. Doping painted by the
  `Structure` DSL is "untracked" and keeps the old single-species
  behaviour (`species_Nd`/`species_Na`).
- **Anneal:** `Recipe.anneal(temperature_C, time_s, model=…)`. Every
  tracked species diffuses with its own coefficients, so P and As in
  the same n+ region spread at their own rates.
  - `model="intrinsic"` (default): an analytic Gaussian spread with the
    Arrhenius D_i(T). It is exact while the profile stays below n_i(T).
  - `model="fair"`: Fair concentration-coupled diffusion. It uses
    D_eff = D_i + D⁻·(n/n_i) + D⁻⁻·(n/n_i)² for donors (D⁺, D⁺⁺ with
    p/n_i for acceptors), where n and p are the total donor and
    acceptor concentrations shared by all species. It steps explicitly
    on a Cartesian grid, with harmonic-mean face diffusivities, a
    no-flux wall on the boundary samples, and sub-steps held under the
    2-D stability limit (factor ≤ 0.25). It also runs standalone as
    `apply_anneal_fair`. At S/D-level doping it produces the
    concentration-enhanced spreading that the intrinsic model misses.
  - Both kernels conserve each species' dose.
  - Not modelled: OED, TED and segregation (deferred beyond Phase 2).
- **`run_recipe(structure, recipe)`:** plays topography steps through
  ViennaLS, meshes the result, and then applies the implant/anneal
  steps directly onto the device `MeshField`. A test checks that the
  resulting junction depth agrees between 20 nm and 5 nm device meshes
  to within 5 % (1.4 % intrinsic, 0.3 % Fair in practice). The
  `opentcad.bridge` RBF + nearest-neighbour interpolator remains
  available for moving doping between separate meshes.

See [`examples/06_nmos_implanted.py`](examples/06_nmos_implanted.py)
for a recipe-to-Id–Vgs NMOS flow (As implants plus anneal, with no
hand-painted doping), and
[`examples/09_fair_anneal_profile.py`](examples/09_fair_anneal_profile.py)
for the Fair vs intrinsic comparison.

Phase 2 exit criterion (met):

- ✓ NMOS Vth within 20 % of SKY130. A 1 µm `nfet_01v8`-like device is
  built from a recipe: SkyWater's published oxide, p-well and junction
  depth, plus a stand-in boron threshold implant sized once by a 1-D
  design formula. Its simulated Vth is 0.679 V by max-gm against 0.592 V
  from the SKY130 tt model card (+14.8 %), and 0.588 V against 0.547 V
  at 100 nA·W/L (+7.5 %). Both curves go through the same extraction
  (`opentcad.device.extract`). Inputs, stand-ins, mesh refinement and
  caveats are in [`validation/sky130/`](validation/sky130/README.md).

### Phase 2a: device physics upgrades (complete)

Each item has dedicated tests under `tests/device/` or
`tests/process/`. The approximations listed are deliberate and are
documented in the source.

- **Avalanche impact ionization** (`Avalanche`): van Overstraeten–de
  Man (Chynoweth-form) α_n, α_p(|E|), with nodal |E| from
  `vector_gradient`. The carrier current uses a saturation-velocity
  proxy |J| ≈ q·v_sat·n rather than the drift-diffusion |J_n|/|J_p|.
  Sweeps do show a breakdown knee, but Vbd comes out roughly 2–3×
  too high for Si at N = 1e17. That is fine for qualitative breakdown
  but not for calibrated Vbd.
- **Joyce–Dixon statistics** (`JoyceDixon`): an explicit series for
  the inverse Fermi–Dirac integral that replaces the Blakemore form in
  the ohmic-contact potential offsets, which fail above ~3.7·N_c. It
  is accurate to better than 1 % for n ≤ ~3e20 cm⁻³ in Si. Bulk
  carrier densities still use the Blakemore forward expression.
- **Lombardi interface-normal field**: `Lombardi(e_normal_axis="y")`
  (the default) takes |∂ψ/∂y| from `vector_gradient` as E_⊥ for planar
  Si/SiO₂ interfaces. `"x"` suits vertical sidewalls, and
  `"magnitude"` keeps the old isotropic |E|. The axis is set per
  region. Curved interfaces would need a per-element projection, which
  is not done yet.
- **Fair concentration-coupled anneal** (`apply_anneal_fair`): see
  the Phase 2 list above.
- **Physical Q_f**: `DeviceSolver(..., interface_Qf_C_per_cm2={"SI":
  (Qf, y_interface_um)})` places a fixed sheet charge as a
  Gaussian-smeared volumetric charge inside the semiconductor, with
  σ set by `interface_Qf_width_um` (default 5 nm). It complements the
  compact gate `flat_band_shift_V`. Tests check that the induced
  surface-potential shift has the right sign and is linear in Q_f.
- **`transient_sweep`**: BDF1/BDF2/TR time stepping with a
  `transient_dc` initialisation, plus `charge_error` exposed as a
  convergence knob. Carrier-storage charge is included; external
  circuit parasitics are not.
- **`ac_sweep`**: small-signal admittance Y(f) = G + jωC on a
  metal-on-insulator gate, via a DEVSIM circuit voltage source. It
  gives HF CV, which the quasi-static `cv_sweep` cannot. Terminals
  must be declared at construction with `ac_terminals=[...]`, because
  DEVSIM forbids new circuit nodes after the first solve. AC on
  ohmic/Schottky terminals raises `NotImplementedError`.

Worked examples are in the Phase 2a demos section below.

---

## Architecture

Every layer communicates through a single data object — the **`MeshField`**
— a thin wrapper around a `pyvista.UnstructuredGrid` carrying:

- per-cell `material_id` (from the `Material` enum)
- per-point doping (`Nd`, `Na` in cm⁻³)
- a list of named electrical contacts (`ContactTag`)
- a `ProcessStep` history for provenance

```
   ┌──────────────────────────────────────────────┐    ┌──────────────────────────────┐
   │   opentcad.geometry.Structure (DSL)          │    │   opentcad.process.Recipe    │
   │  add_substrate / add_layer / add_region /    │    │  .deposit(material, t)       │
   │  add_contact                                 │    │  .etch(depth, model=...,     │
   │                                              │    │        window_x_um=...)      │
   │                                              │    │  .oxidize(T, t, ambient)     │
   │                                              │    │  .implant(...) .anneal(...)  │
   └────────────────────┬─────────────────────────┘    └────────────┬─────────────────┘
                        │ .to_meshfield()                           │ run_recipe(struct, recipe)
                        │                                           ▼
                        │                             ┌───────────────────────────────┐
                        │                             │  ViennaLS multi-LS advection  │
                        │                             │  (per-layer level-sets)       │
                        │                             └────────────┬──────────────────┘
                        │                                          │ topography_to_meshfield
                        ▼                                          ▼
   ┌──────────────────────────────────────────────────────────────────────────────────┐
   │  MeshField  ─  pyvista UnstructuredGrid                                          │
   │   cells:  material_id                                                            │
   │   nodes:  Nd, Na   ← run_recipe applies implant + anneal steps here              │
   │   tags :  ContactTag, ProcessStep                                                │
   └────────────────────────────────────────────┬─────────────────────────────────────┘
                                                │
                                                ▼
                              ┌────────────────────────────────────────┐
                              │  opentcad.device.DeviceSolver          │
                              │  DEVSIM · Poisson + DD                 │
                              │  Klaassen · Canali · Lombardi · SRH …  │
                              │  iv · cv · transient · ac sweeps       │
                              └────────────────────┬───────────────────┘
                                                   │
                                                   ▼
                                            VTK / matplotlib
```

**Units are enforced everywhere**: spatial in micrometers (µm),
concentration in cm⁻³, temperature in Kelvin, energy in eV.
The DEVSIM bridge converts µm → cm internally; you never see that.

---

## Installation

OpenTCAD requires Python ≥ 3.10. The device solver depends on DEVSIM,
which ships as a binary wheel for Linux and macOS.

```bash
git clone https://github.com/abhineet-agarwal/opentcad.git
cd opentcad
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pip install -e ".[topography]"   # ViennaLS, for deposit / etch / oxidize steps
```

ViennaLS is optional. Without it, structures, doping-only recipes,
implants, anneals and the device solver all work, and only topography
steps raise an error asking for it. Its current wheels ship a GPL v3
license, which is why it isn't a required dependency.

Verify the installation:

```bash
pytest tests/geometry -v          # no DEVSIM required
pytest tests/ -v -m "not slow"    # full test suite
```

### Optional: Streamlit GUI

An interactive browser UI walks through the whole pipeline
(Structure → Recipe → MeshField → IV/CV) with per-section live previews:

```bash
pip install -e ".[gui]"
streamlit run opentcad/gui/app.py
```

Opens `http://localhost:8501`. Session state carries the built objects
between sections; a sidebar "Reset entire pipeline" button clears
everything.

---

## Tutorial 1 — A silicon p-n junction in 25 lines

Build a 1 µm × 1 µm symmetric p-n diode (Nₐ = N_d = 10¹⁷ cm⁻³),
mesh it, and sweep the forward bias from 0 V to 0.7 V:

```python
from opentcad.device.solver import DeviceSolver
from opentcad.geometry.formats import Material
from opentcad.geometry.structure import Structure
from opentcad.materials.database import load_material

structure = (Structure(width_um=1.0, name="pn_diode")
    .add_substrate("p", 0.5, Material.SI, doping_Na=1e17)
    .add_layer    ("n", 0.5, Material.SI, doping_Nd=1e17)
    .add_contact  ("anode",   0.0, 1.0, "p", surface="bottom")
    .add_contact  ("cathode", 0.0, 1.0, "n", surface="top"))

mesh = structure.to_meshfield(mesh_size_um=0.05)

solver = DeviceSolver(mesh, {"Silicon": load_material("Si")})
V, I   = solver.iv_sweep("anode", "cathode",
                         v_start=0.0, v_end=0.7, v_step=0.05)
```

The full version (with matplotlib plotting and an ideality-factor check
against the Shockley equation) lives at
[`examples/01_pn_junction.py`](examples/01_pn_junction.py):

```bash
python examples/01_pn_junction.py
```

You should see a textbook diode IV with a semilog slope of q/kT
(≈ 25.85 mV per decade at 300 K).

![p-n junction IV](examples/01_pn_junction_iv.png)

---

## Tutorial 2 — A MOS capacitor (heterogeneous regions)

Multi-region devices work the same way. Stack p-type silicon, a 5 nm
thermal oxide, and a metal gate contact; OpenTCAD automatically detects
the Si/SiO₂ interface and inserts a potential-continuity boundary
condition.

```python
from opentcad.device.solver import DeviceSolver
from opentcad.geometry.formats import Material
from opentcad.geometry.structure import Structure
from opentcad.materials.database import load_material

mos = (Structure(width_um=1.0, name="mos_cap")
    .add_substrate("body",  0.5,   Material.SI,   doping_Na=1e17)
    .add_layer    ("oxide", 0.005, Material.SIO2)              # 5 nm
    .add_contact  ("body",  0.0, 1.0, "body",  surface="bottom")
    .add_contact  ("gate",  0.0, 1.0, "oxide", surface="top"))

mf     = mos.to_meshfield(mesh_size_um=0.05)
solver = DeviceSolver(mf, {
    "Silicon": load_material("Si"),
    "SiO2"  : load_material("SiO2"),
})
solver.solve_equilibrium()
```

You can then sweep the gate bias and observe the three classical regimes
(accumulation, depletion, strong inversion). A worked test that asserts
the surface potential saturates near 2·φ_F at strong inversion is in
[`tests/device/test_mos_capacitor.py`](tests/device/test_mos_capacitor.py).

---

## Tutorial 3 — A full 2-D NMOS Id–Vgs

`add_region` overrides material (and doping) inside a rectangle, so n+
source/drain wells can be poked through the gate-oxide layer to give the
S/D contacts something ohmic to attach to. The result is a real
four-terminal MOSFET:

```python
from opentcad.device.solver import DeviceSolver
from opentcad.geometry.formats import Material
from opentcad.geometry.structure import Structure
from opentcad.materials.database import load_material

W, L, T_OX = 2.0, 1.0, 0.005
nmos = (Structure(width_um=W, name="nmos")
    .add_substrate("p_body", 0.5,   Material.SI,   doping_Na=1e17)
    .add_layer    ("oxide",  T_OX,  Material.SIO2)
    .add_region   ("source", 0.0, 0.5, 0.4, 0.5 + T_OX, Material.SI, doping_Nd=1e20)
    .add_region   ("drain",  W-0.5, W, 0.4, 0.5 + T_OX, Material.SI, doping_Nd=1e20)
    .add_contact  ("source", 0.0, 0.5,             "oxide", surface="top")
    .add_contact  ("drain",  W-0.5, W,             "oxide", surface="top")
    .add_contact  ("gate",   0.5, 0.5+L,           "oxide", surface="top")
    .add_contact  ("body",   0.0, W,               "p_body", surface="bottom"))

mf     = nmos.to_meshfield(mesh_size_um=0.03)
solver = DeviceSolver(mf, {"Silicon": load_material("Si"),
                           "SiO2"   : load_material("SiO2")})
solver.solve_equilibrium()
# Set Vds = 50 mV, then sweep Vgs — see tests/device/test_nmos_idvg.py
```

Sweeping Vgs from 0 V to 1.5 V at Vds = 50 mV gives a textbook Id–Vgs
curve with on/off ratio ≈ 10¹⁰, monotonic turn-on, and the threshold
visible as a knee in the curve near ~0.7 V (matching the MOS-cap
analytic Vth ≈ 0.85 V for Nₐ = 10¹⁷).

---

## Tutorial 4 — A curved trench from a masked etch

The topography DSL runs process steps on a ViennaLS level-set and hands
you a `MeshField` you can feed straight back into `DeviceSolver`. The
following recipe starts with a bare Si substrate, blanket-etches 30 nm,
then opens a 300 nm window in the mask and isotropically etches 150 nm.
The result is the textbook quarter-circle profile:

```python
from opentcad.geometry.formats import Material
from opentcad.geometry.structure import Structure
from opentcad.process.topography import (
    Recipe, simulate, topography_to_meshfield,
)

struct = (Structure(width_um=1.0, name="trench")
    .add_substrate("body", 0.5, Material.SI))

recipe = (Recipe("curved_trench")
    .etch(0.03)                                   # blanket 30 nm
    .etch(0.15, window_x_um=(0.35, 0.65)))        # 150 nm through mask

state = simulate(struct, recipe, grid_delta_um=0.005)
mf    = topography_to_meshfield(state, mesh_size_um=0.03)
```

Swap `.etch(depth, window_x_um=..., model="directional")` for the RIE
variant with near-vertical sidewalls, or `.etch(depth, ...,
model="directional", sidewall_ratio=0.4)` for an intermediate profile.
[`examples/04_topography_hello.py`](examples/04_topography_hello.py)
runs both models under the same window and produces:

- `examples/04_topography_recipe.png` — recipe progression per step
  for both isotropic and directional, in a 2×3 grid.
- `examples/04_topography_profile.png` — the two final profiles
  overlaid so you can read the undercut off directly.
- `examples/04_topography_mesh.png` — the final MeshField shaded by
  material, ready for the device solver.

For multi-material patterning (say, a directional etch through a
30 nm SiO₂ hardmask into the Si substrate), just start with a
stacked `Structure`:

```python
struct = (Structure(width_um=1.0, name="through_etch")
    .add_substrate("body", 0.5, Material.SI)
    .add_layer   ("oxide", 0.03, Material.SIO2))

recipe = Recipe("through").etch(
    0.15, model="directional", window_x_um=(0.35, 0.65))

state = simulate(struct, recipe, grid_delta_um=0.005)
mf    = topography_to_meshfield(state, mesh_size_um=0.02)
```

The etch consumes the oxide inside the window and continues into the Si
by the remaining depth; the mesh bridge splits each material into
whichever contiguous x-ranges still carry non-zero thickness. See
`examples/04_topography_through.png` for the result.

---

## Tutorial 5 — LOCOS field isolation (Phase 1 exit demo)

Deal–Grove oxidation on bare Si follows the linear-parabolic law
x² + A·x = B(t + τ) with Arrhenius fits for A and B; OpenTCAD advects
the Si-top and SiO₂-top level-sets by 0.44·Δx and 0.56·Δx respectively
so each column's oxide growth conserves the physical volume ratio.
A single `.oxidize(T_C, t_s, ambient)` call is the whole recipe:

```python
recipe = Recipe("locos").oxidize(
    temperature_C=1000, time_s=3600, ambient="wet",
    window_x_um=(0.7, 1.3),         # nitride-mask opening
    bird_beak_length_um=0.03,       # lateral O2 diffusion tail
)
```

Running the full flow — thin pad oxide, then a wet field oxidation
inside a photolith window — reproduces the classic LOCOS profile:
thick SiO₂ mesa in the active area, tapered "bird's beak" at each
mask edge, unetched Si below. The full script lives at
[`examples/05_locos.py`](examples/05_locos.py):

```bash
python examples/05_locos.py
```

It produces two PNGs: a step-by-step stack view
(`examples/05_locos_profile.png`) and the final triangulated
`MeshField` shaded per material (`examples/05_locos_mesh.png`, ~85 k
triangles, ready for `DeviceSolver`).

The Phase 1 exit criterion — SiO₂ thickness within 5 % of the analytic
Deal–Grove prediction — is verified in
[`tests/process/test_oxidation.py`](tests/process/test_oxidation.py)
across dry+wet ambients at 1000–1100 °C.

![LOCOS profile](examples/05_locos_profile.png)

---

## Phase 2a demos

Short, self-contained scripts that exercise the Phase 2a additions:

- [`examples/09_fair_anneal_profile.py`](examples/09_fair_anneal_profile.py)
  — Fair concentration-coupled anneal vs intrinsic Gaussian on a
  1e20 cm⁻³ Gaussian phosphorus profile, which stands in for an
  as-implanted peak. It shows the concentration-enhanced flattening
  that the intrinsic model cannot produce, plus a D_eff(n/n_i)
  reference plot.
- [`examples/10_pn_transient.py`](examples/10_pn_transient.py) — p-n
  diode anode driven 0.1 → 0.7 V over 10 ns through
  `DeviceSolver.transient_sweep` (BDF1). Records the ~10 decades of
  current rise as the junction crosses the Shockley knee.
- [`examples/11_mos_hfcv.py`](examples/11_mos_hfcv.py) — small-signal
  high-frequency CV on a p-sub MOS cap via `DeviceSolver.ac_sweep` at
  1 MHz. Reproduces the textbook three-regime shape (C_ox in
  accumulation, falling through depletion, HF floor in inversion —
  C_ox / C_min ≈ 4.6× for NA = 1e17 / t_ox = 10 nm).

![MOS HF-CV](examples/11_mos_hfcv.png)

---

## Concepts

### The `Structure` DSL

`Structure` describes a 2D cross-section as an ordered layer stack plus
optional rectangular region overrides:

| Method            | Purpose                                                 |
| ----------------- | ------------------------------------------------------- |
| `add_substrate`   | First (bottom) layer                                    |
| `add_layer`       | Stack a layer on top                                    |
| `add_region`      | Override material/doping in a rectangle (e.g. S/D wells)|
| `add_contact`     | Tag a span of nodes on the top or bottom surface        |
| `to_meshfield`    | Generate the Gmsh mesh and return a `MeshField`         |

The mesh is automatically refined at material interfaces; you can tune
the global element size via `mesh_size_um`.

### The `Recipe` DSL and topography engine

`Recipe` describes an ordered process flow — pure data, no backend
coupling. `simulate(structure, recipe)` plays it against an initial
`TopographyState` (built from the substrate + any pre-existing layers
in `Structure`) using ViennaLS level-sets:

| Method                                            | Purpose                                                             |
| ------------------------------------------------- | ------------------------------------------------------------------- |
| `deposit(material, thickness_um)`                 | Conformal Minkowski-dilation of the surface                         |
| `etch(depth_um)`                                  | Blanket isotropic erosion                                           |
| `etch(depth_um, window_x_um=(x0, x1))`            | Masked isotropic etch — quarter-circle undercut                     |
| `etch(depth_um, model="directional", ...)`        | Masked / unmasked RIE — near-vertical walls at `sidewall_ratio=0`   |
| `oxidize(T_C, t_s, ambient, window_x_um=..., bird_beak_length_um=...)` | Deal–Grove growth with per-column moving boundary + optional LOCOS-style mask |

`topography_to_meshfield(state, mesh_size_um=...)` extracts each
layer's top-surface polyline via `ToSurfaceMesh`, clamps to the
physical stack invariant, splits every layer into the x-ranges where
it still has non-zero thickness, and hands the resulting polygons to
gmsh for a triangulation tagged per material.

### The `MeshField` data contract

Every module boundary in OpenTCAD passes a `MeshField`. There is no
raw-numpy interface between layers — this guarantees that geometry,
doping, contact, and provenance information stay together.

```python
mf.material_ids        # ndarray[int], one per cell
mf.Nd, mf.Na           # ndarray[float], cm^-3, per node (totals the device solver reads)
mf.species_names()     # e.g. ["arsenic", "boron"] — implanted species tracked as C_<species>
mf.get_species("boron")  # ndarray[float], cm^-3, per node
mf.get_contact("gate") # ContactTag
mf.save("device.vtu")  # VTK + sidecar JSON metadata
MeshField.load("device.vtu")
```

### Materials

Material parameters live as YAML files in
[`opentcad/materials/params/`](opentcad/materials/params/). Each file
specifies bandgap, effective densities of states, mobility, SRH
lifetimes, and (for insulators) the `is_insulator: true` flag that puts
the region in Poisson-only mode. Add a new material by dropping in a new
YAML file.

```python
from opentcad.materials.database import load_material
si  = load_material("Si")
ox  = load_material("SiO2")
print(si.mobility_constant.electron_cm2_Vs)   # 1350.0
```

### Physics models

`DeviceSolver` takes an optional `PhysicsConfig` that bundles the
mobility, recombination, etc. models to use. Mobility is a single
model; recombination is a list of contributors (their rates are
summed).

```python
from opentcad.device.physics import PhysicsConfig
from opentcad.device.models import Klaassen, SRH, Auger, Radiative

solver = DeviceSolver(mf, mat_params,
                      physics=PhysicsConfig(
                          mobility=Klaassen(),
                          recombination=[SRH(), Auger(), Radiative()]))
```

Available today:

| Kind | Model | Notes |
|---|---|---|
| Mobility | `ConstantMobility` | default; YAML `mobility_constant` values |
| Mobility | `Klaassen` | unified low-field bulk mobility (1992) with clustering + carrier-carrier scattering |
| Mobility | `Canali` | high-field velocity saturation; wraps any base model (composes with `Klaassen`) |
| Mobility | `Lombardi` | surface mobility at Si/SiO₂ interfaces; wraps any base model; Matthiessen composition of bulk + acoustic-phonon + surface-roughness; `e_normal_axis="y"` (default) / `"x"` / `"magnitude"` selects the E_⊥ component |
| Recombination | `SRH` | default; mid-gap trap |
| Recombination | `Auger` | Dziewior-Schmid; dominates over SRH for n,p > ~10¹⁸ cm⁻³ |
| Recombination | `Radiative` | negligible in Si; central for GaAs/GaN |
| Recombination | `Avalanche` | impact-ionization *generation*, added to `recombination=[...]`; van Overstraeten–de Man α(E) with a v_sat·n current proxy, so Vbd is qualitative (~2–3× high) |
| BGN | `NoBGN` | default; disables bandgap narrowing |
| BGN | `Slotboom` | doping-dependent Eg narrowing; raises n_i_eff in n+/p+ regions |
| Contact BC | `contact_type="ohmic"` | default; charge-neutral semiconductor contact |
| Contact BC | `contact_type="schottky"` | metal-semi barrier; requires `work_function_eV`; rectifies |
| Contact BC | `flat_band_shift_V` | metal-on-insulator Vfb offset; packs Qf, midgap Dit, and phi_MS in one number |
| Statistics | `Boltzmann` | default; classical Maxwell-Boltzmann |
| Statistics | `FermiDirac` | Blakemore approximation; captures degeneracy at heavy doping (n → N_c) |
| Statistics | `JoyceDixon` | Joyce–Dixon inverse for the contact potential offsets past the Blakemore ceiling (~3.7·N_c); bulk densities stay Blakemore |
| Fixed charge | `interface_Qf_C_per_cm2` (solver kwarg) | physically-located Q_f as a Gaussian-smeared volumetric charge at a given interface y |

The full CMOS mobility stack — bulk doping-dep + high-field saturation +
surface degradation — composes in a single expression:

```python
physics = PhysicsConfig(
    mobility=Lombardi(base=Canali(base=Klaassen())),
    recombination=[SRH(), Auger()],
    bgn=Slotboom())
```

Klaassen's µ_n on uniformly-doped Si at 300 K:

| Nd (cm⁻³) | µ_n (cm²/V/s) |
|----------:|--------------:|
| 10¹⁵      | 1359          |
| 10¹⁶      | 1177          |
| 10¹⁷      | 727           |
| 10¹⁸      | 284           |
| 10¹⁹      | 108           |

Adding new physics is one new file under
[`opentcad/device/models/`](opentcad/device/models/) that subclasses
the relevant base in `opentcad/device/physics.py`.

### Extending OpenTCAD (plugins)

New process steps, device analyses, dopant tables and material files can
be added from outside the core through `opentcad.plugins`. The built-ins
are registered the same way.

```python
from opentcad.plugins import register_step, register_analysis, register_data_dir

register_step(MyStep, stage="doping", apply=my_apply)      # Recipe().add(MyStep(...))
register_analysis("my_sweep", my_sweep)                    # solver.run("my_sweep", ...)
register_data_dir("dopants", "tables/")                    # e.g. Sb_in_Si.yaml → implant("Sb", ...)
```

An installed package can declare an `opentcad.plugins` entry point, and
OpenTCAD loads it automatically. A name defined twice is an error, never
a silent override, and a plugin that fails to load produces a warning. Set
`OPENTCAD_DISABLE_PLUGINS=1` to run with the core alone. See
[`docs/plugins.md`](docs/plugins.md).

---

## Project layout

```
opentcad/
├── plugins.py     Registries for process steps, analyses and data folders; entry-point discovery
├── geometry/      Structure DSL, Gmsh meshing, MeshField data format
├── process/       run_recipe (topography + doping, end to end)
│   ├── topography/ Recipe DSL, ViennaLS simulator, level-set → mesh bridge
│   └── doping/    Pearson implant (tilt, BF₂), per-species intrinsic + Fair anneal, YAML tables
├── device/        DEVSIM wrapper, physics models, contact BCs, IV/CV/transient/AC,
│                  Vth extraction (extract.py)
├── materials/     YAML parameter database + loader
├── bridge/        RBF + nearest-neighbour doping-field interpolator (not yet used by run_recipe)
├── io/            Empty placeholder (MeshField.save writes .vtu; GDS import is planned)
├── viz/           Empty placeholder (GUI plots live in gui/plots.py)
└── gui/           Optional Streamlit front end

validation/sky130/ Phase 2 exit check against SkyWater's nfet_01v8 model card
docs/              Plugin guide, optical generation, compact PV notes
examples/          Runnable tutorial scripts (01–11) + generated PNG plots
tests/             Pytest suite — 420 tests
                   (markers: slow, requires_devsim, requires_viennaps, integration)
PHASES.md          Phased roadmap with exit criteria per phase
```

---

## Testing

```bash
pytest tests/ -v                         # full suite (420 tests, ~8 min)
pytest tests/geometry/ -v                # geometry-only (no DEVSIM/ViennaLS)
pytest tests/process/ -v                 # topography (requires viennals) + doping
pytest tests/device/ -v                  # DEVSIM device physics, transient, AC
pytest tests/validation/ -v              # SKY130 Vth check (end-to-end run ~6 min)
pytest -m "not slow" -v                  # skip slow tests
pytest -m requires_devsim -v             # only DEVSIM-backed tests
```

Test markers are declared in
[`pyproject.toml`](pyproject.toml) under `[tool.pytest.ini_options]`.

---

## Roadmap

See [PHASES.md](PHASES.md) for full milestone descriptions.

**Done**

- **Phase 0** — Geometry DSL + DEVSIM device simulation with p-n
  junction, MOS-cap, and NMOS Id–Vgs / CV as validated exit criteria.
- **Phase 1** — Topography DSL (`Recipe.deposit / etch / oxidize`)
  on ViennaLS: conformal deposit, isotropic + directional (RIE) etch,
  masked windowed etches, multi-material through-etch, Deal–Grove
  thermal oxidation with a per-column moving boundary, and a
  level-set → `MeshField` bridge that drops straight into the device
  solver. LOCOS + gate-oxide-within-5 % exit criteria met.
- **Phase 2a (device physics upgrades)**: Avalanche (van
  Overstraeten–de Man), Joyce–Dixon contact offsets past the
  Blakemore ceiling, Lombardi with an interface-normal E_⊥ via
  `vector_gradient`, physically-located Q_f (Gaussian-smeared
  volumetric), Fair concentration-coupled anneal, `transient_sweep`
  (BDF1/BDF2/TR) and `ac_sweep` (small-signal Y(f) on MOS gates). All
  are tested, with worked examples 09, 10 and 11.
- **Phase 2 (doping)** — Pearson implant profiles matched to all four
  moments for B, P and As (10–200 keV) and BF₂; tilt, beam-geometry
  mask edges and per-column surfaces; per-species `C_<species>`
  tracking; intrinsic and Fair anneal via `Recipe.anneal`; `run_recipe`
  (topography → mesh → doping → `DeviceSolver`) with a junction depth
  converged under mesh refinement; the implanted NMOS demo (example 06).
  Exit check met: Vth within 15 % of SKY130 `nfet_01v8`
  ([`validation/sky130/`](validation/sky130/README.md)). OED, TED and
  segregation are deferred beyond Phase 2.

**Next**

- **Tooling**: the plugin system is in place (`opentcad.plugins`:
  process steps, device analyses, dopant and material tables, entry-point
  discovery; [`docs/plugins.md`](docs/plugins.md)). Still to come: a file
  format for structures and recipes, a CLI with parameter sweeps, a
  promptable GUI built on that file format, GDS import, Sphinx docs and
  a PyPI release.
- **Phase 3**: quantitative calibration against the SKY130 / IHP
  SG13G2 PDKs: a scipy-driven fit of the existing physics knobs against
  target metrics (Vth, Ion, SS). The models in the Phase 3 milestone
  list (Klaassen, Canali, Lombardi, SRH, Auger, Slotboom BGN) exist, and
  SKY130 targets and Vth extraction are ready (`validation/sky130/`,
  `opentcad.device.extract`). The optimizer does not exist yet. The first
  item is surface mobility: with literature Lombardi coefficients the
  simulated gm plateaus instead of peaking.
- **Phase 4**: NEGF backend via NanoTCAD ViDES, community notebooks.

**Backlog / follow-ups noted in code**

- Angled directional etches (non-vertical ion beam direction).
- Proper polygon walker in the mesh bridge for re-entrant profiles
  (currently drops the overhang sliver at multi-valued x).
- Full 2D coupled O₂ diffusion for the LOCOS bird's-beak profile
  (currently an exponential heuristic feathering length).
- Avalanche: replace the v_sat·n current proxy with the real
  drift-diffusion |J_n|/|J_p|, which needs edge/element-aware models,
  to get calibrated Vbd.
- Lombardi: a per-element interface-normal projection for curved
  interfaces (bird's beak, angled sidewalls).
- Joyce–Dixon: a true F₁/₂ forward expression for bulk densities
  (currently Blakemore).
- Small-signal AC on ohmic/Schottky terminals. `ac_sweep` needs a
  metal-on-insulator terminal today, because ohmic/Schottky contacts
  would also need their Electron/HoleContinuity fluxes routed into
  the circuit node.
- Doping physics left out of Phase 2:
  - OED, which needs interstitial injection from the oxidation step.
  - TED, which needs an implant-damage model.
  - Dopant segregation at Si/SiO₂, which needs a cited segregation
    coefficient per species.
  - SiO₂ range tables for screen oxides (today the oxide is crossed
    with Si stopping).
  - Doping steps interleaved with later topography: implants run after
    meshing, so a well implant followed by oxidation isn't modelled.
- ViennaPS as an optional topography backend, adding physical plasma
  etch, ion-beam etch and flux-based deposition next to the geometric
  ViennaLS steps. Blocked on the macOS crash above. Routes to try:
  check whether the Linux wheels work, build ViennaLS and ViennaPS from
  source on macOS against one shared VTK and OpenMP, and report the
  crash upstream.

---

## Contributing

Contributions are welcome — particularly new material YAML files (with
citations), example notebooks, and DEVSIM physics models. Please:

1. Open an issue describing the change before large refactors.
2. Add tests covering new behavior (`pytest -v` must pass).
3. Run `ruff check .` and keep public APIs documented with docstrings.

---

## License

Apache License 2.0 — see [LICENSE](LICENSE). OpenTCAD wraps several
open-source projects, each under its own license: Gmsh GPLv2 with
linking exception, DEVSIM Apache 2.0, FiPy public domain, PyVista MIT,
and ViennaLS, whose current wheels (5.8.3, 5.9.0) ship a GPL v3 license
file. ViennaLS is not a declared dependency; only the topography
module needs it.

## Citation

If you use OpenTCAD in academic work, please cite the upstream tools
(DEVSIM, Gmsh, ViennaLS) in addition to this repository.
