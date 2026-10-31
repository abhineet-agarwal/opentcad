"""Isolated native OP/AC audit of exact adsorption current expressions."""

from decimal import Decimal, localcontext
import json
from pathlib import Path
import re
import shutil

import numpy as np

from . import tcad_controller as tc
from . import tcad_stable_adsorption as stable

EVIDENCE = tc.HERE / "results/tcad_adsorption_source_audit"
LOCAL = tc.HERE / "local_runs/tcad_adsorption_source_audit"
RAW = stable.LOCAL / "controller.dat"
DECKS = {
    "resistor": tc.HERE / "results/tcad_passive_adsorption/passive_adsorption.spice",
    "linear_B": tc.HERE / "results/tcad_linear_bads/linear_bads.spice",
    "stable_B": stable.EVIDENCE / "stable_adsorption.spice",
}
THRESHOLDS = {
    "DC_abs_A": 1e-22,
    "DC_rel": 1e-10,
    "AC_abs_S": 1e-20,
    "AC_rel": 1e-8,
    "input_voltage_abs_V": 1e-12,
    "imaginary_current_abs_A_per_V": 1e-20,
}
MANUAL = "https://ngspice.sourceforge.io/docs/ngspice-44-manual.pdf"


def select_cases():
    columns, data = tc.read_data(RAW)
    v = dict(zip(columns, data.T, strict=True))
    peak = int(np.argmax(abs(v["v(ea)"] - v["v(sa)"])))
    cases = [{"name": "zero", "m": 0.0, "x": 0.0, "s": 0.0, "qmax": "260p"}]
    for name, index, m, x, s, q in [
        ("working_peak_eta", peak, "ea", "ta", "sa", "260p"),
        ("working_last", len(data) - 1, "ea", "ta", "sa", "260p"),
        ("return_last", len(data) - 1, "er", "tr", "sr", "2600p"),
    ]:
        cases.append(
            {
                "name": name,
                "m": float(v[f"v({m})"][index]),
                "x": float(v[f"v({x})"][index]),
                "s": float(v[f"v({s})"][index]),
                "qmax": q,
                "saved_row": index,
                "saved_time_s": float(v["time"][index]),
                "saved_columns": [f"v({m})", f"v({x})", f"v({s})"],
            }
        )
    shifted = {**cases[2], "name": "working_last_common_mode_shift", "common_mode_shift_V": -0.5}
    for name in ["m", "x", "s"]:
        shifted[name] -= 0.5
    cases += [
        shifted,
        {"name": "nonlinear_eta_0p16", "m": 0.56, "x": 0.4, "s": 0.4, "qmax": "260p"},
    ]
    return cases


def expressions():
    prefixes = {"resistor": "Rads ", "linear_B": "Bads_linear ", "stable_B": "Bads_stable "}
    return {
        name: re.search(r"^" + prefix + r".*$", path.read_text(), re.M).group()
        for name, (path, prefix) in (
            (name, (DECKS[name], prefix)) for name, prefix in prefixes.items()
        )
    }


def build_deck(cases):
    laws = expressions()
    saved = DECKS["stable_B"].read_text()
    function = re.search(r"^\.func ads_c.*$", saved, re.M).group()
    lines = [
        "* Isolated adsorption source current and native AC Jacobian audit",
        ".temp 26.85",
        function,
    ]
    for name, law in laws.items():
        lines += [
            f".subckt audit_{name} metal adsnode solution params: qmax=260p width=0.08 tau=20m offset=0",
            law,
            f".ends audit_{name}",
        ]
    records = []
    for case in cases:
        for model in laws:
            for drive in ["m", "x", "s"]:
                tag = f"k{len(records):03d}"
                for node in ["m", "x", "s"]:
                    terminal = "d" + tag if node == "m" else node + tag
                    lines.append(
                        f"V{node}{tag} {terminal} 0 DC {case[node]:.17g} AC {int(node == drive)}"
                    )
                lines += [
                    f"Vp{tag} d{tag} m{tag} 0",
                    f"X{tag} m{tag} x{tag} s{tag} audit_{model} qmax={case['qmax']}",
                ]
                records.append({"tag": tag, "case": case, "model": model, "drive": drive})
    # Same numerical tolerances as preceding benches; no transient command.
    lines += [
        ".options method=gear maxord=2 reltol=1e-6 abstol=1e-15",
        ".control",
        "set wr_vecnames",
        "set wr_singlescale",
        "set numdgt=17",
        "op",
    ]
    vectors = []
    for record in records:
        tag = record["tag"]
        names = [
            f"i(Vp{tag})",
            f"v(m{tag})",
            f"v(x{tag})",
            f"v(s{tag})",
            f"i(Vm{tag})",
            f"i(Vx{tag})",
            f"i(Vs{tag})",
        ]
        vectors.append(names)
        lines.append(f"wrdata {tag}_op.dat " + " ".join(names))
    lines += ["ac lin 1 1 1"]
    for record, names in zip(records, vectors, strict=True):
        lines.append(
            f"wrdata {record['tag']}_ac.dat "
            + " ".join(f"real({name}) imag({name})" for name in names)
        )
    lines += ["quit", ".endc", ".end"]
    return "\n".join(lines) + "\n", records


