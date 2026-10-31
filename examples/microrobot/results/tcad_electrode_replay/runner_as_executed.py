"""One isolated two-model electrode replay of frozen adaptive metal histories."""

import json
from pathlib import Path
import re
import shutil

import numpy as np

from . import tcad_controller as tc
from . import tcad_passive_adsorption as rc
from . import tcad_stable_adsorption as stable

EVIDENCE = tc.HERE / "results/tcad_electrode_replay"
LOCAL = tc.HERE / "local_runs/tcad_electrode_replay"
BENCHMARK = rc.LOCAL / "controller.dat"
STOP = 250e-6
PARAMS = (
    np.array([40e-12, 40e-12, 400e-12]),
    np.array([260e-12, 260e-12, 2600e-12]),
    np.array([10e9, 10e9, 1e9]),
)
LIMITS = {
    "benchmark_eta_abs_V": 1e-6,
    "benchmark_coverage_abs": 1e-8,
    "benchmark_current_abs_A": 5e-12,
    "benchmark_relative_peak": 0.02,
    "model_eta_abs_V": 1e-7,
    "model_coverage_abs": 1e-9,
    "model_current_abs_A": 1e-12,
    "model_relative_peak": 0.001,
}


def prepare_history(time, voltage):
    if not np.isfinite(time).all() or not np.isfinite(voltage).all() or np.any(np.diff(time) < 0):
        raise ValueError("Invalid or decreasing replay time/voltage")
    keep = np.r_[True, np.diff(time) > 0]
    for index in np.flatnonzero(~keep):
        if not np.array_equal(voltage[:, index], voltage[:, index - 1]):
            raise ValueError("Different voltages at duplicate time; refusing to erase an event")
    return time[keep], voltage[:, keep], int(np.count_nonzero(~keep))


def stimulus(time, voltage):
    lines = [
        "* Full adaptive metal history; local-only waveform-bearing include",
        ".subckt metal_history a b r",
    ]
    for node, row in zip(["a", "b", "r"], voltage, strict=True):
        lines.append(f"V{node} {node} 0 PWL(")
        lines += [
            f"+ {instant:.17g} {value:.17g}" for instant, value in zip(time, row, strict=True)
        ]
        lines.append("+ )")
    return "\n".join(lines + [".ends metal_history"]) + "\n"


def build_deck():
    pattern = r"(?ms)^\.subckt micro_electrode\b.*?^\.ends micro_electrode[^\n]*"
    sources = {
        "rc": rc.EVIDENCE / "passive_adsorption.spice",
        "stable": stable.EVIDENCE / "stable_adsorption.spice",
    }
    lines = [
        "* Isolated full electrode/solution networks with externally powered replay",
        ".temp 26.85",
        stable.FUNCTION,
        '.include "metal_history.spice"',
    ]
    vectors = []
    for tag, path in sources.items():
        block = (
            re.search(pattern, path.read_text())
            .group()
            .replace("micro_electrode", "electrode_" + tag)
        )
        lines.append(block)
        lines.append(f"Xstim_{tag} {tag}_srca {tag}_srcb {tag}_srcr metal_history")
        for node in ["a", "b", "r"]:
            lines += [
                f"Vp_{tag}_{node} {tag}_src{node} {tag}_{node} 0",
                f"Xe_{tag}_{node} {tag}_{node} {tag}_s{node} {tag}_x{node} electrode_{tag}"
                + (" cdl=400p qmax=2600p rf=1g" if node == "r" else ""),
                f"Rs_{tag}_{node} {tag}_s{node} {tag}_bulk " + ("1meg" if node == "r" else "10meg"),
            ]
        vectors += [
            f"v({tag}_{node})"
            for node in ["a", "b", "r", "sa", "sb", "sr", "xa", "xb", "xr", "bulk"]
        ]
        vectors += [f"i(Vp_{tag}_{node})" for node in ["a", "b", "r"]]
    lines += [
        ".options method=gear maxord=2 reltol=1e-6 abstol=1e-15",
        ".control",
        "set wr_vecnames",
        "set wr_singlescale",
        "set numdgt=17",
        "save " + " ".join(vectors),
        "tran 25n .00025 0 25n",
        "wrdata replay.dat " + " ".join(vectors),
        "quit",
        ".endc",
        ".end",
    ]
    return "\n".join(lines) + "\n"


