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
Gaussian implant (on Pearson moments), intrinsic anneal and the Fair
concentration-coupled anneal exist and have tests. The full Pearson-IV shape,
TED/OED and calibration are incomplete.

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

Backend note: shipping on ViennaLS directly instead of ViennaPS —
the macOS ViennaPS 4.6 wheel statically links VTK and its duplicate
vtkCocoa* classes segfault when both packages load. ViennaPS process
models (SF6O2Etching, MultiParticleProcess, ...) plug in later when a
fixed wheel arrives; the Recipe / mesh-bridge boundaries won't move.

Deferred to Phase 3+: angled directional etch, polygon walker for
re-entrant profiles, proper 2D coupled O2 diffusion under the mask
(current bird's-beak is a heuristic exponential feathering).

## Phase 2 — Doping Simulation — PARTIAL
Goal: Realistic implant+anneal profiles feeding device simulation.

Milestone 2.1 — Implant parameter database (Pearson IV tables B/P/As/BF2 in Si)  ◐
      B, P, As tables (Rp, ΔRp, γ, β) over 10-200 keV, log-interpolated in
      energy, no extrapolation. BF2 not yet tabulated.
Milestone 2.2 — Implant simulation (Pearson IV + 2D lateral straggle + screening)  ◐
      Vertical Gaussian on (Rp, ΔRp) plus an erf lateral mask-edge blur
      (σ_lat ≈ 0.7·ΔRp); dose-conserving, implants accumulate. Open: full
      Pearson-IV shape from γ/β, tilt (accepted but ignored with a
      warning), screen oxides, per-column surface lookup.
Milestone 2.3 — Diffusion solver (FiPy + Fair model + OED)  ◐
      Intrinsic analytic Gaussian anneal (Recipe.anneal). Fair
      concentration-coupled anneal (apply_anneal_fair): explicit Euler
      on a Cartesian grid, harmonic-mean face D, stability-limited
      sub-steps. Not FiPy-based. Open: Fair via Recipe.anneal, OED, TED,
      segregation.
Milestone 2.4 — Process→device mesh translator (THE CORE PIECE)  ◐
      run_recipe(structure, recipe) runs topography → mesh → doping and
      hands a MeshField straight to DeviceSolver (examples/06). The RBF +
      nearest-neighbour field interpolator in opentcad/bridge (junction
      depth within 5% in tests) is not yet wired into run_recipe.

Exit: ✓ Full NMOS process flow simulated (examples/06_nmos_implanted.py);
      ✗ Vth within 20% of SKY130 published value — not yet checked.

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
      Models implemented with YAML parameters; values not yet fit to data.
Milestone 3.2 — Advanced DEVSIM physics (surface mobility, interface traps, BGN)  ◐
      Lombardi surface mobility and Slotboom BGN done; interface traps only
      as a compact mid-gap Dit term in flat_band_shift_V (no dynamic traps).
Milestone 3.3 — Calibration infrastructure (scipy optimizer, SKY130 target metrics)
      Not started.

Exit: NMOS Vth/Ion/SS within 10% of SKY130. All parameters cited.

## Phase 4 — Community (Ongoing)
Sphinx docs, tutorial notebooks, NEGF extension (NanoTCAD ViDES), GDS import.
