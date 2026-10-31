"""Single logic-only TCAD cold-start isolation, with reset held asserted.

No actuator network, actuator PV, phase counter, electrode or native supervisor
is instantiated. This diagnostic cannot establish released controller behavior.
"""

import difflib
import json
import os
from pathlib import Path
import re
import shutil

import numpy as np

from . import tcad_controller as tc
from .controller import standard_cells, validate_transient
from .electrical import header

EVIDENCE = tc.HERE / "results/tcad_logic_isolation"
LOCAL = tc.HERE / "local_runs/tcad_logic_isolation"
STOP = 250e-6
REMOVED = [
    "both actuator PV stacks and their storage",
    "transistor actuator drivers and their midpoint ports",
    "working and Pt-return electrodes, electrolyte and solution resistors",
    "functional phase counter and phase output bridges",
    "actuator supervisor controls, numeric hysteresis state and driver-ready bridge",
    "native brownout, current-limited reset converter and qualified LVT receiver",
]


def build_deck(table):
    source = tc.build_deck(table)
    clock = re.search(r"(?ms)^\.subckt microrobot_clock\b.*?^\.ends[^\n]*", source).group()
    inverter = re.search(r"(?ms)^\.subckt micro_inv\b.*?^\.ends[^\n]*", source).group()
    pdk = Path(os.environ.get("PDK_ROOT", "/usr/local/share/pdk")) / "sky130A"
    pv = re.search(r"^Bpvlogic .*$", source, re.M).group()
    deck = header() + clock + "\n" + inverter + "\n" + standard_cells(pdk)
    deck += "\n* Logic-only isolation; same 4x1080 um2 TCAD source, no actuator network.\n"
    deck += "Vlight light 0 PWL(0 0 1u 0 101u 1000)\n" + pv + "\n"
    deck += """Clogic logic_raw 0 2p
Vlogic logic_raw logic 0
Vclock logic clock_supply 0
Xclock clk clock_supply 0 bn bp microrobot_clock
Coutput clk 0 2f
Vdigital logic digital_supply 0
Xff clk feedback reset_n 0 0 digital_supply digital_supply q0 sky130_fd_sc_hd__dfrtp_1
Xfeedback q0 0 0 digital_supply digital_supply feedback sky130_fd_sc_hd__inv_1
Vproxy logic proxy_supply 0
Xproxy clk flop_load proxy_supply 0 micro_inv
Xcproxy1 flop_load 0 sky130_fd_pr__cap_mim_m3_1 w=2 l=2
Xcproxy2 flop_load 0 sky130_fd_pr__cap_mim_m3_1 w=2 l=2
* Existing rail-powered 10k reset bridge, held low by signal-only zero control.
Vreset_control supervisor_state 0 0
Vsupervisor_reset logic supervisor_reset_supply 0
Bsupervisor_reset_hi supervisor_reset_supply reset_n I={(v(supervisor_reset_supply)-v(reset_n))*v(supervisor_state)/10000}
Bsupervisor_reset_lo reset_n 0 I={v(reset_n)*(1-v(supervisor_state))/10000}
"""
    vectors = "v(light) v(logic_raw) v(logic) v(clk) v(q0) v(reset_n) v(bn) v(bp) v(supervisor_state) i(Vlogic) i(Vclock) i(Vdigital) i(Vproxy) i(Vsupervisor_reset)"
    deck += f""".options method=gear maxord=2 reltol=1e-6 abstol=1e-15
.control
set wr_vecnames
set wr_singlescale
set numdgt=17
save {vectors}
tran 25n {STOP:.17g} 0 25n
wrdata controller.dat {vectors}
quit
.endc
.end
"""
    return deck