def compare(first, second, kind):
    differences = {}
    for key, floor in [
        ("eta", LIMITS[kind + "_eta_abs_V"]),
        ("coverage", LIMITS[kind + "_coverage_abs"]),
        ("current", LIMITS[kind + "_current_abs_A"]),
    ]:
        scale = np.max(abs(second[key] - (0.5 if key == "coverage" else 0)), axis=1)
        error = np.max(abs(first[key] - second[key]), axis=1)
        allowance = floor + LIMITS[kind + "_relative_peak"] * scale
        differences[key] = {
            "maximum_absolute_error": error.tolist(),
            "allowed": allowance.tolist(),
            "pass": bool(np.all(error <= allowance)),
        }
    return differences


def network(v, tag):
    metal = np.array([v[f"v({tag}_{n})"] for n in ["a", "b", "r"]])
    solution = np.array([v[f"v({tag}_s{n})"] for n in ["a", "b", "r"]])
    state = np.array([v[f"v({tag}_x{n})"] for n in ["a", "b", "r"]])
    return {
        "metal": metal,
        "state": state,
        "eta": metal - solution,
        "coverage": 0.5 + (state - solution) / (0.32),
        "u": state - solution,
        "current": np.array([v[f"i(Vp_{tag}_{n})"] for n in ["a", "b", "r"]]),
        "solution_current": (solution - v[f"v({tag}_bulk)"]) / np.array([10e6, 10e6, 1e6])[:, None],
    }


def analyze(columns, data, execution, benchmark_columns, benchmark):
    complete = True
    failure = None
    try:
        tc.validate_transient(data, len(columns), STOP)
        if (
            data[0, 0] != 0
            or abs(data[-1, 0] - STOP) > 1e-12
            or execution["returncode"]
            or execution["aborted"]
        ):
            raise RuntimeError("Start/stop mismatch or native abort")
    except RuntimeError as error:
        complete = False
        failure = str(error)
    result = {
        "complete": complete,
        "failure": failure,
        "actual_stop_s": float(data[-1, 0]),
        "shape": list(data.shape),
        "finite": bool(np.isfinite(data).all()),
    }
    if not result["finite"]:
        return result
    v = dict(zip(columns, data.T, strict=True))
    t = v["time"]
    b = dict(zip(benchmark_columns, benchmark.T, strict=True))
    bm = np.array([b[f"v({n})"] for n in ["ea", "eb", "er"]])
    bs = np.array([b[f"v({n})"] for n in ["sa", "sb", "sr"]])
    bx = np.array([b[f"v({n})"] for n in ["ta", "tb", "tr"]])
    base = {
        "eta": bm - bs,
        "coverage": 0.5 + (bx - bs) / 0.32,
        "current": np.array([b[f"i({n})"] for n in ["Vea", "Veb", "Vreturn"]]),
    }
    reference = {
        key: np.array([np.interp(t, b["time"], row) for row in value])
        for key, value in base.items()
    }
    networks = {tag: network(v, tag) for tag in ["rc", "stable"]}
    result["comparisons_to_benchmark"] = {
        tag: compare(value, reference, "benchmark") for tag, value in networks.items()
    }
    result["comparison_between_models"] = compare(networks["stable"], networks["rc"], "model")
    cap, qmax, rf = PARAMS
    result["networks"] = {}
    for tag, value in networks.items():
        eta, u, current = value["eta"], value["u"], value["current"]
        ia = (
            rc.CADS[:, None]
            / 0.02
            * (
                (eta - u)
                if tag == "rc"
                else (
                    value["metal"]
                    - value["state"]
                    + 0.16
                    * np.array([[stable.correction(float(x)) for x in row] for row in eta / 0.16])
                )
            )
        )
        work = float(np.trapezoid(np.sum(value["metal"] * current, axis=0), t))
        adsorption = float(np.trapezoid(np.sum(eta * ia, axis=0), t))
        cdl = float(np.sum(0.5 * cap * (eta[:, -1] ** 2 - eta[:, 0] ** 2)))
        solution_loss = float(
            np.trapezoid(
                np.sum(
                    value["solution_current"] ** 2 * np.array([10e6, 10e6, 1e6])[:, None], axis=0
                ),
                t,
            )
        )
        faradaic = float(np.trapezoid(np.sum(eta**2 / rf[:, None], axis=0), t))
        charge = (
            np.trapezoid(current - eta / rf[:, None], t, axis=1)
            - cap * (eta[:, -1] - eta[:, 0])
            - rc.CADS * (u[:, -1] - u[:, 0])
        )
        expected = np.array([np.interp(t, b["time"], row) for row in bm])
        result["networks"][tag] = {
            "coverage_min_max": [float(value["coverage"].min()), float(value["coverage"].max())],
            "max_abs_eta_V": float(abs(eta).max()),
            "metal_history_max_error_V": float(abs(value["metal"] - expected).max()),
            "terminal_KCL_max_A": float(abs(current.sum(axis=0)).max()),
            "solution_KCL_max_A": float(abs(value["solution_current"].sum(axis=0)).max()),
            "terminal_vs_solution_current_max_A": float(
                abs(current - value["solution_current"]).max()
            ),
            "integrated_charge_KCL_residual_C": charge.tolist(),
            "external_signed_source_work_J": work,
            "double_layer_delta_J": cdl,
            "signed_adsorption_terminal_work_J": adsorption,
            "solution_resistive_loss_J": solution_loss,
            "Faradaic_loss_J": faradaic,
            "electrode_energy_residual_J": work - cdl - adsorption - solution_loss - faradaic,
        }
    result["scope"] = (
        "Externally powered isolated voltage replay; not end-to-end power/startup or released-actuation validation. Input histories are piecewise-linear approximations between frozen adaptive samples."
    )
    return result


