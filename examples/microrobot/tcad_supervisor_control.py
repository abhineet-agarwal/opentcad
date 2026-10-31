"""One provisional functional-supervisor control; native POR is excluded.

The ideal supervisory state controls conductances only. Native DFF, physical
drivers and all analog gate charging draw energy from measured TCAD rails.
Supervisor quiescent power remains uncharacterized, not characterized as zero.
"""

from pathlib import Path
import json
import re
import shutil

import numpy as np

from . import tcad_controller as tc

EVIDENCE = tc.HERE / "results/tcad_controller_supervisor_control"
LOCAL = tc.HERE / "local_runs/tcad_controller_supervisor_control"


def supervisor_state(logic, actuator, time):
    """Contract reference: global latch, initial OFF, both ON needed to restart."""
    enabled = False
    states = []
    for lv, av, instant in zip(logic, actuator, time, strict=True):
        if instant < 200e-6 or lv <= 1.45 or av <= 1.40:
            enabled = False
        elif lv >= 1.60 and av >= 1.50:
            enabled = True
        states.append(enabled)
    return np.asarray(states)


def build_deck(table):
    deck = tc.build_deck(table)
    for line in [
        "Vresetlogic logic reset_supply 0",
        "Vresetact act reset_act_supply 0",
        "Xready ready reset_n reset_act_supply reset_supply 0 bp microrobot_ready_levelshift",
        "Vmonitor act monitor_supply 0",
        "Xmonitor bn ready monitor_supply 0 microrobot_brownout",
        "Vdriverbuffer act driverbuffer_supply 0",
        "Xdriverbuffer reset_n ready driver_ready driverbuffer_supply 0 microrobot_ready_driver_qualified_lvt",
    ]:
        if deck.count(line + "\n") != 1:
            raise ValueError("Native supervisor line mismatch: " + line)
        deck = deck.replace(line + "\n", "")
    for vector in ["v(ready)", "i(Vresetlogic)", "i(Vresetact)", "i(Vmonitor)", "i(Vdriverbuffer)"]:
        deck = deck.replace(vector + " ", "")
    bridge = """
* PROVISIONAL functional supervisor. Global hysteresis state, initially OFF.
* Logic ON/OFF=1.60/1.45 V; actuator span ON/OFF=1.50/1.40 V.
* The minimum normalized qualification gives both-ON restart after either-OFF.
* Numerical state circuit is isolated from all physical power ports.
* Supervisor physical quiescent power is uncharacterized, NOT known zero.
Bsupervisor_input supervisor_input 0 V={time<200u ? -1 : min((v(logic)-1.45)/0.15,(v(act)-1.40)/0.10)}
Vsupervisor_numeric_reference supervisor_numeric_reference 0 1
Ssupervisor supervisor_numeric_reference supervisor_state supervisor_input 0 supervisor_hysteresis
Rsupervisor_numeric_state supervisor_state 0 1g
.model supervisor_hysteresis SW(Ron=1 Roff=1e30 Vt=0.5 Vh=0.5)
* Independent real power ports for reset and driver-ready gate charging.
Vsupervisor_reset logic supervisor_reset_supply 0
Bsupervisor_reset_hi supervisor_reset_supply reset_n I={(v(supervisor_reset_supply)-v(reset_n))*v(supervisor_state)/10000}
Bsupervisor_reset_lo reset_n 0 I={v(reset_n)*(1-v(supervisor_state))/10000}
Vsupervisor_driver act supervisor_driver_supply 0
Bsupervisor_driver_hi supervisor_driver_supply driver_ready I={(v(supervisor_driver_supply)-v(driver_ready))*v(supervisor_state)/10000}
Bsupervisor_driver_lo driver_ready 0 I={v(driver_ready)*(1-v(supervisor_state))/10000}
"""
    deck = deck.replace(".options method=gear", bridge + "\n.options method=gear")
    extra = "v(supervisor_input) v(supervisor_state) i(Vsupervisor_reset) i(Vsupervisor_driver) "
    deck = deck.replace("save ", "save " + extra, 1)
    deck = deck.replace("wrdata controller.dat ", "wrdata controller.dat " + extra, 1)
    # Verify source reuse before executing: this path performs no native DC rerun.
    original_sources = re.findall(r"^Bpv.*$", tc.build_deck(table), flags=re.M)
    if re.findall(r"^Bpv.*$", deck, flags=re.M) != original_sources:
        raise ValueError("TCAD source expressions changed")
    return deck


