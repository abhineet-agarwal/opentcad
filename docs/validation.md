# Validation

What OpenTCAD checks itself against, how closely, and where the check lives.
**Tolerance** is what the test enforces; **measured** is what a run produced when
it was recorded. A model being present is not the same as it being calibrated; see
[What is not validated](#what-is-not-validated).

## Device simulation

| Check | Reference | Tolerance | Measured | Test |
|---|---|---|---|---|
| p-n diode I–V slope | Shockley equation | 5 % | — | `tests/device/test_pn_junction_integration.py` |
| Equilibrium bulk potentials of a pn diode | ±kT·ln(N/n_i) | 1 mV | — | `tests/device/test_snapshot.py` |
| Mass action at equilibrium | n·p = n_i² | 0.1 % | — | `tests/device/test_snapshot.py` |
| Law of the junction at 0.4 V forward | n·p/n_i² = exp(V/V_t) | 1 % | — | `tests/device/test_snapshot.py` |
| MOS-cap surface potential in strong inversion | ≈ 2·φ_F | 25 % | — | `tests/device/test_mos_capacitor.py` |
| Low-frequency C–V | accumulation → C_ox; depletion minimum | C_dep < 0.4·C_ox | — | `tests/device/test_cv_sweep.py` |
| Small-signal C in accumulation | C_ox | 5 % | — | `tests/device/test_ac_sweep.py` |
| HF C–V ratio (Nₐ = 10¹⁷, 10 nm oxide) | textbook shape | — | C_ox/C_min ≈ 4.6 | `examples/11_mos_hfcv.py` |
| NMOS turn-on | on/off at V_ds = 50 mV | > 10³ | ≈ 10¹⁰ (hand-doped and implanted) | `tests/device/test_nmos_idvg.py` |
| Chained analyses on one solver | the same sweep twice | 10⁻⁶ | — | `tests/device/test_solver_api.py` |
| Joyce–Dixon contact offsets | Boltzmann at low doping; departs from Blakemore above ~3.7·N_c | — | — (series stated accurate to < 1 % for n ≤ 3×10²⁰ in Si) | `tests/device/test_joyce_dixon.py` |
| Fixed oxide charge | sign of the surface-potential shift; linearity in Q_f | ratio of shifts for 10× Q_f in 8–12 | — | `tests/device/test_interface_qf.py` |

## Process simulation

| Check | Reference | Tolerance | Measured | Test |
|---|---|---|---|---|
| Oxide thickness, dry and wet, 1000–1100 °C | analytic Deal–Grove | 5 % | — | `tests/process/test_oxidation.py` |
| LOCOS: field oxide at the window centre; untouched masked regions; bird's beak | unmasked Deal–Grove | — | — | `tests/process/test_oxidation.py` |
| Pearson profiles reproduce the tabulated moments | R_p, ΔR_p, γ, β tables | 0.1 % (R_p, ΔR_p), 0.01 (γ), 1 % (β) | — | `tests/process/test_pearson.py` |
| Implant dose conserved at any tilt and mask | dose per wafer area | — | — | `tests/process/test_implant_geometry.py` |
| Anneal: dose conservation; spread ⟨d²⟩ = 2Dt | Fick's law | — | — | `tests/process/test_anneal.py`, `test_fair_anneal.py`, `test_species_anneal.py` |
| Junction depth independent of the device mesh (20 nm vs 5 nm) | itself | 5 % | 1.4 % intrinsic, 0.3 % Fair | `tests/process/test_junction_refinement.py` |
| Deposited MOS cap vs layered MOS cap | C–V of the same device built two ways | 10 % | 2–6 % | `tests/process/test_structure_transfer.py` |
| Per-material etch selectivity | rate ratios | — | — | `tests/process/test_selectivity.py` |

## The SKY130 NMOS threshold check (Phase 2 exit)

A 1 µm NMOS is built from a recipe using:
- SkyWater's published oxide thickness (4.148 nm), p-well profile and junction
  depth;
- a stand-in boron threshold implant, sized once by a 1-D design formula and then
  simulated untuned.

Its threshold voltage is compared with the same extraction applied to SkyWater's
`nfet_01v8` typical-corner model card in ngspice:

| | OpenTCAD | SKY130 | Difference |
|---|---|---|---|
| Vth, max-gm extrapolation | 0.679 V | 0.592 V | +14.8 % |
| Vth, 100 nA·W/L | 0.588 V | 0.547 V | +7.5 % |
| S/D junction depth | 100.3 nm | 100 nm | +0.3 % |

Pass band ±20 %, converged to < 10 mV between 10 nm and 7 nm meshes. Passing shows
the process-to-device chain agrees with first-order design and lands in SkyWater's
range. It does not show that OpenTCAD predicts SkyWater's unpublished process.
Details, inputs and caveats: [`validation/sky130/README.md`](https://github.com/abhineet-agarwal/opentcad/blob/main/validation/sky130/README.md);
test: `tests/validation/test_sky130_vth.py`.

## Packaging and data integrity

| Check | Result | Where |
|---|---|---|
| Clean wheel install without optional extras runs the test suite | 287 passed, 12 skipped, 0 failed (slow excluded) | [releasing.md](releasing.md) |
| MeshField save/load keeps every contact field | exact | `tests/geometry/test_formats.py` |
| Catalog export → import into another catalog | identical pinned revisions | `tests/catalog/test_cli.py` |
| Simulation file → dump → load | identical | `tests/io/test_deck.py` |

## What is not validated

- **Calibration:** no physics parameter has been fitted to measured or PDK data
  (Phase 3). Lombardi's literature coefficients leave the simulated
  transconductance of the SKY130-like NMOS plateauing, with its peak about 25 %
  below SkyWater's.
- **Avalanche breakdown voltage:** qualitative only (~2–3× high), because the
  current is a v_sat·n proxy.
- **Topography:** the geometric etch and deposition models aren't compared with
  measured profiles.
- **Short-channel behaviour:** the SKY130 comparison deliberately uses L = 1 µm,
  since the stand-in recipe has no pocket implants.
- **Microrobot application:** its evidence and limits are recorded separately in
  [`examples/microrobot/`](https://github.com/abhineet-agarwal/opentcad/blob/main/examples/microrobot/README.md).

Add a row here whenever you add a check, and say what it does not show.
