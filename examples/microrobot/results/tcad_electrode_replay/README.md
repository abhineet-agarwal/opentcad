# Isolated full-electrode voltage replay

**Both networks complete 250 µs; peak terminal-current comparisons fail.** One native process completes in **3.78 s**, with **69575 × 27 finite values**, zero exit status and no abort. RC and stable nonlinear copies reach exactly 250 µs from zero. This establishes isolated voltage-replay completion only.

Coverage and eta comparisons pass: maximum difference between models is **31.81 pV** in eta and **5.07×10⁻¹²** in coverage; maximum eta difference from the interpolated benchmark is **4.06 nV**. Replayed metal potentials track the full PWL histories within **5.55×10⁻¹⁶ V**. Both models remain near theta 0.5 with peak |eta|≈18.528 µV.

Current results do not satisfy every predeclared comparison limit:

| Peak absolute current error (pA), A / B / Pt-return | Measured | Allowed | Verdict |
|---|---|---|---|
| RC vs benchmark |9.862 /9.981 /31.271 |14.550 /14.550 /24.099 | Pt fails |
| Stable vs benchmark |9.660 /9.918 /28.840 |14.550 /14.550 /24.099 | Pt fails |
| Stable vs RC |0.265 /0.090 /2.431 |1.477 /1.477 /1.955 | Pt fails |

The limits were fixed before execution: benchmark current floor 5 pA plus 2% of branch peak, cross-model floor 1 pA plus 0.1% of branch peak. They were not relaxed after seeing results. Saved terminal-current KCL peaks are **33.63 pA RC /33.95 pA stable**, while solution-resistor KCL residuals stay below **6.0×10⁻²² A**. Local terminal-versus-solution discrepancies reach **31.27 /28.84 pA**, and integrated charge residuals are at most **2.66×10⁻²⁰ C**. The original passive benchmark has a known **1.701 pA** local current discrepancy. Neither topology-level charge conservation nor small eta/coverage differences establish precise saved transient currents.

External signed source work is **5.37723×10⁻¹⁸ J RC /5.39079×10⁻¹⁸ J stable**; electrode energy-accounting residuals are **5.71×10⁻²¹ /1.93×10⁻²⁰ J**. These are externally powered replay quantities, not PV-to-actuator efficiency or end-to-end power validation. The completed replay points toward further coupled feedback/trajectory investigation, while current precision and the original cause remain unresolved. Passive RC and stable nonlinear models receive identical independent copies of the completed passive benchmark's absolute metal-A, metal-B and Pt-return voltage histories. All 14298 adaptive points are retained in a local-only PWL include; no raw waveform/stimulus is exported.

Both networks retain working/Pt-return interfaces, Cdl, adsorption state, RF and 10/10/1 MΩ electrolyte paths. PV, logic, drivers, clamps and supervisors are absent. Default operating-point initialization is used without seeds/UIC. Ideal replay voltage sources explicitly supply signed terminal work; this is not an end-to-end PV power or actuation test.

Same-time identical points may be removed, but conflicting duplicate events are rejected. The selected trace has no duplicate times. All voltage knots round-trip at 17 digits; interpolation is linear between samples. There is no bound on the original unknown between-sample voltage/derivative error. Removing feedback and prescribing metal voltages changes the problem; replay currents need not match every benchmark transient sample exactly. Comparisons use declared absolute floors plus peak-relative allowances, including the benchmark's known 1.701 pA local-current precision caveat.

Metrics compare coverage, local eta and terminal currents between models and with the interpolated benchmark, plus source-work, KCL and integrated charge residuals. All incomplete-trace checks are prefix-only. Complete replay would point toward investigating coupled feedback/trajectory with a reduced reproducer, not prove a cause or validate original large-signal electrochemistry. A nonlinear-copy failure would provide a smaller reproducer, not a simulator-defect declaration. No phase, bending or released-actuation claim follows.

```text
MPLCONFIGDIR=/tmp/opentcad-mpl .venv/bin/python -m examples.microrobot.tcad_electrode_replay
```

Fresh destinations are required. Exact compact deck template, log, provenance hashes and executed runner are retained; waveform-bearing includes and raw replay remain local. Prior evidence/defaults are unchanged. No fine, rescue, DD, layout, submission, publication, push or fabrication occurred.

Two focused simulator-free tests pass in 1.37 s; Ruff passes. They check duplicate/event rejection, round-trip knot formatting, complete isolated-network assembly and absence of controller/seeds. No waveform-bearing include or raw data is exported: the compact replay_template.spice references the local include used from local/native. The runner reconstructs it from the frozen benchmark. No repeat/refinement or tolerance/physics change occurred.

```text
MPLCONFIGDIR=/tmp/opentcad-mpl .venv/bin/python -m pytest tests/integration/test_tcad_electrode_replay.py -q
.venv/bin/python -m ruff check examples/microrobot/tcad_electrode_replay.py tests/integration/test_tcad_electrode_replay.py
```