def analyze(columns, data, execution, table):
    complete = True
    failure = None
    try:
        validate_transient(data, len(columns), STOP)
        if (
            data[0, 0] != 0
            or abs(data[-1, 0] - STOP) > 1e-12
            or execution["aborted"]
            or execution["returncode"]
        ):
            raise RuntimeError("Start/stop mismatch, abort marker or nonzero exit")
    except RuntimeError as error:
        complete = False
        failure = str(error)
    result = {
        "complete": complete,
        "failure": failure,
        "requested_stop_s": STOP,
        "actual_stop_s": float(data[-1, 0]),
        "shape": list(data.shape),
        "finite": bool(np.isfinite(data).all()),
        "scope": "Held-reset logic-only diagnostic, no released-controller/phase/actuator acceptance",
    }
    if not result["finite"]:
        return result
    v = dict(zip(columns, data.T, strict=True))
    t = v["time"]
    logic = v["v(logic)"]
    powered = logic >= 1.4
    result["node_bounds"] = {
        name: {
            "minimum_V": float(v[f"v({name})"].min()),
            "maximum_V": float(v[f"v({name})"].max()),
            "final_V": float(v[f"v({name})"][-1]),
        }
        for name in ["logic", "reset_n", "clk", "q0", "bn", "bp", "supervisor_state"]
    }
    result["cell_domain_min_max_V"] = [
        float(v["v(logic_raw)"].min() / 4),
        float(v["v(logic_raw)"].max() / 4),
    ]
    result["DD_domain_pass"] = bool(
        v["v(logic_raw)"].min() / 4 >= -1e-9
        and v["v(logic_raw)"].max() / 4 <= table.voltage_V[-1] + 1e-9
    )
    result["first_logic_threshold_crossing_s"] = {
        str(x): float(t[np.flatnonzero(logic >= x)[0]]) if np.any(logic >= x) else None
        for x in [1.4, 1.45, 1.6, 1.94]
    }
    result["powered_logic_bench_upper_limit_1p94_pass"] = bool(not np.any(logic > 1.94))
    result["reset_held_command_pass"] = bool(np.max(abs(v["v(supervisor_state)"])) < 1e-12)
    result["powered_reset_max_abs_V"] = (
        float(np.max(abs(v["v(reset_n)"][powered]))) if powered.any() else None
    )
    result["powered_Q_max_abs_V"] = (
        float(np.max(abs(v["v(q0)"][powered]))) if powered.any() else None
    )
    result["powered_reset_below_0p1_logic"] = bool(
        powered.any() and np.all(v["v(reset_n)"][powered] < 0.1 * logic[powered])
    )
    result["powered_Q_below_0p1_logic"] = bool(
        powered.any() and np.all(abs(v["v(q0)"][powered]) < 0.1 * logic[powered])
    )
    rises = tc.crossings(t, v["v(clk)"] - 0.5 * logic)
    result["clock_rises_while_logic_ge_1p4_s"] = [
        float(x) for x in rises if np.interp(x, t, logic) >= 1.4
    ]
    return result


