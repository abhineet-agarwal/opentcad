"""One reduced actuator-feedback bench with externally replayed logic rail."""

import json
from pathlib import Path
import re
import shutil

import numpy as np

from . import tcad_controller as tc
from . import tcad_electrode_replay as replay
from . import tcad_passive_adsorption as rc
from . import tcad_stable_adsorption as stable

EVIDENCE = tc.HERE / "results/tcad_actuator_feedback_replay"
LOCAL = tc.HERE / "local_runs/tcad_actuator_feedback_replay"
SOURCE = rc.EVIDENCE / "passive_adsorption.spice"
KEEP = [
    "Vlight",
    "Bpvlo",
    "Bpvhi",
    "Vpvlo",
    "Vpvhi",
    "Vact",
    "Cstorelo",
    "Cstorehi",
    "Rfixed_phase_A",
    "Rfixed_phase_B",
    "Vdriverslogic",
    "Vdriversact",
    "Vdriversmid",
    "Xda",
    "Xdb",
    "Vea",
    "Veb",
    "Vreturn",
    "Xea",
    "Xeb",
    "Xreturn",
    "Rsa",
    "Rsb",
    "Rsr",
    "Rfixed_ready",
]
NODES = [
    "light",
    "celllo",
    "cellhi",
    "act_raw",
    "act",
    "mid",
    "logic",
    "drivers_logic",
    "drivers_act",
    "drivers_mid",
    "pa",
    "pb",
    "driver_ready",
    "ea_driver",
    "eb_driver",
    "ea",
    "eb",
    "er",
    "sa",
    "sb",
    "sr",
    "ta",
    "tb",
    "tr",
    "bulk",
]
ALIASES = {"ea": "a", "eb": "b", "er": "r", "ta": "xa", "tb": "xb", "tr": "xr"}


def copy_line(line, tag):
    label, rest = line.split(" ", 1)
    labels = {"Vea": f"Vp_{tag}_a", "Veb": f"Vp_{tag}_b", "Vreturn": f"Vp_{tag}_r"}
    renamed = re.sub(
        r"\b(" + "|".join(sorted(NODES, key=len, reverse=True)) + r")\b",
        lambda m: tag + "_" + ALIASES.get(m[0], m[0]),
        rest,
    )
    return labels.get(label, label + "_" + tag) + " " + renamed


def build_deck():
    source = SOURCE.read_text()
    lines = [tc.header(), stable.FUNCTION, '.include "../logic_history.spice"']
    for name in ["microrobot_driver", "micro_inv", "micro_nand2"]:
        lines.append(re.search(r"(?ms)^\.subckt " + name + r"\b.*?^\.ends[^\n]*", source).group())
    vectors = []
    for tag, path in [("rc", SOURCE), ("stable", stable.EVIDENCE / "stable_adsorption.spice")]:
        model = (
            re.search(
                r"(?ms)^\.subckt micro_electrode\b.*?^\.ends micro_electrode[^\n]*",
                path.read_text(),
            )
            .group()
            .replace("micro_electrode", "electrode_" + tag)
        )
        lines += [model, f"Xlogic_{tag} {tag}_logic logic_history"]
        for label in KEEP:
            original = re.search(r"^" + re.escape(label) + r" .*$", source, re.M).group()
            lines.append(copy_line(original, tag).replace(" micro_electrode", " electrode_" + tag))
        vectors += [
            f"v({tag}_{node})"
            for node in [
                "a",
                "b",
                "r",
                "sa",
                "sb",
                "sr",
                "xa",
                "xb",
                "xr",
                "bulk",
                "logic",
                "act",
                "act_raw",
                "mid",
                "celllo",
                "cellhi",
                "driver_ready",
                "pa",
                "pb",
            ]
        ]
        vectors += [f"i(Vp_{tag}_{node})" for node in ["a", "b", "r"]]
        vectors += [
            f"i({name}_{tag})"
            for name in ["Vpvlo", "Vpvhi", "Vdriverslogic", "Vdriversact", "Vdriversmid"]
        ]
    lines += [
        ".options method=gear maxord=2 reltol=1e-6 abstol=1e-15",
        ".control",
        "set wr_vecnames",
        "set wr_singlescale",
        "set numdgt=17",
        "option > options_before.txt",
        "save " + " ".join(vectors),
        "tran 25n .00025 0 25n",
        "option > options_effective.txt",
        "wrdata feedback.dat " + " ".join(vectors),
        "quit",
        ".endc",
        ".end",
    ]
    return "\n".join(lines) + "\n"


def logic_history(time, voltage):
    return (
        ".subckt logic_history logic\nVrail logic 0 PWL(\n"
        + "".join(f"+ {t:.17g} {v:.17g}\n" for t, v in zip(time, voltage, strict=True))
        + "+ )\n.ends logic_history\n"
    )


