"""Bounded TCAD-table → native controller → electrode functional experiment.

This explicitly changed /8 experiment uses the real clock and first resettable
DFF, two XSPICE counter bits and rail-powered functional phase bridges. It is
not the /8192 controller, a published robot reproduction or a walking model.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time

import numpy as np

from .controller import phase_netlist, standard_cells, validate_transient
from .electrical import header
from .pv import PVTable

HERE = Path(__file__).resolve().parent
EVIDENCE = HERE / "results/tcad_controller"
LOCAL = HERE / "local_runs/tcad_controller"
LIGHT = HERE / "results/pv_calibration_feasibility/dd_curves.json"
DARK = HERE / "results/pv.json"
CLOCK = HERE / "results/clock_compact_convergence/clock.spice"
AREA = 1080.0
STOP = 0.008


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


def load_table():
    light = json.loads(LIGHT.read_text())["baseline_R0p3"]
    dark = json.loads(DARK.read_text())["dark"]
    for key, expected in [("mesh_um", 0.04), ("nodes", 2515), ("lifetime_s", 1e-5)]:
        if light[key] != expected or dark[key] != expected:
            raise ValueError("Dark/light physical configuration mismatch: " + key)
    if light["reflectance"] != 0.3 or dark["irradiance_W_m2"] != 0:
        raise ValueError("Unexpected optical reference")
    table = PVTable.from_results(dark, light)
    if not all(
        np.isfinite(x).all()
        for x in [table.voltage_V, table.dark_delivered_A_um2, table.photocurrent_A_um2]
    ):
        raise ValueError("Nonfinite DD table")
    if np.any(np.diff(table.voltage_V) <= 0):
        raise ValueError("DD voltage grid must increase")
    return table


def pwl(variable, voltage, current):
    pairs = ",".join(f"{v:.17g},{i:.17g}" for v, i in zip(voltage, current, strict=True))
    return f"pwl({variable},{pairs})"


def current_expression(table, variable, light="v(light)/1000", area=AREA):
    dark = pwl(variable, table.voltage_V, table.dark_delivered_A_um2)
    photo = pwl(variable, table.voltage_V, table.photocurrent_A_um2)
    return f"{area:.17g}*({dark}+({light})*{photo})"


def source_preflight(table):
    """Every knot and midpoint, three irradiances and both series counts."""
    voltage = np.sort(np.r_[table.voltage_V, (table.voltage_V[:-1] + table.voltage_V[1:]) / 2])
    expected = {}
    lines = ["* Native DC verification of bounded DD PWL terminal sources", "Vcell cell 0 0"]
    vectors = []
    for n in (2, 4):
        lines.append(f"Espan{n} span{n} 0 cell 0 {n}")
        for fraction in (0, 0.5, 1):
            name = f"n{n}f{int(fraction * 10)}"
            expr = current_expression(table, f"v(span{n})/{n}", str(fraction))
            lines += [f"B{name} 0 sink{name} I={{{expr}}}", f"V{name} sink{name} 0 0"]
            vectors.append(f"i(V{name})")
            expected[vectors[-1]] = np.array(
                [table.current(v, 1000 * fraction, AREA) for v in voltage]
            )
    lines += [
        ".control",
        "set wr_vecnames",
        "set wr_singlescale",
        "set numdgt=17",
        "dc Vcell 0 .7 .0125",
        "wrdata source.dat " + " ".join(vectors),
        "quit",
        ".endc",
        ".end",
    ]
    return "\n".join(lines) + "\n", voltage, expected


def build_deck(table, max_step_s=25e-9):
    # Preserve the accepted extracted compact RC/model body byte for byte.
    match = re.search(r"(?ms)^\.subckt microrobot_clock\b.*?^\.ends[^\n]*", CLOCK.read_text())
    if match is None:
        raise ValueError("Missing accepted compact clock")
    circuits = [
        "actuator_driver.spice",
        "electrochemical.spice",
        "brownout_v2.spice",
        "ready_levelshift_current_limited.spice",
        "ready_driver_qualified_lvt.spice",
    ]
    pdk = Path(os.environ.get("PDK_ROOT", "/usr/local/share/pdk")) / "sky130A"
    deck = header() + match.group() + "\n"
    deck += "\n".join((HERE / "circuits" / name).read_text() for name in circuits)
    deck += "\n" + standard_cells(pdk) + phase_netlist(bits=2)
    deck += """