def analyze_contract(columns, data):
    v = dict(zip(columns, data.T, strict=True))
    t = v["time"]
    logic = v["v(logic)"]
    act = v["v(act)"]
    reference = supervisor_state(logic, act, t)
    observed = v["v(supervisor_state)"] > 0.5
    differences = np.flatnonzero(reference != observed)
    # An equality at a threshold may differ by one saved adaptive point.
    away_from_threshold = (abs(v["v(supervisor_input)"]) > 1e-6) & (
        abs(v["v(supervisor_input)"] - 1) > 1e-6
    )
    command_bad = (reference != observed) & away_from_threshold
    bridge_reset = v["v(reset_n)"] - 0.5 * logic
    bridge_driver = v["v(driver_ready)"] - 0.5 * act
    changes = np.flatnonzero(np.diff(observed.astype(int)) != 0) + 1
    released = (act >= 0.5) & (bridge_driver > 0)
    return {
        "scope": "Functional global supervisor; native reset/POR and supervisor quiescent power uncharacterized",
        "gates": {
            "supervisor_matches_global_hysteresis": not bool(command_bad.any()),
            "supervisor_off_before_200us": not bool(observed[t < 200e-6].any()),
            "driver_not_released_before_200us": not bool(released[t < 200e-6].any()),
        },
        "command_transition_samples": [
            {
                "time_s": float(t[i]),
                "enabled": bool(observed[i]),
                "logic_V": float(logic[i]),
                "actuator_V": float(act[i]),
            }
            for i in changes
        ],
        "reference_mismatch_samples": int(len(differences)),
        "mismatch_away_from_threshold_samples": int(command_bad.sum()),
        "reset_release_crossings_s": tc.crossings(t, bridge_reset).tolist(),
        "driver_release_crossings_s": tc.crossings(t, bridge_driver).tolist(),
    }