def analyze(columns, data, execution, benchmark_columns, benchmark):
    result = replay.analyze(columns, data, execution, benchmark_columns, benchmark)
    v = dict(zip(columns, data.T, strict=True))
    t = v["time"]
    result["actuator_feedback"] = {}
    for tag in ["rc", "stable"]:
        def n(name):
            return v[f"v({tag}_{name})"]
        def current(name):
            return v[f"i({name}_{tag})"]
        def integrate(power):
            return float(np.trapezoid(power, t))
        logic, act, mid = n("logic"), n("act"), n("mid")
        pv = integrate(mid * current("Vpvlo") + (act - mid) * current("Vpvhi"))
        storage = 0.5e-12 * (mid**2 + (n("act_raw") - mid) ** 2)
        delta = float(storage[-1] - storage[0])
        load = {
            "driver_logic": integrate(logic * current("Vdriverslogic")),
            "driver_actuator": integrate(act * current("Vdriversact")),
            "driver_midpoint": integrate(mid * current("Vdriversmid")),
            "Pt_return": integrate(mid * v[f"i(Vp_{tag}_r)"]),
        }
        cells = np.array([n("celllo") / 2, (n("cellhi") - mid) / 2])
        enabled = (act >= 0.5) & (n("driver_ready") > 0.5 * act)
        powered = (logic >= 1) & (act >= 0.5)
        clamp = np.maximum(abs(n("a") - mid), abs(n("b") - mid))
        result["actuator_feedback"][tag] = {
            "node_bounds": {
                name: [float(n(name).min()), float(n(name).max()), float(n(name)[-1])]
                for name in ["logic", "act", "mid", "driver_ready", "pa", "pb"]
            },
            "PV_cell_bounds_V": [float(cells.min()), float(cells.max())],
            "DD_domain_pass": bool(cells.min() >= -1e-9 and cells.max() <= 0.7 + 1e-9),
            "drivers_held": not bool(enabled.any()),
            "powered_clamp_peak_V": float(clamp[powered].max()) if powered.any() else None,
            "PV_delivered_J": pv,
            "external_replayed_logic_delivery_J": load["driver_logic"],
            "actuator_storage_delta_J": delta,
            "measured_ports_J": load,
            "actuator_supply_residual_J": pv
            - delta
            - load["driver_actuator"]
            - load["driver_midpoint"]
            - load["Pt_return"],
        }
        result["networks"][tag]["electrode_signed_port_work_J"] = result["networks"][tag].pop(
            "external_signed_source_work_J"
        )
    result["scope"] = (
        "Reduced actuator/PV/driver feedback with externally powered replayed logic only; electrode metals/midpoint are solved, not replayed. No full TCAD controller power or actuation validation."
    )
    result["all_comparisons_pass"] = all(
        item["pass"]
        for group in list(result["comparisons_to_benchmark"].values())
        + [result["comparison_between_models"]]
        for item in group.values()
    )
    return result


