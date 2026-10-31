"""Two initial independent deletion-only feedback runs; no automatic rescue."""

import json
import difflib
from pathlib import Path
import re
import shutil

import numpy as np

from . import tcad_controller as tc
from . import tcad_actuator_feedback_replay as dual
from . import tcad_electrode_replay as replay

EVIDENCE = tc.HERE / "results/tcad_feedback_fix"
LOCAL = tc.HERE / "local_runs/tcad_feedback_fix"
SOURCE = dual.EVIDENCE / "feedback_template.spice"


def build_deck(tag):
    if tag not in ["rc", "stable"]:
        raise ValueError("Unknown model")
    other = "stable" if tag == "rc" else "rc"
    lines = []
    depth = 0
    for line in SOURCE.read_text().splitlines(True):
        if line.startswith(".subckt "):
            depth += 1
        if line.startswith(".ends"):
            depth -= 1
            lines.append(line)
            continue
        token = line.split()[0] if line.split() else ""
        if depth == 0 and (token.endswith("_" + other) or token.startswith("Vp_" + other + "_")):
            continue
        if line.startswith("save ") or line.startswith("wrdata feedback.dat "):
            line = (
                " ".join(
                    part
                    for part in line.split()
                    if other + "_" not in part and "_" + other + ")" not in part
                )
                + "\n"
            )
        lines.append(line)
    return "".join(lines)


def analyze(tag, columns, data, execution):
    complete = True
    failure = None
    try:
        tc.validate_transient(data, len(columns), 250e-6)
        if (
            data[0, 0] != 0
            or abs(data[-1, 0] - 250e-6) > 1e-12
            or execution["returncode"]
            or execution["aborted"]
        ):
            raise RuntimeError("Start/stop mismatch or native abort")
    except RuntimeError as error:
        complete = False
        failure = str(error)
    v = dict(zip(columns, data.T, strict=True))
    n = replay.network(v, tag)
    t = v["time"]

    def node(name):
        return v[f"v({tag}_{name})"]

    cells = np.array([node("celllo") / 2, (node("cellhi") - node("mid")) / 2])
    powered = (node("logic") >= 1) & (node("act") >= 0.5)
    clamp = np.maximum(abs(node("a") - node("mid")), abs(node("b") - node("mid")))
    return {
        "complete": complete,
        "failure": failure,
        "actual_stop_s": float(t[-1]),
        "shape": list(data.shape),
        "finite": bool(np.isfinite(data).all()),
        "node_bounds": {
            name: [float(node(name).min()), float(node(name).max()), float(node(name)[-1])]
            for name in ["logic", "act", "mid", "driver_ready", "pa", "pb"]
        },
        "DD_cell_bounds_V": [float(cells.min()), float(cells.max())],
        "DD_domain_pass": bool(cells.min() >= -1e-9 and cells.max() <= 0.7 + 1e-9),
        "powered_clamp_peak_V": float(clamp[powered].max()) if powered.any() else None,
        "coverage_bounds": [float(n["coverage"].min()), float(n["coverage"].max())],
        "terminal_KCL_peak_A": float(abs(n["current"].sum(axis=0)).max()),
        "solution_KCL_peak_A": float(abs(n["solution_current"].sum(axis=0)).max()),
        "terminal_solution_current_discrepancy_A": float(
            abs(n["current"] - n["solution_current"]).max()
        ),
        "scope": "Independent reduced held-input feedback only; incomplete traces are prefix evidence, no full-controller or released-operation acceptance",
    }