def run():
    if EVIDENCE.exists() or LOCAL.exists():
        raise FileExistsError("Supervisor-control destinations must be fresh")
    EVIDENCE.mkdir(parents=True)
    table = tc.load_table()
    deck = build_deck(table)
    preflight = json.loads((tc.EVIDENCE / "source_validation.json").read_text())
    if not preflight["passed"]:
        raise RuntimeError("Prior identical PWL source verification is required")
    tc.write_json(
        EVIDENCE / "configuration.json",
        {
            "scope": __doc__,
            "logic_ON_OFF_V": [1.60, 1.45],
            "actuator_ON_OFF_V": [1.50, 1.40],
            "initial_state": False,
            "hold_reset_until_s": 200e-6,
            "rearm": "Both ON thresholds after either OFF",
            "supervisor_quiescent_power": "Uncharacterized; no native POR or autonomous-controller claim",
            "analog_bridge_ohm": 10000,
            "counter_divider": 8,
            "duration_s": tc.STOP,
            "max_step_s": 25e-9,
            "source_expressions_unchanged": True,
            "source_verification_reused_sha256": tc.sha(tc.EVIDENCE / "source_validation.json"),
            "initial_attempt_status_sha256": tc.sha(tc.EVIDENCE / "status.json"),
            "light_table_sha256": tc.sha(tc.LIGHT),
            "dark_archive_sha256": tc.sha(tc.DARK),
            "clock_source_sha256": tc.sha(tc.CLOCK),
            "area_each_um2": 1080,
            "total_area_um2": 8640,
            "logic_series": 4,
            "each_actuator_half_series": 2,
            "logic_storage_F": 2e-12,
            "each_half_storage_F": 1e-12,
            "DD_superposition": "Same conditional archived dark plus fresh R=.3 light table; irradiation scaling approximated",
            "mechanics": "Assumed 50ms relaxation, 1e5/m curvature span; no force/contact/walking model",
        },
    )
    tc.write_json(
        EVIDENCE / "execution_counts.json",
        {
            "native_DC_runs": 0,
            "DD_runs": 0,
            "layout_runs": 0,
            "nominal_transients": 1,
            "fine_transients": 0,
            "rescue_transients": 0,
        },
    )
    shutil.copy2(Path(__file__), EVIDENCE / "runner_as_executed.py")
    execution = tc.execute(LOCAL, deck)
    for source, target in [
        ("bench.spice", "nominal_25ns.spice"),
        ("ngspice.log", "nominal_25ns.log"),
        ("execution.json", "execution.json"),
    ]:
        shutil.copy2(LOCAL / source, EVIDENCE / target)
    if (LOCAL / "controller.dat").exists():
        columns, data = tc.read_data(LOCAL / "controller.dat")
        result = tc.analyze(columns, data, execution, table)
        contract = analyze_contract(columns, data)
        result["gates"].update(contract["gates"])
        result["all_gates_pass"] = all(result["gates"].values())
        result["supervisor_contract"] = contract
        result["raw_local_path"] = str(LOCAL / "controller.dat")
        result["raw_sha256"] = tc.sha(LOCAL / "controller.dat")
        result["scope"] = (
            "Complete experiment only if complete=true; all prefix checks otherwise prefix-only. Functional supervisor excludes native POR and uncharacterized quiescent power."
        )
        tc.plot_case(columns, data, EVIDENCE / "nominal_25ns.png")
    else:
        result = {"complete": False, "all_gates_pass": False, "failure": "No transient output"}
    tc.write_json(EVIDENCE / "metrics.json", result)
    status = (
        "Functional supervisor control gates passed; no native POR or autonomous claim"
        if result["all_gates_pass"]
        else "Blocked: provisional supervisor control did not pass complete functional gates; no further run"
    )
    tc.write_json(
        EVIDENCE / "status.json", {"status": status, "acceptance": "Pending Astra review"}
    )
    (EVIDENCE / "README.md").write_text(f"""# Provisional functional-supervisor control

{status}.

This separate control preserves the initial failed native-supervisor attempt. It removes instantiated native brownout, current-limited reset converter and qualified LVT receiver and their current probes. A single global hysteretic state starts OFF, holds reset asserted and driver enable disabled until 200 µs, turns ON only with logic ≥1.60 V and actuator span ≥1.50 V, and turns OFF if either rail reaches 1.45 / 1.40 V respectively. Re-enable requires both ON thresholds again. A voltage-controlled hysteretic switch computes this state from the minimum normalized rail qualification; its isolated numerical reference supplies no analog gate charge. Reset and driver-ready outputs instead charge through independent measured 10 kΩ bridges from logic and actuator rails.

Supervisor quiescent power is **uncharacterized**, not characterized as zero. This is a provisional functional control, with no native POR or autonomous-controller acceptance. Native compact extracted clock, resettable first DFF/feedback, two XSPICE counter bits (/8), switched-capacitor digital proxy, measured phase bridges, transistor drivers, Pt midpoint, electrode models, TCAD PWL sources, optical ramp, storage and solver remain as in the initial integration. The eight conceptual PV cells remain 1080 µm² each. Final /8192 and full RTL power are untested. Coverage/curvature is a short-window assumed response, not mechanical steady state, force or walking.

Exactly one 8 ms / 25 ns transient was requested. No fine or rescue run is permitted on this branch. Native DD PWL source verification is reused because every source expression is unchanged; no DC, DD or layout run was added. Metrics use all adaptive samples; passing checks on incomplete data apply only to the observed prefix. Raw transients remain local. Exit zero alone is not acceptance.

```text
MPLCONFIGDIR=/tmp/opentcad-mpl .venv/bin/python -m examples.microrobot.tcad_supervisor_control
```

The runner refuses existing destinations. Exact deck, log, counts, metrics, source hashes and waveform plot are retained here; local raw data are excluded. No submission, publication, push or fabrication occurred.
""")
    tc.write_json(
        EVIDENCE / "sha256.json",
        {
            p.name: tc.sha(p)
            for p in sorted(EVIDENCE.iterdir())
            if p.is_file() and p.name != "sha256.json"
        },
    )
    print(
        json.dumps(
            {k: result.get(k) for k in ["complete", "actual_stop_s", "all_gates_pass", "failure"]},
            indent=2,
        )
    )
    return result


if __name__ == "__main__":
    run()
