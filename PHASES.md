# OpenTCAD Phases

## Cross-cutting application milestone — microrobot/PV foundation

The current implementation adds prescribed Beer-Lambert generation to the
MeshField → DEVSIM path, explicit A/cm-to-A conversion, and charge-conservation
regressions. A reusable ideal-diode terminal fit, maximum-power calculation and
SPICE export are documented in `docs/photovoltaic_compact.md`. The application
has digitized published PV curves, a PV-powered SKY130 clock with a real
divider-cell load, verified two-phase RTL and independently checked transistor
drivers. The bias macro has native/GDS DRC/LVS and RC post-layout comparisons;
storage/extraction sensitivity exposed divider-edge failures at loose numerical
settings; tighter tolerance qualifies the nominal 2 pF receiver at two timesteps.
Complete reset, integration and the remaining controller layout are pending. See `docs/optical_generation.md` and `examples/microrobot/README.md`
for executed experiments, assumptions and stages through analog layout.
The core remains independent of the application. Surface recombination and
TCAD measurement calibration remain future work. Foundry circuit/layout verification
is separate from conceptual TCAD device physics.

The Phase 2 list below is a roadmap, not an exhaustive capability inventory.
Pearson implant profiles, per-species tracking, and intrinsic and Fair
anneal exist and have tests, and the SKY130 Vth exit check passes. Calibration
is open. TED, OED and segregation are deferred beyond Phase 2.

## Phase 0 — Skeleton and Device Simulation — COMPLETE
Goal: p-n junction and MOSFET IV curves with hand-specified doping. No process sim.

Milestone 0.1 — Shared data format (MeshField, Material enum, ContactTag)  ✓
Milestone 0.2 — Geometry DSL (Structure class, Gmsh wrapper, adaptive mesh)  ✓
Milestone 0.3 — Analytic doping (uniform, Gaussian profile specification)  ✓
Milestone 0.4 — DEVSIM bridge (MeshField → DEVSIM mesh, doping, contacts, materials)  ✓
Milestone 0.5 — Physics model library (constant mobility, SRH, ohmic contacts)  ✓

Exit: ✓ 1D p-n junction IV within 5% of Shockley; ✓ 2D MOSFET threshold
      behavior correct (NMOS Id-Vgs, on/off > 1e10 at Vds = 50 mV);
      ✓ MOS-cap LF CV.

## Phase 1 — Process Topography — COMPLETE
Goal: level-set etch/deposition/oxidation producing geometry for device sim.

Milestone 1.1 — ViennaLS wrapper (TopographySimulator class, Recipe DSL)  ✓
Milestone 1.2 — Etch models (isotropic wet, anisotropic RIE, masked, multi-material)  ✓
Milestone 1.3 — Deposition models (conformal Minkowski dilation)  ✓
Milestone 1.4 — Oxidation (Deal-Grove closed-form + per-column moving boundary)  ✓

Exit: ✓ LOCOS isolation structure simulated (examples/05_locos.py);
      ✓ oxide thickness within 5% of analytic Deal-Grove across dry+wet
        ambients at 1000-1100°C (tests/process/test_oxidation.py).

Backend note: shipping on ViennaLS directly instead of ViennaPS.
On macOS, `import viennaps` loads ViennaLS itself, both wheels bundle
their own VTK and OpenMP, and the duplicates segfault on the first real
operation (re-tested 2026-11-06 with ViennaPS 4.6.1 and 4.7.0).
TODO: ViennaPS as an optional topography backend (plasma etch, ion-beam
etch, flux-based deposition). Routes: test the Linux wheels, build both
from source on macOS against one shared VTK/OpenMP, report upstream.
The Recipe / mesh-bridge boundaries won't move.