def run():
    if EVIDENCE.exists() or LOCAL.exists():
        raise FileExistsError("Fix-workflow destinations must be fresh")
    EVIDENCE.mkdir(parents=True)
    LOCAL.mkdir(parents=True)
    shutil.copy2(dual.LOCAL / "logic_history.spice", LOCAL / "logic_history.spice")
    shutil.copy2(Path(__file__), EVIDENCE / "runner_as_executed.py")
    tc.write_json(
        EVIDENCE / "configuration.json",
        {
            "source_deck_sha256": tc.sha(SOURCE),
            "logic_history_sha256": tc.sha(LOCAL / "logic_history.spice"),
            "transform": "Delete the other active copy and its saved vectors only; names, definitions, options, OP and replay unchanged",
            "initial_runs": ["rc", "stable"],
            "stop_s": 250e-6,
            "max_step_s": 25e-9,
            "limits": replay.LIMITS,
        },
    )
    metrics = {}
    counts = {
        "initial_transients_started": 0,
        "fix_or_rescue_transients": 0,
        "fine": 0,
        "DD": 0,
        "layout": 0,
    }
    for tag in ["rc", "stable"]:
        counts["initial_transients_started"] += 1
        tc.write_json(EVIDENCE / "execution_counts.json", counts)
        execution = tc.execute(LOCAL / tag, build_deck(tag), timeout=600)
        for source, target in [
            ("bench.spice", tag + ".spice"),
            ("ngspice.log", tag + ".log"),
            ("execution.json", tag + "_execution.json"),
        ]:
            shutil.copy2(LOCAL / tag / source, EVIDENCE / target)
        columns, data = tc.read_data(LOCAL / tag / "feedback.dat")
        result = analyze(tag, columns, data, execution)
        result["raw_sha256"] = tc.sha(LOCAL / tag / "feedback.dat")
        result["raw_local_path"] = str(LOCAL / tag / "feedback.dat")
        log = (LOCAL / tag / "ngspice.log").read_text()
        found = re.search(r'trouble with node "([^"]+)"', log)
        result["reported_trouble_equation"] = found[1] if found else None
        metrics[tag] = result
        tc.write_json(EVIDENCE / "metrics.json", metrics)
        print(json.dumps({"model": tag, **result}), flush=True)
    tc.write_json(
        EVIDENCE / "sha256.json",
        {
            p.name: tc.sha(p)
            for p in sorted(EVIDENCE.iterdir())
            if p.is_file() and p.name != "sha256.json"
        },
    )
    return metrics


def accuracy(tag, columns, data, result):
    v = dict(zip(columns, data.T, strict=True))
    t = v["time"]
    n = replay.network(v, tag)
    bc, bd = tc.read_data(replay.BENCHMARK)
    b = dict(zip(bc, bd.T, strict=True))
    bm = np.array([b[f"v({x})"] for x in ["ea", "eb", "er"]])
    bs = np.array([b[f"v({x})"] for x in ["sa", "sb", "sr"]])
    bx = np.array([b[f"v({x})"] for x in ["ta", "tb", "tr"]])
    bi = np.array([b[f"i({x})"] for x in ["Vea", "Veb", "Vreturn"]])
    reference = {"eta": bm - bs, "coverage": 0.5 + (bx - bs) / 0.32, "current": bi}
    ref = {
        key: np.array([np.interp(t, b["time"], row) for row in value])
        for key, value in reference.items()
    }
    comparisons = replay.compare(n, ref, "benchmark")
    allowance = 5e-12 + 0.02 * np.max(abs(bi), axis=1)
    local = np.max(abs(n["current"] - n["solution_current"]), axis=1)
    cap, qmax, rf = replay.PARAMS
    cads = qmax / 0.32
    charge = (
        np.trapezoid(n["current"] - n["eta"] / rf[:, None], t, axis=1)
        - cap * (n["eta"][:, -1] - n["eta"][:, 0])
        - cads * (n["u"][:, -1] - n["u"][:, 0])
    )
    charge_limit = 1e-20 + 0.02 * (cap * np.ptp(bm - bs, axis=1) + cads * np.ptp(bx - bs, axis=1))
    z = n["eta"] / 0.16
    ia = (
        cads[:, None]
        / 0.02
        * (
            (n["eta"] - n["u"])
            if tag == "rc"
            else n["metal"]
            - n["state"]
            + 0.16 * np.array([[dual.stable.correction(float(x)) for x in row] for row in z])
        )
    )
    def integ(power):
        return float(np.trapezoid(power, t))
    work = integ(np.sum(n["metal"] * n["current"], axis=0))
    ads = integ(np.sum(n["eta"] * ia, axis=0))
    cdl = float(np.sum(0.5 * cap * (n["eta"][:, -1] ** 2 - n["eta"][:, 0] ** 2)))
    loss = integ(
        np.sum(n["solution_current"] ** 2 * np.array([10e6, 10e6, 1e6])[:, None], axis=0)
    ) + integ(np.sum(n["eta"] ** 2 / rf[:, None], axis=0))
    eres = work - cdl - ads - loss
    def node(name):
        return v[f"v({tag}_{name})"]
    def current(name):
        return v[f"i({name}_{tag})"]
    pv = integ(node("mid") * current("Vpvlo") + (node("act") - node("mid")) * current("Vpvhi"))
    storage = 0.5e-12 * (node("mid") ** 2 + (node("act_raw") - node("mid")) ** 2)
    supply = (
        pv
        - float(storage[-1] - storage[0])
        - integ(
            node("act") * current("Vdriversact")
            + node("mid") * current("Vdriversmid")
            + node("mid") * v[f"i(Vp_{tag}_r)"]
        )
    )
    drivers_held = not bool(
        np.any((node("act") >= 0.5) & (node("driver_ready") > 0.5 * node("act")))
    )
    gates = {
        "complete": result["complete"],
        "DD_domain": result["DD_domain_pass"],
        "drivers_held": drivers_held,
        "powered_clamp_50mV": result["powered_clamp_peak_V"] is not None
        and result["powered_clamp_peak_V"] < 0.05,
        "benchmark_comparisons": all(value["pass"] for value in comparisons.values()),
        "local_current_conservation": bool(np.all(local <= allowance)),
        "terminal_sum_KCL": result["terminal_KCL_peak_A"] <= float(allowance.sum()),
        "integrated_charge_KCL": bool(np.all(abs(charge) <= charge_limit)),
        "actuator_supply_energy_2percent": abs(supply) < max(0.02 * abs(pv), 1e-15),
        "electrode_energy_2percent": abs(eres) < max(0.02 * abs(work), 1e-15),
    }
    return {
        "gates": gates,
        "all_gates_pass": all(gates.values()),
        "benchmark_comparisons": comparisons,
        "local_current_discrepancy_A": local.tolist(),
        "local_current_allowance_A": allowance.tolist(),
        "terminal_KCL_allowance_A": float(allowance.sum()),
        "integrated_charge_residual_C": charge.tolist(),
        "charge_allowance_C": charge_limit.tolist(),
        "PV_delivered_J": pv,
        "actuator_supply_residual_J": supply,
        "electrode_signed_work_J": work,
        "electrode_energy_residual_J": eres,
    }