def run():
    if EVIDENCE.exists() or LOCAL.exists():
        raise FileExistsError("Feedback-replay destinations must be fresh")
    EVIDENCE.mkdir(parents=True)
    LOCAL.mkdir(parents=True)
    query = Path(Path("/tmp/opentcad-feedback-options-path.txt").read_text())
    for name in ["options.spice", "options.log"]:
        shutil.copy2(query / name, EVIDENCE / ("no_analysis_" + name))
    (
        EVIDENCE / "numerical_conventions.md"
    ).write_text("""# Numerical conventions documented before transient

Installed ngspice44.2, same hsa initialization. The saved no-analysis option query reports CHGTOL1e-14 C, TRTOL7, VNTOL1e-6 V, GMIN1e-12. No A devices occur in this reduced bench. These unmodified defaults are expected here; options_effective.txt after the sole transient will confirm applied settings. The pre-analysis option listing shows old current settings, not queued .options; it must not be mistaken for the requested Gear2/reltol1e-6/abstol1e-15 settings.

The official [manual44](https://ngspice.sourceforge.io/docs/ngspice-44-manual.pdf), sections11.1.2/11.1.4 and13.5.55, distinguishes convergence, charge and truncation controls. ABSTOL1e-15 is not a bound on every saved transient current or KCL discrepancy. Charge integration, step control and numerical conditioning also matter, without uniquely explaining earlier pA residuals. No tolerance is changed.

I(Vprobe) is positive from the probe's first node to its second. It is a voltage-source branch current; SAVECURRENTS device vectors are not used. That option's possible one-step-delay warning therefore does not establish the cause here. Output uses native adaptive samples,17 digits and no INTERP.
""")
    columns, benchmark = tc.read_data(replay.BENCHMARK)
    b = dict(zip(columns, benchmark.T, strict=True))
    time, voltage, dropped = replay.prepare_history(b["time"], b["v(logic)"][None, :])
    (LOCAL / "logic_history.spice").write_text(logic_history(time, voltage[0]))
    deck = build_deck()
    tc.write_json(
        EVIDENCE / "configuration.json",
        {
            "included_elements_per_copy": KEEP,
            "shared_exact_macros": ["microrobot_driver", "micro_inv", "micro_nand2"],
            "removed": "Clock, firstDFF/feedback, proxy/counter, native supervisor, logicPV/storage; external replay powers driver logic",
            "logic_history_points": len(time),
            "duplicates_removed": dropped,
            "logic_history_local": str(LOCAL / "logic_history.spice"),
            "logic_history_sha256": tc.sha(LOCAL / "logic_history.spice"),
            "benchmark_sha256": tc.sha(replay.BENCHMARK),
            "metals_midpoint": "Solved native-driver/electrode/PV feedback, never replayed",
            "limits": replay.LIMITS,
            "initialization": "OP/noUIC/noIC/seeds",
            "duration_s": 250e-6,
            "max_step_s": 25e-9,
            "tolerance_note": "numerical_conventions.md written before transient; effective listing retained after",
        },
    )
    tc.write_json(
        EVIDENCE / "execution_counts.json",
        {
            "transient_processes": 1,
            "transients": 1,
            "copies": 2,
            "no_analysis_options_queries": 1,
            "version_queries": 1,
            "fine": 0,
            "rescue": 0,
            "DC_sweeps": 0,
            "DD": 0,
            "layout": 0,
        },
    )
    shutil.copy2(Path(__file__), EVIDENCE / "runner_as_executed.py")
    execution = tc.execute(LOCAL / "native", deck, timeout=600)
    for source, target in [
        ("bench.spice", "feedback_template.spice"),
        ("ngspice.log", "ngspice.log"),
        ("execution.json", "execution.json"),
        ("options_before.txt", "options_before.txt"),
        ("options_effective.txt", "options_effective.txt"),
    ]:
        if (LOCAL / "native" / source).exists():
            shutil.copy2(LOCAL / "native" / source, EVIDENCE / target)
    output_columns, data = tc.read_data(LOCAL / "native/feedback.dat")
    result = analyze(output_columns, data, execution, columns, benchmark)
    result["raw_local_path"] = str(LOCAL / "native/feedback.dat")
    result["raw_sha256"] = tc.sha(LOCAL / "native/feedback.dat")
    tc.write_json(EVIDENCE / "metrics.json", result)
    tc.write_json(
        EVIDENCE / "status.json",
        {
            "status": "Completed reduced actuator-feedback replay"
            if result["complete"]
            else "Incomplete reduced actuator-feedback replay",
            "acceptance": "Pending Astra review",
            "limit": "A single global abort cannot automatically be attributed to only one copy; no unique causal/full-system claim",
        },
    )
    (EVIDENCE / "README.md").write_text(f"""# Reduced actuator-feedback logic-rail replay

One process, two isolated full actuator/PV/native-driver/electrode feedback copies, **250 µs /25 ns**. Complete: **{result["complete"]}**. Only the completed passive benchmark's logic rail is replayed from all adaptive samples. Actual electrode metals, actuator rails and Pt midpoint remain solved feedback nodes. External logic-rail power is explicitly measured, so this is not a full TCAD-powered controller test.

Exact inclusion list is configuration.json: two DD actuator half-stacks and1 pF storage each, native transistor drivers, passive phase/ready clamps, three electrode interfaces and10/10/1 MΩ solution paths. Shared driver macros and retained lines are copied from the frozen deck with node/instance namespaces only. Clock, DFF, proxy/counter and supervisor dynamics and logicPV/storage are removed. RC/stable copies differ only in electrode adsorption branch. Default operating point, no seeds/UIC, unchanged Gear2/reltol/abstol and25 ns maximum step.

Before execution, numerical_conventions.md records installed charge/truncation defaults and branch-current conventions. Effective post-initialization options are in options_effective.txt. The pre-analysis list is not proof queued options are applied. ABSTOL alone cannot explain or bound prior pA discrepancies.

Coverage/eta/current comparisons retain prior replay floors/limits without posthoc changes. Native current precision, signed electrode work, finite-PV/storage/driver-port balance and externally supplied logic work remain separate. Incomplete traces support prefix checks only. A global two-copy abort cannot identify one copy as its cause without additional evidence; no released actuation, bending or unique simulator-defect claim follows.

```text
MPLCONFIGDIR=/tmp/opentcad-mpl .venv/bin/python -m examples.microrobot.tcad_actuator_feedback_replay
```

Waveform-bearing logic include and raw output remain local; compact deck template, log, options, exact provenance and source are retained. No rescue, fine, source/DD/layout rerun, publication, submission, push or fabrication occurred.
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
                key: result[key]
                for key in ["complete", "actual_stop_s", "shape", "actuator_feedback"]
            },
            indent=2,
        )
    )
    return result


if __name__ == "__main__":
    run()