Deferred to Phase 3+: angled directional etch, polygon walker for
re-entrant profiles, proper 2D coupled O2 diffusion under the mask
(current bird's-beak is a heuristic exponential feathering).

## Phase 2 — Doping Simulation — COMPLETE
Goal: Realistic implant+anneal profiles feeding device simulation.

Milestone 2.1 — Implant parameter database (Pearson IV tables B/P/As/BF2 in Si)  ✓
      B, P, As tables (Rp, ΔRp, γ, β) over 10-200 keV, log-interpolated in
      energy, no extrapolation. BF2 maps to B at E·11/49 (mass share), so
      it needs no separate table. Co-implanted F is not modelled.
Milestone 2.2 — Implant simulation (Pearson IV + 2D lateral straggle + screening)  ◐
      The depth profile is the Pearson curve matched to all four moments,
      from the Pearson ODE. It covers types I/IV/VI, since several table
      rows are not type IV. Gaussian lateral straggle (σ_lat ≈ 0.7·ΔRp)
      with the concentration integrated over the beam geometry: mask-edge
      blur, tilt |θ| < 89°, dose per wafer area conserved. Depth comes
      from a per-column top-surface lookup (trenches, LOCOS). Implants
      write C_<species> plus the Nd/Na totals. Open: screen oxides with
      SiO₂ range data (today oxide is crossed with Si stopping); no
      channeling.
Milestone 2.3 — Diffusion solver (FiPy + Fair model + OED)  ◐
      Per-species anneal, each species with its own coefficients, chosen
      by Recipe.anneal(model=...):
        * intrinsic — analytic Gaussian convolution.
        * fair — explicit Euler on a Cartesian grid with harmonic-mean
          face D, a no-flux wall on the boundary samples (exact dose
          conservation), and sub-steps within the 2D stability limit
          (factor ≤ 0.25). Species share n / p = total donors / acceptors.
      Not FiPy-based. OED, TED and segregation are deferred beyond
      Phase 2 (agreed 2026-11-05).
Milestone 2.4 — Process→device mesh translator (THE CORE PIECE)  ✓
      run_recipe(structure, recipe) runs topography → mesh → doping and
      hands a MeshField straight to DeviceSolver (examples/06). Doping is
      computed on the device mesh itself. Junction depth agrees within 5%
      between 20 nm and 5 nm meshes for both anneal models
      (tests/process/test_junction_refinement.py). The RBF + nearest-
      neighbour interpolator in opentcad/bridge remains for moving doping
      between separate meshes.

Exit: ✓ Full NMOS process flow simulated (examples/06_nmos_implanted.py);
      ✓ Vth within 20% of SKY130 (validation/sky130/). At L = 1 µm the
        max-gm Vth is 0.697 V against 0.592 V from SkyWater's nfet_01v8 tt
        model card (+17.7 %); at 100 nA·W/L it is 0.599 V against 0.547 V
        (+9.6 %). (0.679 V and 0.588 V before anneals stopped carrying
        boron into the gate oxide.) Oxide, p-well and junction depth are SkyWater's published
        values. The threshold implant is a stand-in, sized once by a 1-D
        design formula and then simulated untuned. Between 10 nm and 7 nm
        meshes Vth changes by 10 mV (max-gm) and 2 mV (constant current).

## Phase 2a — Device physics paydown — COMPLETE
Goal: close the device-side known issues that blocked process-coupled
breakdown, heavy-doping, surface-mobility, fixed-charge and dynamic analyses.

Milestone 2a.1 — Avalanche impact ionization (van Overstraeten-de Man)  ✓
      Nodal |E| via vector_gradient; v_sat·n current proxy, so Vbd is
      ~2-3x high for Si at 1e17 (qualitative knee, not calibrated).
Milestone 2a.2 — Joyce-Dixon Fermi-Dirac inverse past the Blakemore ceiling  ✓
      Replaces the ohmic-contact potential offsets; bulk densities stay
      Blakemore.
Milestone 2a.3 — Lombardi interface-normal E_normal (e_normal_axis)  ✓
      |∂ψ/∂y| (default), |∂ψ/∂x|, or isotropic |E|; global per region.
Milestone 2a.4 — Fair concentration-coupled anneal  ✓  (see 2.3)
Milestone 2a.5 — Physical Qf (Gaussian-smeared volumetric charge)  ✓
      interface_Qf_C_per_cm2 on DeviceSolver; sign and linearity tested.
Milestone 2a.6 — transient_sweep (BDF1/BDF2/TR)  ✓
Milestone 2a.7 — ac_sweep, small-signal Y(f) via DEVSIM circuit nodes  ✓
      Metal-on-insulator terminals only, declared via ac_terminals at
      construction. Ohmic/Schottky AC is follow-up.

Exit: ✓ each item tested (tests/device, tests/process); ✓ worked examples
      09 (Fair anneal), 10 (pn transient), 11 (MOS HF-CV: C → C_ox within
      ~2% in accumulation, C_ox/C_min ≈ 4.6 in HF inversion).

## Phase 3 — Materials and Calibration 
Goal: Quantitative agreement with real fab data.

Milestone 3.1 — Materials database (Klaassen, Lombardi, Canali, SRH, Auger)  ◐
      Models implemented with YAML parameters, Lombardi's now in the
      material file too (mobility_lombardi). The Lombardi electron
      coefficients are fitted to SKY130 (validation/sky130/calibrate.py,
      materials/sky130/Si.yaml): peak gm goes from −26 % to +4 % and the
      linear Id–Vgs rms error from 0.25 to 0.09. The values are effective,
      not physical: the phonon coefficient goes to 24× its literature value
      and a systematic residual remains (−15 % to +12 % across overdrive).
      Next: a surface Coulomb term screened by the inversion layer.
Milestone 3.2 — Advanced DEVSIM physics (surface mobility, interface traps, BGN)  ◐
      Lombardi surface mobility and Slotboom BGN done; interface traps only
      as a compact mid-gap Dit term in flat_band_shift_V (no dynamic traps).
      Canali velocity saturation is driven by the quasi-Fermi-potential
      gradient by default (driving_force="quasi_fermi"). With the electric
      field along each mesh edge, oblique channel edges picked up the gate
      field and Ion was 38 % low; now it is 3.6 % low and follows the
      mobility fit (validation/sky130/README.md).
Milestone 3.3 — Calibration infrastructure (scipy optimizer, SKY130 target metrics)  ✓
      opentcad.calibrate: bounded least squares with parallel device
      simulations, calibrated material files. SKY130 targets: thresholds,
      a body-effect table and Id–Vgs curves from the tt model card. The
      stand-in channel implant is fitted to SkyWater's body effect (rms over
      five biases 248 → 19 mV) before mobility is fitted.

