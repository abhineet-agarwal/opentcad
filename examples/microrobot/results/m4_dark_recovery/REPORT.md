# Nominal TT dark/recovery — incomplete run, reproducible power-down retention

**The requested 4.5 ms experiment aborts before relight. No dark reset or phase
clear is observed over its saved falling-light/dark interval. Separate completed
2.2 ms prefixes reproduce retained reset/enable state; they do not qualify recovery.**

This evidence is later than the frozen M4 17-case/670-hash review bundle and the
separate hot follow-up. Neither snapshot was modified or repackaged.

## Protocol, criteria and completion

Our optical history, in seconds and W/m², is `(0,0), (0.0001,0), (0.001,1000),
(0.0015,1000), (0.0016,0), (0.0031,0), (0.004,1000), (0.0045,1000)`. The fully
dark hold is 1.5 ms, followed by a 900 µs relight ramp. These are our diagnostic
choices, not published shadow/restart tolerances. Circuit, 2 pF logic storage,
two 1 pF actuator stores, TT models and Gear2/reltol=1e-6/abstol=1e-15 settings
remain unchanged from the qualified-LVT nominal circuit.

[Original criteria](criteria.json) were fixed before result review (SHA256
`c1b04511a85f1ddb693022da38dfb2e146755d1a04a1394ca5353d335a437665`).
The separate [prefix addendum](prefix_criteria_addendum.json) was fixed before
prefix comparison (SHA256
`1ddd614a7500e4c345b5ef5eab992c5570982cfb3b5537e7087af7f9cbab02b4`).
The analysis-specific [prefix criteria](prefix_criteria.json) are also retained.
Voltage fractions, guards and comparison tolerances are diagnostic conventions,
not PDK input-high, reset-removal or electrochemical safety specifications.

| Experiment | Requested stop | Actual stop | Finite rows | Status |
|---|---:|---:|---:|---|
| Original 50 ns dark/recovery | 4.5 ms | 3.00089994 ms | 83,479 | Rejected incomplete; `TRAN: Timestep too small`, `vdriverbuffer#branch` |
| Original 25 ns comparison | 4.5 ms | — | — | Skipped because reference failed |
| Separate 50 ns power-down prefix | 2.2 ms | 2.2 ms | 63,758 | Complete; numerical prefix checks pass |
| Separate 25 ns power-down prefix | 2.2 ms | 2.2 ms | 103,842 | Complete; numerical prefix checks pass |

The prefix decks retain the **entire original future illumination history**;
only their requested stop is shortened. They observe 0.6 ms of zero light, not
the full darkness/recovery protocol. They neither repair the 3 ms abort nor
convert the failed original run into a successful one. The planned 3.1 ms
end-dark state and 4.5 ms final state are **not reached** and remain null.

## Observed retention and qualified edges

Across the original saved interval from 1.5 to 3.00089994 ms, monitor-ready,
native reset and driver enable have **zero 10%, 50% or 90% crossings** of their
instantaneous supply domains. Their minimum normalized values are approximately
0.997822, 0.999582 and 0.999975. Event phases remain `pan=1, pbn=0` throughout
that interval; there is no observed brief reset/clear pulse. Falling absolute
voltages are not reset assertion. This retained state is distinct from the
numerical failure reported at the final timestep; a failing equation name does
not establish its cause.

At logic ≥1.6 V and native reset ≥90% of logic, with ±1 µs reset/rail guards,
the original and both prefixes each have **12 qualified clock rising edges,
one Q transition per edge, and no unmatched qualified Q transition**. Matching
uses the predefined **±0.5 µs** window. The original has three additional clock
rises and three Q changes at low rails, which are explicitly unqualified rather
than successes or missed valid edges. Every observed edge/exclusion is retained
in the edge reports. An initial analysis used a looser match window; the archived
final analysis corrects it to the fixed criterion without changing raw data.

The two prefixes agree within the declared numerical targets:

- Maximum 2.2 ms terminal voltage/eta difference: **5.84 µV**, below 1 mV.
- Largest corresponding meaningful crossing-time difference: **42.413 ns**, below 1 µs.
- Reset remains released below 1.6 V for **596.742 / 596.699 µs** in the 50/25 ns prefixes.
- Largest relative full-prefix source-energy difference for ports ≥1 pJ:
  **0.001446%**, below 1%. Smaller signed quantities are compared in absolute units.