* New design: 4 logic + 2 lower + 2 upper cells, each 1080 um2 = 8640 um2.
* Common CMOS lower rail 0; physical Pt midpoint mid. No empirical PV fit.
Vlight light 0 PWL(0 0 1u 0 101u 1000)
"""
    for name, low, high, count in [
        ("logic", "0", "logic_raw", 4),
        ("lo", "0", "celllo", 2),
        ("hi", "mid", "cellhi", 2),
    ]:
        expr = current_expression(table, f"v({high},{low})/{count}")
        deck += f"Bpv{name} {low} {high} I={{{expr}}}\n"
    deck += """Clogic logic_raw 0 2p
Vlogic logic_raw logic 0
Vpvlo celllo mid 0
Vpvhi cellhi act_raw 0
Vact act_raw act 0
Cstorelo mid 0 1p
Cstorehi act_raw mid 1p
Vclock logic clock_supply 0
Xclock clk clock_supply 0 bn bp microrobot_clock
Coutput clk 0 2f
Vdigital logic digital_supply 0
Xff clk feedback reset_n 0 0 digital_supply digital_supply q0 sky130_fd_sc_hd__dfrtp_1
Xfeedback q0 0 0 digital_supply digital_supply feedback sky130_fd_sc_hd__inv_1
Vresetlogic logic reset_supply 0
Vresetact act reset_act_supply 0
Xready ready reset_n reset_act_supply reset_supply 0 bp microrobot_ready_levelshift
Vmonitor act monitor_supply 0
Xmonitor bn ready monitor_supply 0 microrobot_brownout
Vdriverbuffer act driverbuffer_supply 0
Xdriverbuffer reset_n ready driver_ready driverbuffer_supply 0 microrobot_ready_driver_qualified_lvt
* Measured switched-capacitor digital power proxy, not extracted RTL power.
Vproxy logic proxy_supply 0
Xproxy clk flop_load proxy_supply 0 micro_inv
Xcproxy1 flop_load 0 sky130_fd_pr__cap_mim_m3_1 w=2 l=2
Xcproxy2 flop_load 0 sky130_fd_pr__cap_mim_m3_1 w=2 l=2
* Native first DFF plus TWO functional bits: real-time /8 experiment.
Bclock_norm clock_n 0 V={1-v(q0)/max(v(logic),0.1)}
Breset_norm reset_ok_n 0 V={v(reset_n)/max(v(logic),0.1)}
Xphases clock_n reset_ok_n pan pbn microrobot_event_phases
* Functional CMOS output bridges: conductances move charge from measured rails.
* DAC outputs pan/pbn control conductance only; they deliver no phase energy.
Vphase logic phase_supply 0
Bpahi phase_supply pa I={(v(phase_supply)-v(pa))*min(max(v(pan),0),1)/10000}
Bpalo pa 0 I={v(pa)*(1-min(max(v(pan),0),1))/10000}
Bpbhi phase_supply pb I={(v(phase_supply)-v(pb))*min(max(v(pbn),0),1)/10000}
Bpblo pb 0 I={v(pb)*(1-min(max(v(pbn),0),1))/10000}
Vdriverslogic logic drivers_logic 0
Vdriversact act drivers_act 0
Vdriversmid mid drivers_mid 0
Xda pa driver_ready ea_driver drivers_logic drivers_act drivers_mid 0 microrobot_driver
Xdb pb driver_ready eb_driver drivers_logic drivers_act drivers_mid 0 microrobot_driver
Vea ea_driver ea 0
Veb eb_driver eb 0
Vreturn mid er 0
Xea ea sa ta micro_electrode
Xeb eb sb tb micro_electrode
Xreturn er sr tr micro_electrode cdl=400p qmax=2600p rf=1g
Rsa sa bulk 10meg
Rsb sb bulk 10meg
Rsr sr bulk 1meg
"""
    vectors = [
        "v(" + n + ")"
        for n in [
            "light",
            "logic_raw",
            "logic",
            "act_raw",
            "act",
            "mid",
            "celllo",
            "cellhi",
            "clk",
            "q0",
            "bn",
            "bp",
            "ready",
            "reset_n",
            "driver_ready",
            "pan",
            "pbn",
            "pa",
            "pb",
            "ea_driver",
            "eb_driver",
            "ea",
            "eb",
            "er",
            "sa",
            "sb",
            "sr",
            "bulk",
            "ta",
            "tb",
            "tr",
        ]
    ]
    vectors += [
        "i(" + n + ")"
        for n in [
            "Vlogic",
            "Vact",
            "Vpvlo",
            "Vpvhi",
            "Vclock",
            "Vdigital",
            "Vresetlogic",
            "Vresetact",
            "Vmonitor",
            "Vdriverbuffer",
            "Vproxy",
            "Vphase",
            "Vdriverslogic",
            "Vdriversact",
            "Vdriversmid",
            "Vea",
            "Veb",
            "Vreturn",
        ]
    ]
    deck += f""".options method=gear maxord=2 reltol=1e-6 abstol=1e-15