def reference(case, model):
    with localcontext() as context:
        context.prec = 80
        D = Decimal
        m, x, s = (D.from_float(case[name]) for name in ["m", "x", "s"])
        q = D("260e-12") if case["qmax"] == "260p" else D("2600e-12")
        w = D(".08")
        tau = D(".02")
        g = q / (4 * w * tau)
        if model != "stable_B":
            return float(g * (m - x)), [float(g), float(-g), 0.0]
        z = (m - s) / (2 * w)
        exp = (2 * z).exp()
        th = (exp - 1) / (exp + 1)
        if abs(z) < D(".001"):
            c = -(z**3) / 3 + 2 * z**5 / 15 - 17 * z**7 / 315
            cp = -(z**2) + 2 * z**4 / 3 - 17 * z**6 / 45
        else:
            c = th - z
            cp = -th * th
        value = g * (m - x + 2 * w * c)
        return float(value), [float(g * (1 + cp)), float(-g), float(-g * cp)]


def parse_native(path, ac=False):
    _, data = tc.read_data(path)
    expected = 15 if ac else 8
    if data.shape != (1, expected) or not np.isfinite(data).all():
        raise RuntimeError(f"Bad native audit output: {path}, {data.shape}")
    if ac:
        if abs(data[0, 0] - 1) > 1e-12:
            raise RuntimeError("Wrong AC frequency")
        return data[0, 1::2] + 1j * data[0, 2::2]
    return data[0, 1:]


def within(value, expected, absolute, relative):
    return abs(value - expected) <= absolute + relative * abs(expected)


