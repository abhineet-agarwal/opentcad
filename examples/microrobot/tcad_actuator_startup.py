"""One held-input actuator-network startup add-back; no released operation."""

import difflib
import json
from pathlib import Path
import re
import shutil

import numpy as np

from . import tcad_controller as tc
from . import tcad_logic_isolation as logic
from . import tcad_supervisor_control as control
from .controller import phase_netlist

EVIDENCE = tc.HERE / "results/tcad_actuator_startup"
LOCAL = tc.HERE / "local_runs/tcad_actuator_startup"


def build_deck(table):
    deck = control.build_deck(table)
    deck = deck.replace(phase_netlist(bits=2), "")
    for name in [
        "microrobot_brownout",
        "microrobot_ready_levelshift",
        "microrobot_ready_driver_qualified_lvt",
    ]:
        deck = re.sub(r"(?ms)^\.subckt " + name + r"\b.*?^\.ends[^\n]*\n?", "", deck)
    for prefix in [
        "Bsupervisor_input ",
        "Vsupervisor_numeric_reference ",
        "Ssupervisor ",
        "Rsupervisor_numeric_state ",
        ".model supervisor_hysteresis ",
        "Bclock_norm ",
        "Breset_norm ",
        "Xphases ",
    ]:
        deck = re.sub(r"^" + re.escape(prefix) + r".*\n", "", deck, flags=re.M)
    deck = deck.replace("v(supervisor_input) ", "")
    deck = re.sub(
        r"(?ms)^\* PROVISIONAL functional supervisor.*?^\* Independent real power ports[^\n]*\n",
        "* Held-low reset and driver-ready bridges; supervisor state circuitry absent.\n",
        deck,
    )
    deck = deck.replace(
        "* Native first DFF plus TWO functional bits: real-time /8 experiment.",
        "* Native first DFF remains held in reset; event counter is absent.",
    )
    deck = deck.replace(
        ".options method=gear",
        """* Fixed signal-only commands. Gate charge comes only from existing rail-powered bridges.
Vreset_control supervisor_state 0 0
Vphase_command_A pan 0 0
Vphase_command_B pbn 0 0
.options method=gear""",
    )
    deck = re.sub(r"^tran .*$", f"tran 25n {logic.STOP:.17g} 0 25n", deck, flags=re.M)
    return deck