.control
set wr_vecnames
set wr_singlescale
set numdgt=17
save {" ".join(vectors)}
tran {max_step_s:.17g} {STOP} 0 {max_step_s:.17g}
wrdata controller.dat {" ".join(vectors)}
quit
.endc
.end
"""
    return deck


def execute(directory, deck, *, timeout=900):
    directory.mkdir(parents=True, exist_ok=False)
    (directory / ".spiceinit").write_text("set ngbehavior=hsa\nset num_threads=1\n")
    (directory / "bench.spice").write_text(deck)
    start = time.monotonic()
    result = subprocess.run(
        [shutil.which("ngspice") or "ngspice", "-b", "bench.spice"],
        cwd=directory,
        text=True,
        capture_output=True,
        timeout=timeout,
    )
    log = result.stdout + result.stderr
    (directory / "ngspice.log").write_text(log)
    execution = {
        "returncode": result.returncode,
        "seconds": time.monotonic() - start,
        "completed_UTC": datetime.now(timezone.utc).isoformat(),
        "netlist_sha256": sha(directory / "bench.spice"),
        "aborted": any(
            x in log.lower() for x in ["simulation(s) aborted", "doanalyses:", "timestep too small"]
        ),
    }
    write_json(directory / "execution.json", execution)
    return execution


def read_data(path):
    with path.open() as stream:
        columns = stream.readline().split()
    data = np.loadtxt(path, skiprows=1, ndmin=2)
    return columns, data


def crossings(t, value, rising=True):
    indices = np.flatnonzero(
        (value[:-1] < 0) & (value[1:] >= 0) if rising else (value[:-1] >= 0) & (value[1:] < 0)
    )
    return t[indices] - value[indices] * np.diff(t)[indices] / np.diff(value)[indices]


def mechanics(t, theta):
    """Exact first-order update for piecewise-linear coverage, tau=50 ms."""
    target = 1e5 * (theta - 0.5)
    out = np.zeros(len(t))
    for index, dt in enumerate(np.diff(t), 1):
        if dt == 0:
            out[index] = out[index - 1]
            continue
        decay = np.exp(-dt / 0.05)
        slope = (target[index] - target[index - 1]) / dt
        out[index] = (
            out[index - 1] * decay
            + target[index - 1] * (1 - decay)
            + slope * (dt - 0.05 * (1 - decay))
        )
    return out


def analyze(columns, data, execution, table):
    v = dict(zip(columns, data.T, strict=True))
    t = v["time"]
    complete = False
    reason = None
    try:
        validate_transient(data, len(columns), STOP)
        if t[0] != 0 or execution["aborted"] or execution["returncode"]:
            raise RuntimeError("Bad start, simulator abort or nonzero exit")
        complete = True
    except RuntimeError as error:
        reason = str(error)
    if not np.isfinite(data).all():
        return {"complete": False, "failure": "Nonfinite transient", "all_gates_pass": False}

    def integrate(power):
        return float(np.trapezoid(power, t))

    logic, act, mid = (v["v(" + name + ")"] for name in ["logic", "act", "mid"])
    cell_voltages = np.array(
        [v["v(logic_raw)"] / 4, v["v(celllo)"] / 2, (v["v(cellhi)"] - mid) / 2]
    )
    domain = bool(
        cell_voltages.min() >= -1e-9 and cell_voltages.max() <= table.voltage_V[-1] + 1e-9
    )
    released = (act >= 0.5) & (v["v(driver_ready)"] > 0.5 * act)
    qualified = released & (v["v(reset_n)"] > 0.5 * logic) & (logic >= 1.4) & (logic <= 1.94)
    start = float(t[np.flatnonzero(qualified)[0]]) if qualified.any() else STOP
    clock_r = crossings(t, v["v(clk)"] - 0.5 * logic)
    q_r = crossings(t, v["v(q0)"] - 0.5 * logic)
    q_f = crossings(t, v["v(q0)"] - 0.5 * logic, False)
    clock_r, q_r, q_f = (x[x > start + 20e-6] for x in [clock_r, q_r, q_f])
    q_changes = np.sort(np.r_[q_r, q_f])
    mapped = [int(np.count_nonzero((q_changes >= x) & (q_changes <= x + 20e-6))) for x in clock_r]
    phase_r = [crossings(t, v[f"v({n})"] - 0.5 * logic) for n in ["pa", "pb"]]
    phase_r = [r[r > start + 20e-6] for r in phase_r]
    ar, br = phase_r
    periods = np.diff(ar)
    lags = [
        float((br[(br > left) & (br < right)][0] - left) / (right - left))
        for left, right in zip(ar[:-1], ar[1:])
        if len(br[(br > left) & (br < right)]) == 1
    ]
    # Quadrature state progression should be 10 -> 11 -> 01 -> 00 -> 10.
    states = (v["v(pa)"] > 0.5 * logic).astype(int) * 2 + (v["v(pb)"] > 0.5 * logic)
    stable = qualified & (t > start + 20e-6)
    compact_states = states[stable]
    compact_states = (
        compact_states[np.r_[True, np.diff(compact_states) != 0]] if len(compact_states) else []
    )
    expected_next = {2: 3, 3: 1, 1: 0, 0: 2}
    order_ok = len(compact_states) > 4 and all(
        expected_next[int(a)] == int(b) for a, b in zip(compact_states[:-1], compact_states[1:])
    )
    reset = (logic >= 1) & (act >= 0.5) & (v["v(reset_n)"] <= 0.1 * logic)
    cold = t <= 0.00004  # Same optical ramp is earlier than legacy 0.4 ms window.
    metal_error = np.maximum(abs(v["v(ea)"] - mid), abs(v["v(eb)"] - mid))
    clamp = float(metal_error[reset].max()) if reset.any() else None
    rail_excursion = float(
        max(
            0,
            -v["v(ea)"].min(),
            -v["v(eb)"].min(),
            (v["v(ea)"] - act).max(),
            (v["v(eb)"] - act).max(),
        )
    )
    eta = np.array([v["v(ea)"] - v["v(sa)"], v["v(eb)"] - v["v(sb)"], v["v(er)"] - v["v(sr)"]])
    theta = np.array([v["v(ta)"], v["v(tb)"], v["v(tr)"]])
    cap = np.array([40e-12, 40e-12, 400e-12])[:, None]
    qmax = np.array([260e-12, 260e-12, 2600e-12])[:, None]
    rf = np.array([10e9, 10e9, 1e9])[:, None]
    adsorption = qmax / 0.02 * (1 / (1 + np.exp(-np.clip(eta / 0.08, -700, 700))) - theta)
    currents = np.array([v["i(Vea)"], v["i(Veb)"], v["i(Vreturn)"]])
    solution_i = np.array(
        [
            (v["v(sa)"] - v["v(bulk)"]) / 10e6,
            (v["v(sb)"] - v["v(bulk)"]) / 10e6,
            (v["v(sr)"] - v["v(bulk)"]) / 1e6,
        ]
    )
    pv_powers = np.array(
        [
            v["v(logic_raw)"]
            * AREA
            * np.array(
                [
                    table.current(x, light, 1)
                    for x, light in zip(np.clip(cell_voltages[0], 0, 0.7), v["v(light)"])
                ]
            ),
            mid * v["i(Vpvlo)"],
            (v["v(act_raw)"] - mid) * v["i(Vpvhi)"],
        ]
    )
    load_ports = {
        name: integrate(logic * v["i(" + port + ")"])
        for name, port in [
            ("clock", "Vclock"),
            ("first_DFF_feedback", "Vdigital"),
            ("digital_proxy", "Vproxy"),
            ("reset_logic", "Vresetlogic"),
            ("phase_bridge", "Vphase"),
            ("drivers_logic", "Vdriverslogic"),
            ("supervisor_reset_bridge", "Vsupervisor_reset"),
        ]
        if "i(" + port + ")" in v
    }
    load_ports.update(
        {
            name: integrate(act * v["i(" + port + ")"])
            for name, port in [
                ("reset_actuator", "Vresetact"),
                ("monitor", "Vmonitor"),
                ("qualified_LVT", "Vdriverbuffer"),
                ("drivers_upper", "Vdriversact"),
                ("supervisor_driver_bridge", "Vsupervisor_driver"),
            ]
            if "i(" + port + ")" in v
        }
    )
    load_ports["drivers_mid"] = integrate(mid * v["i(Vdriversmid)"])
    load_ports["Pt_return_port"] = integrate(mid * v["i(Vreturn)"])
    storage = 0.5 * 2e-12 * v["v(logic_raw)"] ** 2 + 0.5e-12 * (
        mid**2 + (v["v(act_raw)"] - mid) ** 2
    )
    storage_delta = float(storage[-1] - storage[0])
    pv_energy = integrate(pv_powers.sum(axis=0))
    supply_residual = pv_energy - storage_delta - sum(load_ports.values())
    cdl_delta = float((0.5 * cap * (eta**2 - eta[:, 0, None] ** 2))[:, -1].sum())
    ads_work = integrate(np.sum(eta * adsorption, axis=0))
    faradaic = integrate(np.sum(eta**2 / rf, axis=0))
    electrolyte = integrate(np.sum(solution_i**2 * np.array([10e6, 10e6, 1e6])[:, None], axis=0))
    electrode_work = integrate(
        np.sum(np.array([v["v(ea)"], v["v(eb)"], v["v(er)"]]) * currents, axis=0)
    )
    bridge_loss = integrate(
        (
            (logic - v["v(pa)"]) ** 2 * np.clip(v["v(pan)"], 0, 1)
            + v["v(pa)"] ** 2 * (1 - np.clip(v["v(pan)"], 0, 1))
            + (logic - v["v(pb)"]) ** 2 * np.clip(v["v(pbn)"], 0, 1)
            + v["v(pb)"] ** 2 * (1 - np.clip(v["v(pbn)"], 0, 1))
        )
        / 10000
    )
    curvature = np.array([mechanics(t, x) for x in theta[:2]])
    theta_swing = [float(np.ptp(x[stable])) if stable.any() else 0 for x in theta[:2]]
    curvature_swing = [float(np.ptp(x[stable])) if stable.any() else 0 for x in curvature]
    corr = [
        float(np.corrcoef(eta[i, stable], np.gradient(theta[i], t)[stable])[0, 1])
        if stable.sum() > 3 and theta_swing[i] > 0
        else None
        for i in range(2)
    ]
    gates = {
        "complete_finite": complete,
        "DD_domain": domain,
        "released_logic_1p4_to_1p94_V": bool(
            not np.any(released & ((logic < 1.4) | (logic > 1.94)))
        ),
        "native_DFF_maps_clock": len(mapped) >= 6 and all(x == 1 for x in mapped),
        "three_complete_phase_cycles": len(periods) >= 3,
        "quadrature_order": bool(
            order_ok and len(lags) >= 3 and max(abs(np.array(lags) - 0.25)) < 0.08
        ),
        "both_electrode_polarities": bool(
            stable.any()
            and all(
                (v[f"v({n})"] - mid)[stable].min() < -0.05
                and (v[f"v({n})"] - mid)[stable].max() > 0.05
                for n in ["ea", "eb"]
            )
        ),
        "coverage_bounded": bool(theta.min() >= -1e-6 and theta.max() <= 1 + 1e-6),
        "phase_correlated_coverage_curvature": all(x > 1e-5 for x in theta_swing)
        and all(x > 0.01 for x in curvature_swing)
        and all(x is not None and x > 0 for x in corr),
        "reset_midpoint_clamp_50mV": clamp is not None and clamp < 0.05,
        "electrode_rail_excursion_100mV": rail_excursion < 0.1,
        "supply_energy_balance_2percent": abs(supply_residual) < max(abs(pv_energy) * 0.02, 1e-15),
        "electrode_energy_balance_2percent": abs(
            electrode_work - cdl_delta - ads_work - faradaic - electrolyte
        )
        < max(abs(electrode_work) * 0.02, 1e-15),
        "solution_KCL_1pA": float(abs(solution_i.sum(axis=0)).max()) < 1e-12,
    }
    result = {
        "complete": complete,
        "failure": reason,
        "requested_stop_s": STOP,
        "actual_stop_s": float(t[-1]),
        "rows": len(t),
        "gates": gates,
        "all_gates_pass": all(gates.values()),
        "cell_domain_min_max_V": [float(cell_voltages.min()), float(cell_voltages.max())],
        "logic_min_max_V": [float(logic.min()), float(logic.max())],
        "released_logic_min_max_V": [float(logic[released].min()), float(logic[released].max())]
        if released.any()
        else None,
        "qualified_start_s": start,
        "native_clock_rises": clock_r.tolist(),
        "native_Q_rises": q_r.tolist(),
        "native_Q_falls": q_f.tolist(),
        "Q_changes_per_clock_rise": mapped,
        "phase_A_rises_s": ar.tolist(),
        "phase_B_rises_s": br.tolist(),
        "phase_B_lag_cycles": lags,
        "phase_states": list(map(int, compact_states)),
        "reset_clamp_peak_V": clamp,
        "cold_0_to_40us_metal_error_V": float(metal_error[cold].max()),
        "rail_excursion_V": rail_excursion,
        "theta_min_max": [float(theta.min()), float(theta.max())],
        "coverage_swing": theta_swing,
        "curvature_swing_m_inv": curvature_swing,
        "eta_vs_coverage_derivative_correlation": corr,
        "energy_J": {
            "PV_delivered": pv_energy,
            "storage_delta": storage_delta,
            "measured_load_ports": load_ports,
            "supply_balance_residual": supply_residual,
            "electrode_metal_port_work": electrode_work,
            "double_layer_delta": cdl_delta,
            "signed_adsorption_work": ads_work,
            "Faradaic_loss": faradaic,
            "solution_resistive_loss": electrolyte,
            "phase_bridge_resistive_loss": bridge_loss,
            "electrode_balance_residual": electrode_work
            - cdl_delta
            - ads_work
            - faradaic
            - electrolyte,
        },
        "electrode_terminal_vs_solution_current_max_A": float(abs(currents - solution_i).max()),
        "solution_KCL_max_A": float(abs(solution_i.sum(axis=0)).max()),
    }
    return result


def plot_case(columns, data, path):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    v = dict(zip(columns, data.T, strict=True))
    t = v["time"]
    # Plot decimation only; every metric above uses every native saved sample.
    ix = np.unique(np.r_[np.arange(0, len(t), max(1, len(t) // 18000)), len(t) - 1])
    fig, axes = plt.subplots(5, 1, figsize=(11, 12), sharex=True)
    for n in ["logic", "act", "mid", "reset_n", "driver_ready"]:
        axes[0].plot(t[ix] * 1e3, v["v(" + n + ")"][ix], label=n)
    for n in ["clk", "q0", "pa", "pb"]:
        axes[1].plot(t[ix] * 1e3, v["v(" + n + ")"][ix], label=n, alpha=0.8)
    for n in ["ea", "eb"]:
        axes[2].plot(t[ix] * 1e3, (v[f"v({n})"] - v["v(mid)"])[ix], label=n + " minus Pt")
    for n in ["ta", "tb", "tr"]:
        axes[3].plot(t[ix] * 1e3, v["v(" + n + ")"][ix], label=n)
    for n in ["ta", "tb"]:
        axes[4].plot(t[ix] * 1e3, mechanics(t, v["v(" + n + ")"])[ix], label=n + " curvature")
    for ax, label in zip(
        axes,
        [
            "Rail / reset (V)",
            "Native / phase (V)",
            "Metal vs Pt (V)",
            "Coverage",
            "Assumed curvature (m⁻¹)",
        ],
    ):
        ax.set_ylabel(label)
        ax.grid(alpha=0.2)
        ax.legend(loc="best", ncol=3)
    axes[-1].set_xlabel("Native simulation time (ms)")
    fig.suptitle("TCAD-table functional /8 experiment — short-window mechanics, no walking claim")
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def run(*, evidence=EVIDENCE, local=LOCAL, resume_preflight=False):
    evidence, local = Path(evidence), Path(local)
    if resume_preflight:
        prior = json.loads((evidence / "source_validation.json").read_text())
        if (
            prior["passed"]
            or (evidence / "execution_counts.json").exists()
            or (local / "nominal_25ns").exists()
        ):
            raise RuntimeError("Preflight-only resume requires a failed DC check and no transient")
        (local / "source_dc").rename(local / "source_dc_initial_precision8")
        for name in ["source_dc.spice", "source_dc.log", "source_validation.json"]:
            (evidence / name).rename(evidence / ("initial_precision8_" + name))
    elif evidence.exists() or local.exists():
        raise FileExistsError("Both evidence and local run destinations must be fresh")
    evidence.mkdir(parents=True, exist_ok=resume_preflight)
    local.mkdir(parents=True, exist_ok=resume_preflight)
    table = load_table()
    provenance = {
        "light_curve": "baseline_R0p3",
        "light_sha256": sha(LIGHT),
        "dark_sha256": sha(DARK),
        "dark_condition": "Archived dark reused conditional on identical mesh, nodes, lifetime and grid; historical full source hash unavailable; no fresh dark DD",
        "light_condition": "Fresh prior-task DD R=.3 reproduction; not rerun here",
        "superposition": "Linear irradiance scaling of light-minus-dark; no new irradiance DD solution",
        "area_each_um2": AREA,
        "logic_series": 4,
        "each_actuator_half_series": 2,
        "total_area_um2": 8640,
        "logic_storage_F": 2e-12,
        "each_half_storage_F": 1e-12,
        "mechanical_tau_s": 0.05,
        "curvature_span_m_inv": 1e5,
        "hinge_length_um": 10,
        "logic_limits_V": [1.4, 1.94],
        "logic_limits_scope": "Engineering bench limits, not foundry specifications",
        "table_voltage_domain_V": [float(table.voltage_V[0]), float(table.voltage_V[-1])],
        "PV_logic_Voc_V": 4
        * float(
            np.interp(0, -(table.dark_delivered_A_um2 + table.photocurrent_A_um2), table.voltage_V)
        ),
        "PV_logic_power_at_1p7_W": 1.7 * table.current(1.7 / 4, 1000, AREA),
        "clock_source_sha256": sha(CLOCK),
        "DD_sweeps_this_task": 0,
        "layout_runs_this_task": 0,
        "phase_divider": 8,
        "phase_divider_scope": "Changed real-time functional test; final /8192 untested",
        "ideal_controls_scope": "Normalized native clock/reset plus XSPICE signal-only event DAC; phase analog power comes only from measured logic rail",
    }
    write_json(evidence / "configuration.json", provenance)
    preflight, voltage, expected = source_preflight(table)
    execution = execute(local / "source_dc", preflight)
    shutil.copy2(local / "source_dc/bench.spice", evidence / "source_dc.spice")
    shutil.copy2(local / "source_dc/ngspice.log", evidence / "source_dc.log")
    columns, data = read_data(local / "source_dc/source.dat")
    error = {
        name: float(np.max(abs(data[:, i + 1] - expected[name]))) for i, name in enumerate(expected)
    }
    checks = {
        "execution": execution,
        "rows": len(data),
        "knot_and_midpoint_count": len(voltage),
        "voltage_grid_max_error_V": float(np.max(abs(data[:, 0] - voltage))),
        "max_absolute_current_error_A": error,
        "passed": not execution["aborted"]
        and not execution["returncode"]
        and len(data) == len(voltage)
        and max(error.values()) < 1e-12,
    }
    write_json(evidence / "source_validation.json", checks)
    if not checks["passed"]:
        raise RuntimeError("Native DD PWL source validation failed; no transient authorized")
    counts = {
        "source_native_DC_runs": 2 if resume_preflight else 1,
        "nominal_transients": 0,
        "fine_transients": 0,
        "rescue_runs": 0,
    }
    write_json(evidence / "execution_counts.json", counts)
    metrics = {}
    for name, step in [("nominal_25ns", 25e-9), ("fine_12p5ns", 12.5e-9)]:
        if name.startswith("fine") and not metrics["nominal_25ns"]["all_gates_pass"]:
            break
        counts["nominal_transients" if name.startswith("nominal") else "fine_transients"] += 1
        write_json(evidence / "execution_counts.json", counts)
        deck = build_deck(table, step)
        execution = execute(local / name, deck)
        for source, target in [
            ("bench.spice", name + ".spice"),
            ("ngspice.log", name + ".log"),
            ("execution.json", name + "_execution.json"),
        ]:
            shutil.copy2(local / name / source, evidence / target)
        path = local / name / "controller.dat"
        if path.exists():
            columns, data = read_data(path)
            result = analyze(columns, data, execution, table)
            result["raw_sha256"] = sha(path)
            result["raw_local_path"] = str(path)
            plot_case(columns, data, evidence / (name + ".png"))
        else:
            result = {
                "complete": False,
                "all_gates_pass": False,
                "failure": "No transient output",
                "execution": execution,
            }
        metrics[name] = result
        write_json(evidence / "metrics.json", metrics)
    status = (
        "Functional gates passed in both nominal and fine runs"
        if len(metrics) == 2 and all(x["all_gates_pass"] for x in metrics.values())
        else "BLOCKED: nominal functional/completion gate failed; no rescue or fine run"
    )
    write_json(
        evidence / "status.json", {"status": status, "acceptance": "Pending Astra evidence review"}
    )
    (evidence / "README.md").write_text(f"""# TCAD-powered controller functional experiment