Status against the exit, at L = 1 µm: Vth −0.1 % (max-gm) and −8.8 %
(100 nA·W/L), SS −4.5 %, Ion −3.6 %. All three are within 10 %. Not yet
met: "all parameters cited". Citations are now machine-read
(opentcad.provenance) and every run lists the values it used without one:
12 in Si.yaml, 1 in SiO2.yaml, and four constants in the code
(docs/provenance.md; tests/provenance keeps the list from growing). The
citations carried over from the files' comments still need checking against
the papers. The fitted Lombardi coefficients are effective
values (a systematic residual remains), and the reference is a compact model
at one gate length and 300 K, not measured silicon.

Exit: NMOS Vth/Ion/SS within 10% of SKY130. All parameters cited.

## Phase 4 — Community (Ongoing)
Documentation and tutorials, NEGF extension (NanoTCAD ViDES), GDS import.
GDS import, documentation, a plugin system, a CLI and packaging were brought
forward as a tooling track right after Phase 2.
Tooling progress: plugin system ✓ (opentcad.plugins, docs/plugins.md);
ViennaLS made an optional extra, so doping and device work without it;
simulation files + `opentcad check | run` CLI ✓ (opentcad.io.deck,
docs/simulation_files.md); parameter sweeps with metrics ✓
(`opentcad sweep`, opentcad.io.sweep); promptable GUI page with a local
open-weights model (opentcad.assist, gui/pages/assistant.py,
docs/assistant.md) and Plotly figures (opentcad.viz) ✓. Documentation ✓
(a GitBook manual in docs/: tutorials, user guide, contributor guide and an
API reference generated from the docstrings by tools/gen_api_docs.py; checked
by tests/docs). Next: GDS import, the first PyPI upload. Packaging ready ✓ (clean
wheel install passes its tests; docs/releasing.md). Solution-field maps ✓
(DeviceSolver.snapshot, `fields` analysis). Device design from
specifications, first slice ✓ (opentcad.design, `opentcad design check | run |
draft`, docs/design.md): adaptive coordinate search over existing numeric
geometry, doping and recipe fields of one file, with its physics, mesh and
analyses fixed and every candidate kept as evidence. A local model can draft
the plan; drafting never runs it, and the model's open questions block a run
until they are resolved. Not in this slice:
changing topology, new process models. Open: a global or gradient-based
search, candidates in parallel.