def run():
    if EVIDENCE.exists() or LOCAL.exists():
        raise FileExistsError("Native source-audit destinations must be fresh")
    EVIDENCE.mkdir(parents=True)
    cases = select_cases()
    deck, records = build_deck(cases)
    tc.write_json(
        EVIDENCE / "configuration.json",
        {
            "scope": __doc__,
            "cases": cases,
            "exact_laws": expressions(),
            "source_deck_sha256": {name: tc.sha(path) for name, path in DECKS.items()},
            "saved_trace_sha256": tc.sha(RAW),
            "thresholds": THRESHOLDS,
            "AC_frequency_Hz": 1,
            "AC_input": "Each isolated clone has one independent1V input; othersAC0",
            "probe_sign": "Vp from metal-drive node into branch metal; I(Vp)>0 is metal→state current",
            "manual": {
                "url": MANUAL,
                "sections": "5.1.1 (printed page106),1.2.2 (page40)",
                "meaning": "B-source AC coefficients are derivatives at the DC operating point; unity excitation gives the partial directly",
            },
            "limit": "Only isolated branch law/linearization; no coupled controller transient, capacitance dynamics or root-cause inference",
        },
    )
    tc.write_json(
        EVIDENCE / "execution_counts.json",
        {
            "ngspice_processes": 1,
            "explicit_OP": 1,
            "AC": 1,
            "AC_internal_DC_operating_point": 1,
            "controller_transients": 0,
            "DC_sweeps": 0,
            "DD": 0,
            "layout": 0,
        },
    )
    shutil.copy2(Path(__file__), EVIDENCE / "runner_as_executed.py")
    execution = tc.execute(LOCAL, deck, timeout=120)
    for source, target in [
        ("bench.spice", "source_audit.spice"),
        ("ngspice.log", "ngspice.log"),
        ("execution.json", "execution.json"),
    ]:
        shutil.copy2(LOCAL / source, EVIDENCE / target)
    if execution["returncode"] or execution["aborted"]:
        raise RuntimeError("Native source audit failed; see saved log")
    rows = []
    for record in records:
        tag = record["tag"]
        case = record["case"]
        model = record["model"]
        drive = record["drive"]
        dc = parse_native(LOCAL / f"{tag}_op.dat")
        ac = parse_native(LOCAL / f"{tag}_ac.dat", True)
        current, partials = reference(case, model)
        derivative = partials[["m", "x", "s"].index(drive)]
        desired = np.array([int(drive == node) for node in ["m", "x", "s"]])
        input_error = float(np.max(abs(ac[1:4] - desired)))
        bias_error = float(np.max(abs(dc[1:4] - [case["m"], case["x"], case["s"]])))
        input_kcl = float(max(abs(ac[4] + ac[0]), abs(ac[5] - ac[0]), abs(ac[6])))
        row = {
            "case": case["name"],
            "model": model,
            "drive": drive,
            "native_current_A": float(dc[0]),
            "reference_current_A": current,
            "current_error_A": float(dc[0] - current),
            "native_partial_S": float(ac[0].real),
            "native_partial_imag_S": float(ac[0].imag),
            "reference_partial_S": derivative,
            "partial_error_S": float(ac[0].real - derivative),
            "input_matrix_error_V": input_error,
            "DC_bias_error_V": bias_error,
            "AC_source_current_KCL_error_A": input_kcl,
            "current_pass": within(dc[0], current, THRESHOLDS["DC_abs_A"], THRESHOLDS["DC_rel"]),
            "partial_pass": within(
                ac[0].real, derivative, THRESHOLDS["AC_abs_S"], THRESHOLDS["AC_rel"]
            )
            and abs(ac[0].imag) < THRESHOLDS["imaginary_current_abs_A_per_V"],
            "inputs_pass": max(input_error, bias_error) < THRESHOLDS["input_voltage_abs_V"]
            and input_kcl < 1e-20,
        }
        rows.append(row)
    passed = all(row["current_pass"] and row["partial_pass"] and row["inputs_pass"] for row in rows)
    metrics = {
        "passed": passed,
        "bias_cases": len(cases),
        "isolated_clones": len(records),
        "native_results": rows,
        "max_current_error_A": max(abs(row["current_error_A"]) for row in rows),
        "max_partial_error_S": max(abs(row["partial_error_S"]) for row in rows),
        "max_input_matrix_error_V": max(row["input_matrix_error_V"] for row in rows),
        "interpretation": "Agreement supports a reduced coupled reproducer next; it does not establish complete startup or a simulator defect"
        if passed
        else "At least one isolated native current/partial/input check differs beyond declared tolerances; inspect before any causal inference",
        "error_floor": "Absolute+relative criteria; near-zero partials are judged by absolute error, not relative-to-zero percentages",
    }
    tc.write_json(EVIDENCE / "metrics.json", metrics)
    tc.write_json(
        EVIDENCE / "raw_hashes.json", {p.name: tc.sha(p) for p in sorted(LOCAL.glob("*.dat"))}
    )
    tc.write_json(
        EVIDENCE / "status.json",
        {
            "status": "Isolated native DC/AC audit agrees"
            if passed
            else "Isolated native DC/AC audit discrepancy",
            "acceptance": "Pending Astra review",
        },
    )
    (EVIDENCE / "README.md").write_text(f"""# Isolated native adsorption-source DC/AC audit

All declared current/partial/input checks pass: **{passed}**. One installed-ngspice process packs six biases×three exact saved models×three independent terminal excitations, with one explicit operating-point analysis and one1 Hz AC analysis (which also computes its DC operating point). **No controller transient, tolerance change, physics edit, DD or layout run occurs.**

The cases are zero, saved working-electrode peak eta, saved working-electrode and Pt-return pre-abort endpoints, a bounded common-mode shift, and one clearly nonlinear eta0.16 V bias. Actual row/time/node values and source/raw hashes are retained in configuration.json. The source-only bench omits capacitors and surrounding circuits deliberately: independent ideal sources hold metal/state/solution voltages and isolate the static law and its native AC derivatives. No transient behavior is inferred.

Each clone has exactly one independent1 V AC input, the other terminalsAC0. The measured input matrix must be the identity. The zero-volt current probe points from the drive into metal, so positive I(Vprobe) is metal→state current. The primitive resistor oracle must give derivatives(+g,−g,0); saved source currents independently check probe sign and branch KCL.

The [official ngspice44 manual]({MANUAL}) §5.1.1 states that a B-source's AC coefficients are derivatives at its DC operating point; §1.2.2 explains unity input scaling. Native DC/AC outputs are compared with Decimal80-digit current and voltage-partial references for the exact model expression, including the stable polynomial correction. Declared absolute-plus-relative thresholds protect near-zero current/partials from meaningless relative errors. Tiny nonlinear corrections and common-mode error floors remain explicit.

{metrics["interpretation"]}. This audit does not qualify coupled startup, released actuation, electrochemistry or native transient integration.

```text
MPLCONFIGDIR=/tmp/opentcad-mpl .venv/bin/python -m examples.microrobot.tcad_adsorption_source_audit
```

The runner requires fresh destinations. Exact deck/log, source snapshot, detailed metrics and hashes are retained; native raw files remain local. Prior evidence is unchanged. No publication, submission, push or fabrication occurred.
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
                key: metrics[key]
                for key in [
                    "passed",
                    "max_current_error_A",
                    "max_partial_error_S",
                    "max_input_matrix_error_V",
                ]
            },
            indent=2,
        )
    )
    return metrics


if __name__ == "__main__":
    run()