def analyze(columns, data, execution, table):
    result = logic.analyze(columns, data, execution, table)
    result["scope"] = (
        "Held reset, driver-ready and phase inputs only; no released-controller, phase/gait, bending or autonomous acceptance"
    )
    if not np.isfinite(data).all():
        return result
    v = dict(zip(columns, data.T, strict=True))
    t = v["time"]
    lv, av, mv = (v[f"v({name})"] for name in ["logic", "act", "mid"])

    def integrate(power):
        return float(np.trapezoid(power, t))

    cell = np.array([v["v(logic_raw)"] / 4, v["v(celllo)"] / 2, (v["v(cellhi)"] - mv) / 2])
    result["all_PV_cell_bounds_V"] = [float(cell.min()), float(cell.max())]
    result["all_PV_DD_domain_pass"] = bool(
        cell.min() >= -1e-9 and cell.max() <= table.voltage_V[-1] + 1e-9
    )
    result["actuator_node_bounds"] = {
        name: {
            "minimum_V": float(v[f"v({name})"].min()),
            "maximum_V": float(v[f"v({name})"].max()),
            "final_V": float(v[f"v({name})"][-1]),
        }
        for name in ["act", "mid", "driver_ready", "pa", "pb", "ea", "eb"]
    }
    result["held_phase_commands_pass"] = bool(
        np.max(abs(v["v(pan)"])) < 1e-12 and np.max(abs(v["v(pbn)"])) < 1e-12
    )
    ready_domain = av >= 0.5
    result["powered_driver_ready_max_abs_V"] = (
        float(np.max(abs(v["v(driver_ready)"][ready_domain]))) if ready_domain.any() else None
    )
    result["driver_not_released"] = bool(
        not np.any(ready_domain & (v["v(driver_ready)"] > 0.5 * av))
    )
    reset_domain = (lv >= 1) & (av >= 0.5) & (v["v(reset_n)"] <= 0.1 * lv)
    metal_error = np.maximum(abs(v["v(ea)"] - mv), abs(v["v(eb)"] - mv))
    result["global_metal_midpoint_error_V"] = float(metal_error.max())
    result["qualified_reset_clamp_peak_V"] = (
        float(metal_error[reset_domain].max()) if reset_domain.any() else None
    )
    excursion = float(
        max(
            0,
            -v["v(ea)"].min(),
            -v["v(eb)"].min(),
            (v["v(ea)"] - av).max(),
            (v["v(eb)"] - av).max(),
        )
    )
    result["electrode_rail_excursion_V"] = excursion
    eta = np.array([v["v(ea)"] - v["v(sa)"], v["v(eb)"] - v["v(sb)"], v["v(er)"] - v["v(sr)"]])
    theta = np.array([v["v(ta)"], v["v(tb)"], v["v(tr)"]])
    cap = np.array([40e-12, 40e-12, 400e-12])[:, None]
    qmax = np.array([260e-12, 260e-12, 2600e-12])[:, None]
    rf = np.array([10e9, 10e9, 1e9])[:, None]
    ads = qmax / 0.02 * (1 / (1 + np.exp(-np.clip(eta / 0.08, -700, 700))) - theta)
    currents = np.array([v["i(Vea)"], v["i(Veb)"], v["i(Vreturn)"]])
    solution_i = np.array(
        [
            (v["v(sa)"] - v["v(bulk)"]) / 10e6,
            (v["v(sb)"] - v["v(bulk)"]) / 10e6,
            (v["v(sr)"] - v["v(bulk)"]) / 1e6,
        ]
    )
    power = (
        lv
        * tc.AREA
        * np.array(
            [
                table.current(x, light, 1)
                for x, light in zip(np.clip(cell[0], 0, 0.7), v["v(light)"])
            ]
        )
        + mv * v["i(Vpvlo)"]
        + (av - mv) * v["i(Vpvhi)"]
    )
    loads = {
        name: integrate(lv * v[f"i({port})"])
        for name, port in [
            ("clock", "Vclock"),
            ("native_DFF_feedback", "Vdigital"),
            ("digital_proxy", "Vproxy"),
            ("phase_bridges", "Vphase"),
            ("drivers_logic", "Vdriverslogic"),
            ("reset_bridge", "Vsupervisor_reset"),
        ]
    }
    loads.update(
        {
            name: integrate(av * v[f"i({port})"])
            for name, port in [
                ("driver_ready_bridge", "Vsupervisor_driver"),
                ("drivers_upper", "Vdriversact"),
            ]
        }
    )
    loads["drivers_mid"] = integrate(mv * v["i(Vdriversmid)"])
    loads["Pt_return"] = integrate(mv * v["i(Vreturn)"])
    store = 1e-12 * lv**2 + 0.5e-12 * (mv**2 + (av - mv) ** 2)
    pv = integrate(power)
    delta = float(store[-1] - store[0])
    residual = pv - delta - sum(loads.values())
    cdl = float((0.5 * cap * (eta**2 - eta[:, 0, None] ** 2))[:, -1].sum())
    adsorption = integrate(np.sum(eta * ads, axis=0))
    faradaic = integrate(np.sum(eta**2 / rf, axis=0))
    solution = integrate(np.sum(solution_i**2 * np.array([10e6, 10e6, 1e6])[:, None], axis=0))
    electrode = integrate(np.sum(np.array([v["v(ea)"], v["v(eb)"], v["v(er)"]]) * currents, axis=0))
    result["bookkeeping_scope"] = (
        "Whole requested diagnostic if complete, otherwise saved prefix only; no released-operation power claim"
    )
    result["energy_J"] = {
        "PV_delivered": pv,
        "storage_delta": delta,
        "measured_load_ports": loads,
        "supply_residual": residual,
        "electrode_metal_port_work": electrode,
        "double_layer_delta": cdl,
        "signed_adsorption_work": adsorption,
        "Faradaic_loss": faradaic,
        "solution_resistive_loss": solution,
        "electrode_residual": electrode - cdl - adsorption - faradaic - solution,
    }
    result["solution_KCL_max_A"] = float(abs(solution_i.sum(axis=0)).max())
    result["electrode_terminal_solution_current_difference_max_A"] = float(
        abs(currents - solution_i).max()
    )
    result["diagnostic_checks"] = {
        "complete": result["complete"],
        "DD_domain": result["all_PV_DD_domain_pass"],
        "logic_below_1p94": result["powered_logic_bench_upper_limit_1p94_pass"],
        "inputs_held": result["reset_held_command_pass"]
        and result["held_phase_commands_pass"]
        and result["driver_not_released"],
        "reset_clamp_below_50mV": result["qualified_reset_clamp_peak_V"] is not None
        and result["qualified_reset_clamp_peak_V"] < 0.05,
        "electrodes_within_100mV_of_rails": excursion < 0.1,
        "supply_energy_2percent": abs(residual) < max(abs(pv) * 0.02, 1e-15),
        "electrode_energy_2percent": abs(electrode - cdl - adsorption - faradaic - solution)
        < max(abs(electrode) * 0.02, 1e-15),
        "solution_KCL_1pA": result["solution_KCL_max_A"] < 1e-12,
    }
    return result


