# OpenTCAD Phases

## Phase 0 — Skeleton and Device Simulation 
Goal: p-n junction and MOSFET IV curves with hand-specified doping. No process sim.

Milestone 0.1 — Shared data format (MeshField, Material enum, ContactTag)
Milestone 0.2 — Geometry DSL (Structure class, Gmsh wrapper, adaptive mesh)
Milestone 0.3 — Analytic doping (uniform, Gaussian profile specification)
Milestone 0.4 — DEVSIM bridge (MeshField → DEVSIM mesh, doping, contacts, materials)
Milestone 0.5 — Physics model library (constant mobility, SRH, ohmic contacts)

Exit: 1D p-n junction IV within 5% of Shockley; 2D MOSFET threshold behavior correct.

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

## Phase 2 — Doping Simulation 
Goal: Realistic implant+anneal profiles feeding device simulation.

Milestone 2.1 — Implant parameter database (Pearson IV tables B/P/As/BF2 in Si)
Milestone 2.2 — Implant simulation (Pearson IV + 2D lateral straggle + screening)
Milestone 2.3 — Diffusion solver (FiPy + Fair model + OED)
Milestone 2.4 — Process→device mesh translator (THE CORE PIECE)

Exit: Full NMOS process flow simulated; Vth within 20% of SKY130 published value.

## Phase 3 — Materials and Calibration 
Goal: Quantitative agreement with real fab data.

Milestone 3.1 — Materials database (Klaassen, Lombardi, Canali, SRH, Auger)
Milestone 3.2 — Advanced DEVSIM physics (surface mobility, interface traps, BGN)
Milestone 3.3 — Calibration infrastructure (scipy optimizer, SKY130 target metrics)

Exit: NMOS Vth/Ion/SS within 10% of SKY130. All parameters cited.

## Phase 4 — Community (Ongoing)
Sphinx docs, tutorial notebooks, NEGF extension (NanoTCAD ViDES), GDS import.
