# Device physics

`DeviceSolver` turns a `MeshField` into a DEVSIM device and solves Poisson plus
electron and hole continuity (drift–diffusion, Scharfetter–Gummel fluxes, automatic
Jacobians). Insulator regions are solved for Poisson only; potential is continuous
across semiconductor/insulator interfaces.

```python
from opentcad.device.solver import DeviceSolver
from opentcad.device.physics import PhysicsConfig
from opentcad.device.models import Lombardi, Canali, Klaassen, SRH, Auger, Slotboom

solver = DeviceSolver(
    meshfield,
    {"Silicon": load_material("Si"), "SiO2": load_material("SiO2")},
    temperature_K=300.0,
    physics=PhysicsConfig(mobility=Lombardi(base=Canali(base=Klaassen())),
                          recombination=[SRH(), Auger()], bgn=Slotboom()))
```

The default physics is Boltzmann statistics, constant mobility, SRH and no
bandgap narrowing. Units: inputs in µm and cm⁻³; DEVSIM's centimetres are handled
internally. Currents are per unit width, in A/cm.

## Contacts

| Contact | How it's set | Behaviour |
|---|---|---|
| Ohmic | `contact_type="ohmic"` (default) | Charge-neutral, equilibrium carrier densities |
| Schottky | `contact_type="schottky"`, `work_function_eV=…` | Metal–semiconductor barrier |
| Gate | Any contact on an insulator layer | Metal on oxide; `flat_band_shift_V` packs φ_MS, Q_f and mid-gap D_it into one number |

A physically located fixed oxide charge is
`interface_Qf_C_per_cm2={"SI": (Qf, y_interface_um)}`. It is a Gaussian-smeared
sheet (σ = `interface_Qf_width_um`, default 5 nm) inside the semiconductor, and
complements the compact `flat_band_shift_V`.

## Physics models

| Kind | Model | Notes |
|---|---|---|
| Mobility | `ConstantMobility` | Default; the file's `mobility_constant` |
| Mobility | `Klaassen` | Unified low-field bulk mobility (1992), clustering and carrier–carrier scattering |
| Mobility | `Canali` | High-field velocity saturation; wraps any base model |
| Mobility | `Lombardi` | Surface mobility at Si/SiO₂ (bulk + acoustic phonon + surface roughness). `e_normal_axis="y"` (default), `"x"` or `"magnitude"`. Coefficients from the material file's `mobility_lombardi` block (Si.yaml: Darwish 1997) |
| Recombination | `SRH` | Default; lifetimes from the file; mid-gap trap (n₁ = p₁ = n_i). The file's `Et_eV` is not used yet |
| Recombination | `Auger` | Dominates above ~10¹⁸ cm⁻³ |
| Recombination | `Radiative` | Negligible in Si; for direct-gap materials |
| Generation | `Avalanche` | van Overstraeten–de Man α(E). The current uses a v_sat·n proxy, so the breakdown voltage is qualitative (~2–3× high) |
| Bandgap narrowing | `NoBGN`, `Slotboom` | Slotboom raises n_i,eff in heavily doped regions |
| Statistics | `Boltzmann`, `FermiDirac`, `JoyceDixon` | Fermi–Dirac via Blakemore. Joyce–Dixon fixes the contact offsets past ~3.7·N_c; bulk densities stay Blakemore |