{status}.

The run connects the fresh R=0.3, 29-point drift-diffusion table to the native extracted compact clock, first resettable DFF, existing current-limited reset converter, brownout candidate, qualified LVT receiver and two transistor drivers. Two XSPICE bits make a changed **/8 real-time functional test**. The final /8192 divider and extracted RTL power remain untested. The remaining digital power uses a measured switched PDK-capacitor proxy. Functional phase bridges transfer charge from the measured logic rail through 10 kΩ conductances; signal-only event controls provide no analog output energy.

This is a new **8640 µm²** conceptual PV design: four logic cells and two series cells per actuator half, each 1080 µm². Common lower rail is physical CMOS ground and the physical midpoint connects the Pt return. Storage is 2 pF logic and 1 pF per half. Dark/light superposition is conditional as recorded in configuration.json; no empirical PV fit is used. SPICE PWL endpoint behavior is never accepted outside the characterized per-cell domain: the full saved transient must pass the bounded-domain gate. Native DC verifies every knot and midpoint at zero, half and full reference illumination for both series counts before any transient.

Electrodes retain 40 pF double layer, 260 pC adsorption scale, 20 ms kinetics and 10 GΩ Faradaic resistance; Pt return uses 400 pF, 2600 pC and 1 GΩ. Solution resistances are 10/10/1 MΩ. Electrical metrics separately retain double-layer energy change, signed adsorption work and resistive losses. Current KCL and source/storage/load balance use all adaptive samples. Logic limits 1.4–1.94 V, 50 mV reset clamp and 100 mV rail excursion are engineering bench limits, not foundry or electrochemical safety specifications.