def charge_control():
    metrics = json.loads((EVIDENCE / "metrics.json").read_text())
    counts = json.loads((EVIDENCE / "execution_counts.json").read_text())
    old = ".options method=gear maxord=2 reltol=1e-6 abstol=1e-15"
    new = old + " chgtol=1e-20"
    tc.write_json(
        EVIDENCE / "charge_control_plan.json",
        {
            "single_change": {"from": old, "to": new},
            "execution_order": "stable first; matching RC only if stable completes and every unchanged accuracy/domain/clamp gate passes",
            "current_limits": "5pA+2% frozen benchmark branch peak; terminal sum allowance is sum of three branch allowances",
            "charge_limit": "1e-20C+2% frozen benchmark Cdl/Cads charge excursion",
            "energy_limit": "Existing2% with1e-15J absolute floor; current gates decide precision separately",
            "rationale": "Recorded charge scales and1pA*25ns=2.5e-20C; CHGTOL is not a direct saved-current bound",
        },
    )
    shutil.copy2(Path(__file__), EVIDENCE / "charge_control_runner_as_executed.py")
    for tag in ["stable", "rc"]:
        if tag == "rc" and not metrics["stable_chgtol20"]["accuracy"]["all_gates_pass"]:
            break
        name = tag + "_chgtol20"
        source = (EVIDENCE / (tag + ".spice")).read_text()
        if source.count(old) != 1 or new in source:
            raise RuntimeError("Unexpected original options")
        deck = source.replace(old, new)
        if deck.replace(new, old) != source:
            raise RuntimeError("Non-CHGTOL deck difference")
        counts["targeted_CHGTOL_controls_started"] = (
            counts.get("targeted_CHGTOL_controls_started", 0) + 1
        )
        tc.write_json(EVIDENCE / "execution_counts.json", counts)
        (EVIDENCE / (name + ".diff")).write_text(
            "".join(difflib.unified_diff(source.splitlines(True), deck.splitlines(True)))
        )
        execution = tc.execute(LOCAL / name, deck, timeout=600)
        for original, target in [
            ("bench.spice", name + ".spice"),
            ("ngspice.log", name + ".log"),
            ("execution.json", name + "_execution.json"),
        ]:
            shutil.copy2(LOCAL / name / original, EVIDENCE / target)
        columns, data = tc.read_data(LOCAL / name / "feedback.dat")
        result = analyze(tag, columns, data, execution)
        result["accuracy"] = accuracy(tag, columns, data, result)
        result["raw_sha256"] = tc.sha(LOCAL / name / "feedback.dat")
        result["raw_local_path"] = str(LOCAL / name / "feedback.dat")
        found = re.search(
            r'trouble with node "([^"]+)"', (LOCAL / name / "ngspice.log").read_text()
        )
        result["reported_trouble_equation"] = found[1] if found else None
        metrics[name] = result
        tc.write_json(EVIDENCE / "metrics.json", metrics)
        print(json.dumps({"model": name, **result}), flush=True)
        if not result["accuracy"]["all_gates_pass"]:
            break
    return metrics


if __name__ == "__main__":
    import sys

    if "--charge-control" in sys.argv:
        charge_control()
    else:
        run()