def run():
    if EVIDENCE.exists() or LOCAL.exists():
        raise FileExistsError("Logic-isolation destinations must be fresh")
    EVIDENCE.mkdir(parents=True)
    table = tc.load_table()
    deck = build_deck(table)
    prior = (tc.HERE / "results/tcad_controller_supervisor_control/nominal_25ns.spice").read_text()
    source = re.search(r"^Bpvlogic .*$", deck, re.M).group()
    if source != re.search(r"^Bpvlogic .*$", prior, re.M).group():
        raise RuntimeError("Logic TCAD source changed; prior verification not reusable")
    if not json.loads((tc.EVIDENCE / "source_validation.json").read_text())["passed"]:
        raise RuntimeError("Prior source verification required")
    tc.write_json(
        EVIDENCE / "configuration.json",
        {
            "scope": __doc__,
            "removed_components": REMOVED,
            "stop_s": STOP,
            "max_step_s": 25e-9,
            "reset": "Asserted throughout via existing 10k rail-powered bridge",
            "logic_PV": "Four series cells,1080um2 each; same conditional dark/light DD superposition",
            "logic_storage_F": 2e-12,
            "optical_ramp": "1us dark then linear ramp to1000W/m2 at101us",
            "source_expression_unchanged": True,
            "source_verification_sha256": tc.sha(tc.EVIDENCE / "source_validation.json"),
            "clock_source_sha256": tc.sha(tc.CLOCK),
            "light_source_sha256": tc.sha(tc.LIGHT),
            "dark_source_sha256": tc.sha(tc.DARK),
        },
    )
    tc.write_json(
        EVIDENCE / "execution_counts.json",
        {
            "transients": 1,
            "fine_runs": 0,
            "rescue_runs": 0,
            "DC_runs": 0,
            "DD_runs": 0,
            "layout_runs": 0,
        },
    )
    shutil.copy2(Path(__file__), EVIDENCE / "runner_as_executed.py")
    (EVIDENCE / "deck.diff").write_text(
        "".join(
            difflib.unified_diff(
                prior.splitlines(True),
                deck.splitlines(True),
                fromfile="supervisor_control",
                tofile="logic_isolation",
            )
        )
    )
    execution = tc.execute(LOCAL, deck)
    for source, target in [
        ("bench.spice", "logic_isolation.spice"),
        ("ngspice.log", "ngspice.log"),
        ("execution.json", "execution.json"),
    ]:
        shutil.copy2(LOCAL / source, EVIDENCE / target)
    if (LOCAL / "controller.dat").exists():
        columns, data = tc.read_data(LOCAL / "controller.dat")
        result = analyze(columns, data, execution, table)
        result["raw_sha256"] = tc.sha(LOCAL / "controller.dat")
        result["raw_local_path"] = str(LOCAL / "controller.dat")
    else:
        result = {"complete": False, "failure": "No transient output"}
    tc.write_json(EVIDENCE / "metrics.json", result)
    interpretation = (
        "Completion suggests the removed actuator-coupled network is required for the previous abort under these benches; it does not establish a root cause."
        if result["complete"]
        else "The shared logic path also aborts and needs further diagnosis; the trouble equation alone does not establish a root cause."
    )
    tc.write_json(
        EVIDENCE / "status.json",
        {
            "status": "Complete held-reset logic isolation"
            if result["complete"]
            else "Incomplete held-reset logic isolation",
            "interpretation": interpretation,
            "acceptance": "Pending Astra review",
        },
    )
    (EVIDENCE / "README.md").write_text(f"""# TCAD logic-only startup isolation

Requested exactly one **250 µs / 25 ns** cold-start transient, with no fine or rescue run. Complete: **{result["complete"]}**. {interpretation}

The four-series 1080 µm²/cell TCAD logic source, compact extracted clock, native resettable DFF/feedback, switched-capacitor digital proxy, 2 pF storage, optical ramp and Gear2 solver are retained. Reset is held asserted throughout by the existing rail-powered 10 kΩ bridge; its zero-valued numerical control supplies no analog gate charge. Removed components are explicit in configuration.json and deck.diff: all actuator PV/storage/driver/electrode/solution networks, phase counter/phase bridges, actuator supervisor controls and native supervisor components. No DD, native DC or layout run is added because the logic source expression is exactly unchanged from the verified source.

Metrics report complete finite coverage from zero to250 µs, abort/exit checks, per-cell DD domain, rail/reset/native-clock/Q bounds and held-reset behavior. Logic1.4–1.94 V are engineering bench limits, not foundry specifications. No released-controller, native POR, phase, bending or autonomous operation is accepted by this diagnostic. Raw data remain local; exact deck/log, source snapshot, diff and hashes are retained. No defaults or prior evidence are changed.

```text
MPLCONFIGDIR=/tmp/opentcad-mpl .venv/bin/python -m examples.microrobot.tcad_logic_isolation
```

The runner refuses existing destinations. No submission, publication, push or fabrication occurred.
""")
    tc.write_json(
        EVIDENCE / "sha256.json",
        {
            p.name: tc.sha(p)
            for p in sorted(EVIDENCE.iterdir())
            if p.is_file() and p.name != "sha256.json"
        },
    )
    print(json.dumps(result, indent=2))
    return result


if __name__ == "__main__":
    run()
