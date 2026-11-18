# Calibration

The models ship with literature coefficients. Calibration fits some of them to
reference data, such as measured curves or a foundry's compact model, and
records the result as a material file you can load by name.

`opentcad.calibrate` does the generic part:

- **[`Parameter`](api/calibrate.md#parameter):** one coefficient the fit may
  change. It's named as a dotted material field, such as
  `"mobility_lombardi.delta_e"`, and has bounds.
- **[`fit`](api/calibrate.md#fit):** bounded nonlinear least squares over your
  residual function. Each residual evaluation is usually a full device
  simulation, so the finite-difference Jacobian can run in parallel processes.
- **[`apply_overrides`](api/calibrate.md#apply_overrides):** a copy of a
  `MaterialParams` with fitted values set, checked like a file.
- **[`write_material_variant`](api/calibrate.md#write_material_variant):** the
  result as a process-variant material file, with a `calibration` block saying
  what was fitted, to what and from which starting values.

## A fit in outline

```python
import numpy as np
from opentcad.calibrate import Parameter, apply_overrides, fit, write_material_variant
from opentcad.materials.database import load_material

def residuals(values):
    """Simulate with `values` and compare with the reference."""
    si = apply_overrides(load_material("Si"), values)
    ...                                     # build the device, run the sweep
    return simulated / reference - 1.0      # one number per comparison point

params = [Parameter("mobility_lombardi.delta_e", 3.58e18, 1e16, 1e20),
          Parameter("mobility_lombardi.C_e", 1.70e4, 1e3, 1e6)]
result = fit(residuals, params, workers=3)
print(result.values, result.rms, result.correlation)

write_material_variant("my_materials/mylab/Si.yaml", load_material("Si"), result.values,
                       calibration={"status": "fitted",
                                    "calibrated_against": "what the reference is",
                                    "notes": "conditions the values are valid for"})
```

Then register the folder and load the variant:

```python
from opentcad.plugins import register_data_dir
register_data_dir("materials", "my_materials")
si = load_material("Si", process="mylab")
```

Some practical points:

- **Parallel runs.** With `workers > 1`, `residuals` must be a module-level
  function, because each worker process imports it. DEVSIM keeps one global state
  per process, so processes are what parallelise it.
- **Log scale.** `Parameter(log=True)`, the default, fits `log10` of the value.
  That suits coefficients that move by factors. Use `log=False` for exponents
  and offsets.
- **Read the correlation.** `FitResult.correlation` comes from the Jacobian at
  the solution. Entries near ±1 mean the data can't tell two parameters apart:
  fix one of them, or add data that separates them.
- **Bounds.** `FitResult.at_bound` lists parameters that ended on a bound. Such a
  result is the best inside the bounds, not a minimum of the problem.
- **Effective values.** A fitted coefficient absorbs everything the simulation
  leaves out. Write the conditions of the fit into the `calibration` block, and
  don't reuse the values outside them.

## SKY130: electrostatics, then mobility

The first calibration is against SkyWater's `nfet_01v8` model card, at
L = 1 µm. It lives in
[`validation/sky130/calibrate.py`](https://github.com/abhineet-agarwal/opentcad/blob/main/validation/sky130/calibrate.py)
and runs in two stages:

1. **Electrostatics.** SkyWater doesn't publish its threshold-adjust implant.
   The stand-in implant's dose and drive-in are fitted to SkyWater's threshold
   at five body biases. The body effect depends on the depletion charge, not on
   mobility, so this pins the channel doping before any mobility is fitted.
2. **Mobility.** The Lombardi electron coefficients are fitted to SkyWater's
   linear Id–Vgs, compared at equal gate overdrive so that any remaining
   threshold difference stays out of the mobility.

```bash
python -m validation.sky130.calibrate electrostatics
python -m validation.sky130.calibrate sensitivity      # which coefficients the curve can tell apart
python -m validation.sky130.calibrate scan             # a coarse grid of two of them, far from the start
python -m validation.sky130.calibrate mobility         # writes validation/sky130/materials/sky130/Si.yaml
python -m validation.sky130.calibrate report
```

[Validation](validation.md#sky130-calibration-phase-3) has the results.