def run():
    if EVIDENCE.exists() or LOCAL.exists():
        raise FileExistsError("Electrode-replay destinations must be fresh")
    EVIDENCE.mkdir(parents=True)
    columns, data = tc.read_data(BENCHMARK)
    v = dict(zip(columns, data.T, strict=True))
    time, metals, dropped = prepare_history(
        v["time"], np.array([v[f"v({name})"] for name in ["ea", "eb", "er"]])
    )
    history = stimulus(time, metals)
    deck = build_deck()
    tc.write_json(
        EVIDENCE / "configuration.json",
        {
            "scope": __doc__,
            "benchmark_raw_sha256": tc.sha(BENCHMARK),
            "benchmark_local_path": str(BENCHMARK),
            "stimulus_local_path": str(LOCAL / "metal_history.spice"),
            "stimulus_points_each": len(time),
            "duplicate_times_removed": dropped,
            "duplicate_policy": "Remove identical duplicates only; reject conflicting same-time values rather than moving/smoothing events",
            "maximum_input_gap_s": float(np.diff(time).max()),
            "interpolation_limit": "Exact original knots, linear between them; no bound on unknown original between-sample waveform or edge-derivative error",
            "comparison_thresholds": LIMITS,
            "source_scope": "Independent external ideal voltage sources supply measured signed work, not finite PV or driver power",
            "initialization": "Default operating point; no UIC/seed/IC",
            "duration_s": STOP,
            "max_step_s": 25e-9,
        },
    )
    tc.write_json(
        EVIDENCE / "execution_counts.json",
        {
            "ngspice_processes": 1,
            "transients": 1,
            "model_copies": 2,
            "fine": 0,
            "rescue": 0,
            "DD": 0,
            "layout": 0,
        },
    )
    shutil.copy2(Path(__file__), EVIDENCE / "runner_as_executed.py")
    # execute() creates a fresh directory; use an include written before launch
    # through its filename argument replacement, without a second simulator call.
    original_execute = tc.execute

    def execute_with_history(destination, body):
        destination.mkdir(parents=True, exist_ok=False)
        (destination / "metal_history.spice").write_text(history)
        # Existing helper requires a fresh directory, so use its child and a
        # relative parent include; waveform bytes remain local.
        return original_execute(
            destination / "native",
            body.replace('"metal_history.spice"', '"../metal_history.spice"'),
            timeout=120,
        )

    execution = execute_with_history(LOCAL, deck)
    for source, target in [
        ("bench.spice", "replay_template.spice"),
        ("ngspice.log", "ngspice.log"),
        ("execution.json", "execution.json"),
    ]:
        shutil.copy2(LOCAL / "native" / source, EVIDENCE / target)
    replay_columns, replay_data = tc.read_data(LOCAL / "native/replay.dat")
    result = analyze(replay_columns, replay_data, execution, columns, data)
    result["raw_local_path"] = str(LOCAL / "native/replay.dat")
    result["raw_sha256"] = tc.sha(LOCAL / "native/replay.dat")
    tc.write_json(EVIDENCE / "metrics.json", result)
    tc.write_json(
        EVIDENCE / "local_waveform_hashes.json",
        {
            "stimulus_sha256": tc.sha(LOCAL / "metal_history.spice"),
            "replay_sha256": result["raw_sha256"],
            "benchmark_sha256": tc.sha(BENCHMARK),
        },
    )
    tc.write_json(
        EVIDENCE / "status.json",
        {
            "status": "Both isolated electrode models complete replay"
            if result["complete"]
            else "Incomplete isolated electrode replay",
            "acceptance": "Pending Astra review",
            "limit": "Neither outcome establishes a unique coupled failure cause",
        },
    )
    (EVIDENCE / "README.md").write_text(f"""# Isolated full-electrode voltage replay

One ngspice process runs two full electrode/solution networks together for **250 µs / 25 ns**. Complete: **{result["complete"]}**. Passive RC and stable nonlinear models receive identical independent copies of the completed passive benchmark's absolute metal-A, metal-B and Pt-return voltage histories. All14298 adaptive points are retained in a local-only PWL include; no raw waveform/stimulus is exported.

Both networks retain working/Pt-return interfaces, Cdl, adsorption state, RF and10/10/1 MΩ electrolyte paths. PV, logic, drivers, clamps and supervisors are absent. Default operating-point initialization is used without seeds/UIC. Ideal replay voltage sources explicitly supply signed terminal work; this is not an end-to-end PV power or actuation test.

Same-time identical points may be removed, but conflicting duplicate events are rejected. The selected trace has no duplicate times. All voltage knots round-trip at17 digits; interpolation is linear between samples. There is no bound on the original unknown between-sample voltage/derivative error. Removing feedback and prescribing metal voltages changes the problem; replay currents need not match every benchmark transient sample exactly. Comparisons use declared absolute floors plus peak-relative allowances, including the benchmark's known1.701 pA local-current precision caveat.

Metrics compare coverage, local eta and terminal currents between models and with the interpolated benchmark, plus source-work, KCL and integrated charge residuals. All incomplete-trace checks are prefix-only. Complete replay would point toward investigating coupled feedback/trajectory with a reduced reproducer, not prove a cause or validate original large-signal electrochemistry. A nonlinear-copy failure would provide a smaller reproducer, not a simulator-defect declaration. No phase, bending or released-actuation claim follows.

```text
MPLCONFIGDIR=/tmp/opentcad-mpl .venv/bin/python -m examples.microrobot.tcad_electrode_replay
```

Fresh destinations are required. Exact compact deck template, log, provenance hashes and executed runner are retained; waveform-bearing includes and raw replay remain local. Prior evidence/defaults are unchanged. No fine, rescue, DD, layout, submission, publication, push or fabrication occurred.
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
            {key: result[key] for key in ["complete", "actual_stop_s", "shape", "networks"]},
            indent=2,
        )
    )
    return result


if __name__ == "__main__":
    run()
