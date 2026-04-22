# OpenTCAD Phases

## Phase 0 — Skeleton and Device Simulation (6-8 weeks)
Goal: p-n junction and MOSFET IV curves with hand-specified doping. No process sim.

Milestone 0.1 — Shared data format (MeshField, Material enum, ContactTag)
Milestone 0.2 — Geometry DSL (Structure class, Gmsh wrapper, adaptive mesh)
Milestone 0.3 — Analytic doping (uniform, Gaussian profile specification)
Milestone 0.4 — DEVSIM bridge (MeshField → DEVSIM mesh, doping, contacts, materials)
Milestone 0.5 — Physics model library (constant mobility, SRH, ohmic contacts)

Exit: 1D p-n junction IV within 5% of Shockley; 2D MOSFET threshold behavior correct.

## Phase 1 — Process Topography (10-14 weeks)
Goal: ViennaPS etch/deposition/oxidation producing geometry for device sim.

Milestone 1.1 — ViennaPS wrapper (TopographySimulator class, recipe definition)
Milestone 1.2 — Etch models (isotropic wet, anisotropic RIE via ViennaRay, masked)
Milestone 1.3 — Deposition models (conformal, PVD)
Milestone 1.4 — Oxidation (Deal-Grove + moving boundary coupled to ViennaPS)

Exit: LOCOS isolation structure simulated correctly; gate oxide thickness within 5%.

## Phase 2 — Doping Simulation (10-14 weeks)
Goal: Realistic implant+anneal profiles feeding device simulation.

Milestone 2.1 — Implant parameter database (Pearson IV tables B/P/As/BF2 in Si)
Milestone 2.2 — Implant simulation (Pearson IV + 2D lateral straggle + screening)
Milestone 2.3 — Diffusion solver (FiPy + Fair model + OED)
Milestone 2.4 — Process→device mesh translator (THE CORE PIECE)

Exit: Full NMOS process flow simulated; Vth within 20% of SKY130 published value.

## Phase 3 — Materials and Calibration (8-12 weeks)
Goal: Quantitative agreement with real fab data.

Milestone 3.1 — Materials database (Klaassen, Lombardi, Canali, SRH, Auger)
Milestone 3.2 — Advanced DEVSIM physics (surface mobility, interface traps, BGN)
Milestone 3.3 — Calibration infrastructure (scipy optimizer, SKY130 target metrics)

Exit: NMOS Vth/Ion/SS within 10% of SKY130. All parameters cited.

## Phase 4 — Community (Ongoing)
Sphinx docs, tutorial notebooks, NEGF extension (NanoTCAD ViDES), GDS import.