Coverage drives an assumed 50 ms relaxation and 10⁵ m⁻¹ curvature span, with no force, contact or walking model. Eight milliseconds is a short-window response, not mechanical steady state or a calibrated actuator reproduction. Raw waveforms remain local; plots are decimated only for display. Exit status alone is not acceptance.

Reproduce from repository root with fresh destinations:

```text
MPLCONFIGDIR=/tmp/opentcad-mpl .venv/bin/python -m examples.microrobot.tcad_controller
```

The runner allows exactly one nominal 8 ms / 25 ns transient and only permits one 12.5 ns repeat if completion and every nominal gate pass. Failed nominal execution stops this branch; no automatic rescue. See execution_counts.json, metrics.json, exact decks/logs, source_validation.json, configuration.json and sha256.json. No DD/layout rerun, publication, submission, push or fabrication was performed.
""")
    write_json(
        evidence / "sha256.json",
        {
            p.name: sha(p)
            for p in sorted(evidence.iterdir())
            if p.is_file() and p.name != "sha256.json"
        },
    )
    return metrics


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", type=Path, default=EVIDENCE)
    parser.add_argument("--local", type=Path, default=LOCAL)
    parser.add_argument(
        "--resume-preflight",
        action="store_true",
        help="Only resume a failed native DC check before any transient",
    )
    args = parser.parse_args()
    result = run(evidence=args.evidence, local=args.local, resume_preflight=args.resume_preflight)
    print(
        json.dumps(
            {
                name: {
                    k: r.get(k) for k in ["complete", "actual_stop_s", "all_gates_pass", "failure"]
                }
                for name, r in result.items()
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