These are reproducibility checks of power-down retention, not valid low-voltage
clock operation or complete brownout/recovery qualification. See
[prefix comparison](prefix_comparison.json) and
[common-interval comparison](original_prefix_common_interval.json).

## Clamp coverage and actual last state

The original/native-reset-low and actual-driver-low masks require logic ≥1 V,
actuator ≥0.5 V and the respective control ≤10% of its domain. Piecewise-linear
threshold intersections give mask durations of **113.081 / 119.153 µs**;
all are startup intervals. **Both masks overlap falling light and observed
darkness for zero seconds.** Their small measured clamp errors therefore do
not constitute a dark-clamp pass while reset/enable stayed high. Exact intervals
and prefix durations are in each case's `clamp_mask_review.json`.

Within their actual masks, original peak metal-minus-midpoint errors are
25.27 µV (native-reset-low) and 2.254 mV (actual-driver-low), below the chosen
50 mV diagnostic limit. The original largest electrode excursions outside the
actuator rails are 9.899 mV / 0.261 mV, below the chosen 100 mV limit. None is
a calibrated electrochemical safety bound.

The **last saved original state at 3.00089994 ms**, not the planned end-dark state:

| Quantity | Value |
|---|---:|
| Logic / actuator / PV midpoint | 1.104552 / 0.564239 / 0.272759 V |
| Native reset / driver enable | 1.104091 / 0.565250 V |
| Electrode metal A / B | 0.543170 / 0.0000669 V |
| Solution node A / B | 0.273150 / 0.271386 V |
| Local eta A / B | +0.270020 / −0.271319 V |
| Event phases A / B | 1 / 0 |

Retained electrode/adsorption charge is reported in
[terminal_state.json](tt_50ns/terminal_state.json). Neither zero stored rail
voltage nor instant neutral local eta is assumed. In this interval the drivers
are not commanded into their neutral clamp state.

## Signed energy and partial storage

Over **1.6–3.00089994 ms only**, the logic load port delivers **+1.1938 pJ**,
while the explicit 2 pF logic store loses **1.3645 pJ**. `Vlogic` is downstream
of that storage capacitor: its positive dark delivery is not photogenerated
solar energy. The actuator PV terminal probes are upstream of their stores and
report **−0.1123 pJ**, a signed return; the selected two 1 pF stores lose about
**0.1510 pJ**. These differently located ports and partial storage changes are
not a full energy-closure or efficiency calculation. Component deliveries are
subsets, not extra energy to add again. Full definitions and observed-window
boundaries are in [energy_windows.json](tt_50ns/energy_windows.json).

## Plots, provenance and reproduction

[Partial transient overview](dark_recovery_overview.png) marks the abort and
shows future illumination as **planned/dashed**, with no simulated state beyond
the saved stop. [Separate prefix pair](powerdown_prefix_pair.png) shows the
independent 50/25 ns numerical comparison. Small extrema-preserving previews
reproduce both figures; all metrics use full adaptive data, whose hashes are
recorded without shipping raw `.dat` files.

```sh
MPLCONFIGDIR=/tmp/opentcad-mpl python examples/microrobot/results/m4_dark_recovery/reproduce_plots.py
```

The current post-snapshot API reproduces the physical original protocol in a
fresh destination (the frozen review bundle predates `illumination_history`):

```python
from examples.microrobot.controller import run_diagnostic
history = [(0,0), (.0001,0), (.001,1000), (.0015,1000),
           (.0016,0), (.0031,0), (.004,1000), (.0045,1000)]
run_diagnostic('examples/microrobot/local_runs/dark_recovery_REPRO_NEW',
               driver_ready='qualified-lvt', stop_s=.0045, max_step_s=50e-9,
               illumination_history=history)
```

The adapter rejects an incomplete transient; a normal simulator exit is not
success. Archived exact decks include the extra read-only return/event saves
used by analysis. Default-deck equivalence and source/model provenance are in
[manifest.json](manifest.json) and the retained API-equivalence record.

## Next priority — not executed

Proceed with the canonical clock macro's analog layout independently of the
rejected integrated POR: reuse the qualified bias macro, keep the first native
DFF as a characterized schematic load, then require exact-source DRC/LVS and
extracted finite-PV startup/receiver-edge checks at matched timesteps. That
would validate a block, not a full controller. POR redesign remains a bounded
parallel diagnostic; no new layout, topology, PVT/gait or safety signoff was
performed here.
