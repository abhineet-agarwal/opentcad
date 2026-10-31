"""Two initial independent deletion-only feedback runs; no automatic rescue."""

import json
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


if __name__ == "__main__":
    run()
