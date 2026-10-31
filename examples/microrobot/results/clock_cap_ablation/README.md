# Explicit extracted capacitance ablation diagnostic

**Reviewed and accepted as diagnostic evidence; no physical/electrical design acceptance.** Exactly one new 4 ms transient with a 25 ns maximum step was executed. The reviewed schematic and full-RC 25 ns baselines were reused without rerunning them.

The variant deletes all 374 explicit `C` elements from the reviewed `clock_rc.spice` (source SHA-256 `f5491783e4294a96d925a4674d76ce188e1333e018c80b41d02dbe212f75b9ea`). All 851 resistors, 29 FETs, seven intentional MIM instances, parameters, connectivity, comments and remaining lines are preserved verbatim. Device-model capacitances remain. This netlist is an artificial experiment, not a proposed physical design. `netlist.diff`, `deck.diff` and `metrics.json` establish the transformation; `sha256.json` hashes every exported artifact except itself.

| Case, all 25 ns | Clock Hz | Analog nW | First FF + feedback nW | Whole nW | Rail time average V | Rail min–max V | Steady Q rises / bench criterion |
|---|---:|---:|---:|---:|---:|---:|---|
| Schematic, reused | 13054.161954 | 42.646796 | 0.937543 | 43.584339 | 1.774970 | 1.678951–1.823501 | 10 / true |
| Full extracted RC, reused | 2927.580369 | 41.075002 | 1.641387 | 42.716389 | 1.739084 | 1.368941–1.825845 | 2 / false |
| Extracted R, explicit C removed, new | 12892.720442 | 42.850546 | 0.943425 | 43.793971 | 1.774970 | 1.678368–1.823450 | 10 / true |

Power and rail averages integrate full data over the exact common **2.4–4 ms** interval, with linear interpolation at its boundaries. This differs slightly from the original bench's integration starting at the first adaptive sample after 2.4 ms. Both the original reviewed metrics and the unchanged bench's exact sample-index criterion, recalculated offline, remain separately labelled in `metrics.json`. Energies in the new case are 68.560874 pJ analog and 1.509480 pJ receiver, totaling 70.070354 pJ over 1.6 ms. Separate internal bias-reference power is unavailable.

The diagnostic reaches **98.7633%** of schematic frequency and **4.40388×** full-RC frequency. The finite PV rail moves with the circuit. This recovery cannot be interpreted as an additive causal contribution from explicit capacitance, nor can the remaining frequency difference be assigned exclusively to resistance. The new variant has only one timestep and is **not convergence-qualified**. The reviewed baseline convergence results do not qualify this variant.

The recommended next physical variant uses stage-local placement and shorter raw/a/b/c/d routing while preserving all devices, intentional MIM capacitors and the bias circuit. Gate that variant on passing native and GDS-roundtrip DRC/LVS before one matched transient comparison, if useful. This recommendation has not been executed.

The new full transient contains **182155 rows and eight finite columns**, starts at zero, has nondecreasing time, and ends at exactly 0.004 s. The simulator returned **0 in 47.697243 s**, within the unchanged 180 s simulator timeout. No abort, `doAnalyses:` or timestep-too-small marker occurs. The log retains the PDK `m=xx` hierarchy warning and successful dynamic gmin stepping. Baseline full-data SHA-256 values match the reviewed evidence; their full-completion audits also pass.

Divider behavior is separate from completion. The existing requirement of **at least three Q rises** in the steady window is retained: the new case has ten, while full RC still has two and its bench divider frequency remains null. The sustained audit from 0.4 ms gives new Q/clock frequency ratio **0.499999983**, with exactly two clock rises between consecutive Q rises. All threshold-crossing times are retained in `metrics.json`; startup near-zero-rail crossings are excluded from the sustained audit. The full-RC two-rise observation does not establish divider failure, and a bench criterion result does not establish application acceptance.

The exact reviewed deck was reused by replacing only its embedded RC subcircuit with the variant. Supply, receiver, initialization, tolerance, startup, integration method and load lines are identical. Settings are tt, 26.85 °C, three fitted PV cells with assumed 150 µm²/cell current scaling, 1 µs dark then a 100 µs optical ramp, chosen 2 pF storage, 2 fF output load, real SKY130 DFF plus feedback inverter, Gear order 2, reltol 1e-6, abstol 1e-15, and zero-supply operating-point startup without UIC or seeded voltages. The PDK top-level library hash matches the reviewed baseline.

Executed from the repository root:

```text
.venv/bin/python -u examples/microrobot/results/clock_cap_ablation/run_diagnostic.py
.venv/bin/python -u examples/microrobot/results/clock_cap_ablation/run_diagnostic.py --audit-only
```

The first command refuses an existing `local_runs/clock_layout/clock_cap_ablation_25ns` directory and invokes ngspice once. The second command performs only read-only full-data analysis and compact evidence export; it never starts a simulator. The saved deck was executed directly with the same `ngspice -b clock.spice` invocation used by the existing bench. There was no regeneration, PVT, parameter sweep, additional transient, submission, publication, push or fabrication. Raw `clock.dat` remains local; no raw waveform or local reference PDF is exported.
