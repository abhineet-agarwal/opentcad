# Post-snapshot hot numerical follow-up — branch stopped

This supplement is **later than the frozen M4 submission snapshot**: its
17-case compact archive and 670-file-hash-verified export were not modified.
The original Gear2 hot failure belongs to that snapshot. The zero-probe and
Gear1 controls below are subsequent bounded attempts, kept separate here.
The snapshot's statement that no rescue run followed applies to that snapshot;
it does not describe this later supplement.

## Actual attempts

All use the same TT qualified-LVT circuit at 85 C, photovoltaic fit temperature
fixed at 26.85 C, optical ramp beginning at 100 us, reltol=1e-6,
abstol=1e-15 A, 50 ns maximum step, requested stop 0.8 ms and no auxiliary
energy states. No transistor sizing, physical component value, illumination
or tolerance relaxation was introduced.

| Control | Only change | Actual stop | Finite rows | Reported failing equation |
|---|---|---:|---:|---|
| Original Gear2, all probes | Frozen reference | 101.757103 us | 2,230 | `vdriverbuffer#branch` |
| Gear2, qualifier probe removed | Ideal-wire replacement of zero-V probe; its current saves/component metric omitted | 81.2994395 us | 1,778 | `vmonitor#branch` |
| Gear1, original all-probe circuit | `maxord=2` becomes `maxord=1` only | 101.750561 us | 3,734 | `vdriverbuffer#branch` |

All three abort with `TRAN: Timestep too small`, timestep 6.25e-20 s, after
completed dynamic gmin stepping. Simulator normal exit was correctly rejected
by the adapter. Full requested-stop completion was not achieved in any hot run.
The conditional 25 ns Gear1 check was **not run**, and this numerical branch
was stopped without another variant or rescue cascade.

At the Gear1 abort, light is only 1.94507 W/m², logic 33.04 uV and actuator
0.447017 mV. The original Gear2 abort has similarly unpowered rails. The
zero-probe control stops before light begins, with nanovolt rails. No meaningful
powered-state native-clock, clamp, phase, source-power or leakage qualification
can be inferred. Small partial values are not accepted operating performance.

Gear1/backward Euler adds numerical damping; it is **not a physical fix**.
Changing integration order alone did not resolve the observed failure. Removing
the ideal measurement probe also did not resolve it. A reported branch name is
a failing Newton equation, not proof of a unique physical or numerical cause.
These controls neither establish a physical hot-startup failure nor provide hot
waveform/timestep agreement. The prior scoped TT 2 ms nominal result is unchanged.

## Exact evidence and integrity

Each case directory contains the exact `bench.spice`, full `ngspice.log` and
`failure_review.json`. `summary.json` records actual stop times, row counts,
netlist hashes and raw local-directory paths. `gear1_50ns.diff` proves the
single integration-order change from the original all-probe hot deck;
`hot85_no_probe.diff` records the separate earlier ideal-wire control.
Full adaptive `.dat` files remain in ignored local runs and are not copied here.

`manifest.json` records SHA256 for every compact evidence/report file other
than the manifest itself; hashes were recomputed and verified after writing.
Only documentation/evidence files were added. Core source, circuits, frozen
export/archive and the final 195-test pass remain unchanged; tests and notebooks
were not repeated for this supplement.

Recommended next priority, **not executed**: a separate bounded nominal
short-light-pulse darkness/recovery test. Audit the hot numerical/model behavior
offline rather than starting another topology search or tolerance-rescue chain.