def run():
    if EVIDENCE.exists() or LOCAL.exists():
        raise FileExistsError("Actuator-startup destinations must be fresh")
    EVIDENCE.mkdir(parents=True)
    table = tc.load_table()
    deck = build_deck(table)
    prior = (tc.HERE / "results/tcad_controller_supervisor_control/nominal_25ns.spice").read_text()
    if re.findall(r"^Bpv.*$", deck, re.M) != re.findall(r"^Bpv.*$", prior, re.M):
        raise RuntimeError("Prior verified TCAD sources changed")
    tc.write_json(
        EVIDENCE / "configuration.json",
        {
            "scope": __doc__,
            "restored": "Two TCAD actuator half-stacks, storage, transistor drivers, working/Pt-return electrode and electrolyte networks",
            "held_low": "Reset, driver-ready and phase commands via existing measured 10k rail-powered bridges",
            "absent": "Event counters and supervisor state circuitry",
            "duration_s": logic.STOP,
            "max_step_s": 25e-9,
            "TCAD_source_expressions_unchanged": True,
            "logic_cells": 4,
            "cells_per_actuator_half": 2,
            "area_each_um2": 1080,
            "storage_logic_F": 2e-12,
            "storage_each_actuator_half_F": 1e-12,
            "source_verification_sha256": tc.sha(tc.EVIDENCE / "source_validation.json"),
            "light_sha256": tc.sha(tc.LIGHT),
            "dark_sha256": tc.sha(tc.DARK),
            "clock_sha256": tc.sha(tc.CLOCK),
        },
    )
    tc.write_json(
        EVIDENCE / "execution_counts.json",
        {"transients": 1, "fine": 0, "rescue": 0, "DC": 0, "DD": 0, "layout": 0},
    )
    shutil.copy2(Path(__file__), EVIDENCE / "runner_as_executed.py")
    baseline = (logic.EVIDENCE / "logic_isolation.spice").read_text()
    (EVIDENCE / "deck.diff").write_text(
        "".join(
            difflib.unified_diff(
                baseline.splitlines(True),
                deck.splitlines(True),
                fromfile="accepted_logic_isolation",
                tofile="held_actuator_startup",
            )
        )
    )
    execution = tc.execute(LOCAL, deck)
    for source, target in [
        ("bench.spice", "actuator_startup.spice"),
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
        result = {"complete": False, "failure": "No transient data"}
    tc.write_json(EVIDENCE / "metrics.json", result)
    tc.write_json(
        EVIDENCE / "status.json",
        {
            "status": "Complete held-input actuator add-back"
            if result["complete"]
            else "Incomplete held-input actuator add-back",
            "acceptance": "Pending Astra review",
            "causal_limit": "This altered bench cannot uniquely identify a root cause; trouble equation alone is not causal evidence",
        },
    )
    (EVIDENCE / "README.md").write_text(f"""# Held-input actuator-network startup add-back

One **250 µs / 25 ns** cold-start diagnostic. Complete: **{result["complete"]}**. Reset, driver-ready and both phase commands are held low through the existing measured rail-powered 10 kΩ bridges. Signal-only zero controls supply no analog gate charge. Event counter and supervisor-state circuitry are absent. No fine, rescue, DC, DD or layout run is added.

The passing logic-isolation core is retained: identical four-series TCAD logic source, compact extracted clock, native resettable DFF/feedback, switched-capacitor proxy, ramp, 2 pF storage and solver. This add-back restores both two-series TCAD actuator half-stacks, 1 pF storage per half, physical midpoint, transistor drivers and full working/Pt-return electrode and solution network. All eight conceptual cells retain1080 µm² each. The conditional dark/light superposition and characterized domain are unchanged; exact source expressions match the previously verified deck.

Metrics cover finite completion, DD/rail limits, held-input/reset clamps and signed electrical energy/KCL bookkeeping. Incomplete traces support prefix checks only. The engineering limits are not foundry or electrochemical safety specifications. This diagnostic provides no released-controller, phase/gait, bending or autonomous-operation validation. Any reported trouble equation is not an established root cause; passing this altered bench also would not uniquely isolate the previous cause.

```text
MPLCONFIGDIR=/tmp/opentcad-mpl .venv/bin/python -m examples.microrobot.tcad_actuator_startup
```

Fresh destinations are required. Exact deck/log/diff, executed runner and metrics are retained; raw data remain local. Prior accepted evidence is unchanged. No publication, submission, push or fabrication occurred.
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
            {
                k: result.get(k)
                for k in ["complete", "actual_stop_s", "failure", "diagnostic_checks"]
            },
            indent=2,
        )
    )
    return result


if __name__ == "__main__":
    run()
