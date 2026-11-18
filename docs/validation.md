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
| Anneal next to an oxide: dose stays in the Si, oxide doping untouched | no-flux wall at the interface | 10⁻⁹ | 10⁻¹⁵ | `tests/process/test_anneal_walls.py` |
| Anneal profile at a Si/SiO₂ wall | reflecting-wall (image) solution | 3 % | — | `tests/process/test_anneal_walls.py` |
| Fair junction depth behind a wall vs bare Si | the same column without the cap (grid refined to 2.5 nm) | 2 % | 0.8 % | `tests/process/test_anneal_walls.py` |
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
| Vth, max-gm extrapolation | 0.697 V | 0.592 V | +17.7 % |
| Vth, 100 nA·W/L | 0.599 V | 0.547 V | +9.6 % |
| S/D junction depth | 99.9 nm | 100 nm | −0.1 % |

Pass band ±20 %. Between 10 nm and 7 nm meshes Vth changes by 10 mV (max-gm) and 2 mV (constant current). Passing shows
the process-to-device chain agrees with first-order design and lands in SkyWater's
range. It does not show that OpenTCAD predicts SkyWater's unpublished process.
Details, inputs and caveats: [`validation/sky130/README.md`](https://github.com/abhineet-agarwal/opentcad/blob/main/validation/sky130/README.md);
test: `tests/validation/test_sky130_vth.py`.

## SKY130 calibration (Phase 3)

The same 1 µm NMOS, calibrated against SkyWater's model card in two stages
([Calibration](calibration.md)):

1. **Electrostatics.** The stand-in channel implant's dose and drive-in are fitted
   to SkyWater's threshold at five body biases. The Phase 2 stand-in had twice
   SkyWater's body effect; the rms error over the biases drops from 248 mV to
   19 mV.
2. **Mobility.** The Lombardi electron coefficients are fitted to the linear
   Id–Vgs at equal overdrive. The curve's rms error drops from 0.247 to 0.092,
   but only by pushing the phonon coefficient to 24× its literature value. The
   remaining error is systematic (−15 % to +12 % across the overdrive range), so
   the fitted values are effective, not a physical calibration.

| | Phase 2 stand-in | Calibrated | SkyWater |
|---|---|---|---|
| Vth, max-gm | +17.7 % | −0.1 % | 0.592 V |
| Vth, 100 nA·W/L | +9.6 % | −8.8 % | 0.547 V |
| Subthreshold swing | +5.0 % | −4.5 % | 84.7 mV/dec |
| Peak gm | −25.7 % | +4.3 % | 13.7 µS/µm |
| Ion (Vgs = Vds = 1.8 V) | −39.5 % | −3.6 % | 139.6 µA/µm |

Threshold, subthreshold swing and Ion all meet the Phase 3 target of 10 %. Ion
needed velocity saturation driven by the quasi-Fermi gradient, now Canali's
default. With the electric field along each mesh edge as the driving force, the
calibrated Ion is 86.7 µA/µm (−37.9 %) and doesn't respond to mobility at all.
Oblique edges in the channel pick up the vertical gate field.
Details: [`validation/sky130/README.md`](https://github.com/abhineet-agarwal/opentcad/blob/main/validation/sky130/README.md#calibration-phase-3);
tests: `tests/validation/test_sky130_calibration.py`.

## Packaging and data integrity

| Check | Result | Where |
|---|---|---|
| Clean wheel install without optional extras runs the test suite | 287 passed, 12 skipped, 0 failed (slow excluded) | [releasing.md](releasing.md) |
| MeshField save/load keeps every contact field | exact | `tests/geometry/test_formats.py` |
| Catalog export → import into another catalog | identical pinned revisions | `tests/catalog/test_cli.py` |
| Simulation file → dump → load | identical | `tests/io/test_deck.py` |

## What is not validated

- **Calibration:** the SKY130 calibration above is against a compact model, not
  measured silicon, at one gate length and 300 K. Its mobility values are
  effective (a systematic residual remains). Ion uses Canali's quasi-Fermi
  driving force, whose density reference (10¹⁵ cm⁻³) is a numerical choice:
  10¹⁴ and 10¹⁶ give −3.5 % and −5.2 %.
- **Avalanche breakdown voltage:** qualitative only (~2–3× high), because the
  current is a v_sat·n proxy.
- **Topography:** the geometric etch and deposition models aren't compared with
  measured profiles.
- **Short-channel behaviour:** the SKY130 comparison deliberately uses L = 1 µm,
  since the stand-in recipe has no pocket implants.
- **Microrobot application:** its evidence and limits are recorded separately in
  [`examples/microrobot/`](https://github.com/abhineet-agarwal/opentcad/blob/main/examples/microrobot/README.md).

Add a row here whenever you add a check, and say what it does not show.