Models are composed in `PhysicsConfig` and named in simulation files (`klaassen`,
`lombardi`, `srh` …). New ones are plugins ([plugins.md](plugins.md#physics-models)).

## Materials

Parameters live in YAML files under
[`opentcad/materials/params/`](https://github.com/abhineet-agarwal/opentcad/tree/main/opentcad/materials/params), or in any folder you
register. Each file cites its sources.

- **Every material** needs `permittivity_relative`.
- **A semiconductor** (anything without `is_insulator: true`) also needs:
  - the band structure: `bandgap.Eg_eV_300K`, `electron_affinity_eV`,
    `Nc_cm3_300K`, `Nv_cm3_300K`, `ni_cm3_300K`
  - the constant mobilities
  - the SRH lifetimes

  A missing one is an error, never filled with silicon's value.
- **Model-specific blocks** may be omitted: `mobility_klaassen`,
  `mobility_lombardi`, `velocity_saturation`, the Auger/radiative coefficients and `avalanche`. The
  loader records them in `MaterialParams.defaulted`. A model that needs one then
  refuses to run on that material and says what to add.
- **Process variants:** `load_material("Si", process="mylab")` loads
  `mylab/Si.yaml`. A missing variant is an error, not a silent fallback.
- **Calibrated variants** are process variants too. `opentcad.calibrate` fits
  parameters to reference data and writes the result as one, with a
  `calibration` block saying what was fitted and to what
  ([Calibration](calibration.md)).

Shipped today: `Si.yaml` (complete) and `SiO2.yaml` (insulator). The `Material`
enum has more entries (Si₃N₄, poly-Si, GaN, SiC, …) than there are parameter
files. `load_material` names the files that exist when one is missing, and the
solver refuses a region whose material has no parameters.

## Analyses

All are methods on the solver, and also reachable by name via
`solver.run(name, **kwargs)` and in simulation files.

| Name | Method | Result |
|---|---|---|
| `iv` | `iv_sweep(anode, cathode, v_start, v_end, v_step, hold_contacts=…, measure_contact=…)` | (V, I) |
| `cv` | `cv_sweep(terminal, reference, …)` | Quasi-static (low-frequency) C(V) |
| `transient` | `transient_sweep(bias_schedule, times, integrator="bdf1"/"bdf2"/"tr")` | Currents over time |
| `ac` | `ac_sweep(terminal, reference, frequencies, dc_bias=…)` | Small-signal Y(f) = G + jωC on a gate. Declare `ac_terminals=[…]` when constructing the solver |
| `fields` | `field_snapshot(biases={…})` | A MeshField copy with `Potential`, `Electrons`, `Holes` |

Analyses can be chained on one solver. Each starts from all contacts at 0 V: the
first runs the staged equilibrium solve, and later ones ramp the biases back down.
DEVSIM keeps devices in global state and solves all live ones together, so call
`solver.close()` before building another solver in the same process.

### Field snapshots

`solver.snapshot()` and the `fields` analysis copy the solution back onto the mesh:

- **`Potential`:** in V, relative to the intrinsic level, with the Fermi level at
  0 V in equilibrium.
- **`Electrons`, `Holes`:** in cm⁻³. Zero in insulators; at an interface node the
  semiconductor's value is used.
- **Contact biases:** recorded in `metadata`.
- **Electric field:** computed per triangle from the potential
  (`opentcad.viz.fields.electric_field_V_per_cm`).

The GUI draws all four as maps, and `opentcad run` writes them as `.vtu`.

### Extraction

`opentcad.device.extract.vth_max_gm(vgs, ids, vds)` and
`vth_constant_current(vgs, ids, i_crit)` apply the same definitions to simulated
and reference curves. Sweeps expose them as metrics.

## Limits

- Avalanche uses a current proxy, so the breakdown voltage isn't calibrated
  (needs edge-aware |J_n|, |J_p|).
- Lombardi's interface normal is a global axis per region; curved interfaces need
  a per-element projection. Its coefficients are literature values, not fits. With
  them, the simulated transconductance of a 1 µm SKY130-like NMOS plateaus instead
  of peaking, which is the first calibration target.
- Small-signal AC works on gates only, not ohmic or Schottky terminals.
- SRH ignores the trap energy `Et_eV` given in material files (it assumes a
  mid-gap trap).
- There's no quantum correction (density gradient), band-to-band tunnelling,
  dynamic traps or hydrodynamic transport.
- Everything is 2-D.
