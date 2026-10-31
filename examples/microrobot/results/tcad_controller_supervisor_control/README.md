# Provisional functional-supervisor control

**Reviewed and accepted as failed functional-supervisor control evidence; end-to-end operation remains unvalidated.** This control also aborts before supervisor release. The sole 8 ms / 25 ns request saves **4930 × 49 finite values through 81.533843 µs**, then reports `TRAN: Timestep too small; time = 8.15338e-05, timestep = 3.125e-20: trouble with node "vsupervisor_driver#branch"`. Ngspice returns zero but the transient aborts. The trouble equation does not establish a numerical or physical root cause. No fine or rescue run followed.

Final logic / actuator span / midpoint are **1.577998 / 1.821612 / 0.910804 V**. Reset ranges from **−1.392224 to +0.381344 mV** and driver-ready from **−125.632 to +54.044 µV**. The numerical supervisor remains OFF throughout this prefix. Because the trace ends before **200 µs**, ON qualification, hysteresis cycling, restart and released controller operation are **untested in simulation**; focused unit tests check the reference contract and deck construction only. No complete phase cycle, alternating actuator operation, coverage modulation or bending validation follows. Passing energy/clamp/KCL checks describe the prefix only. The tiny assumed-curvature trace is numerical postprocessing, not actuator validation. See `prefix_observations.json` for full ranges.

Ten focused simulator-free tests pass, including global-latch restart after either rail falls OFF; Ruff passes. Exact current-source expressions match the previously verified sources. Execution counts remain **one transient, zero fine/rescue, zero new DC/DD/layout runs**.

This separate control preserves the initial failed native-supervisor attempt. It removes instantiated native brownout, current-limited reset converter and qualified LVT receiver and their current probes. A single global hysteretic state starts OFF, holds reset asserted and driver enable disabled until 200 µs, turns ON only with logic ≥1.60 V and actuator span ≥1.50 V, and turns OFF if either rail reaches 1.45 / 1.40 V respectively. Re-enable requires both ON thresholds again. A voltage-controlled hysteretic switch computes this state from the minimum normalized rail qualification; its isolated numerical reference supplies no analog gate charge. Reset and driver-ready outputs instead charge through independent measured 10 kΩ bridges from logic and actuator rails.

Supervisor quiescent power is **uncharacterized**, not characterized as zero. This is a provisional functional control, with no native POR or autonomous-controller acceptance. Native compact extracted clock, resettable first DFF/feedback, two XSPICE counter bits (/8), switched-capacitor digital proxy, measured phase bridges, transistor drivers, Pt midpoint, electrode models, TCAD PWL sources, optical ramp, storage and solver remain as in the initial integration. The eight conceptual PV cells remain 1080 µm² each. Final /8192 and full RTL power are untested. Coverage/curvature is a short-window assumed response, not mechanical steady state, force or walking.

Exactly one 8 ms / 25 ns transient was requested. No fine or rescue run is permitted on this branch. Native DD PWL source verification is reused because every source expression is unchanged; no DC, DD or layout run was added. Metrics use all adaptive samples; passing checks on incomplete data apply only to the observed prefix. Raw transients remain local. Exit zero alone is not acceptance.

```text
MPLCONFIGDIR=/tmp/opentcad-mpl .venv/bin/python -m examples.microrobot.tcad_supervisor_control
```

The runner refuses existing destinations. Exact deck, log, counts, metrics, source hashes and waveform plot are retained here; local raw data are excluded. No submission, publication, push or fabrication occurred.

Validation commands:

```text
MPLCONFIGDIR=/tmp/opentcad-mpl .venv/bin/python -m pytest tests/integration/test_tcad_supervisor_control.py tests/integration/test_tcad_controller.py -q
.venv/bin/python -m ruff check examples/microrobot/tcad_controller.py examples/microrobot/tcad_supervisor_control.py tests/integration/test_tcad_supervisor_control.py
```

The isolated 1 V reference and 1 GΩ numerical state load implement a signal variable only: no electrical connection transfers its charge to reset, driver-ready or physical supply nodes. Its numerical current is not a measured model of supervisor quiescent power. Physical reset and driver-ready bridge currents are included separately in the source-port audit. No zero-quiescent-power claim is made. `runner_as_executed.py` and `tcad_controller_as_executed.py` preserve the executed source, while the initial integration evidence remains separately frozen.
