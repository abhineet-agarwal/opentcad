"""One held-input startup with small-signal passive adsorption RC branches."""

import difflib
import json
from pathlib import Path
import re
import shutil

import numpy as np

from . import tcad_controller as tc
from . import tcad_passive_clamps as passive

EVIDENCE = tc.HERE / "results/tcad_passive_adsorption"
LOCAL = tc.HERE / "local_runs/tcad_passive_adsorption"
SOURCE = passive.EVIDENCE / "passive_clamps.spice"
WIDTH = 0.08
TAU = 0.02
QMAX = np.array([260e-12, 260e-12, 2600e-12])
CADS = QMAX / (4 * WIDTH)
RADS = TAU / CADS
PATTERN = r"(?ms)^\.subckt micro_electrode\b.*?^\.ends micro_electrode[^\n]*"


def verified_parameters(source):
    original = re.search(PATTERN, source).group()
    expected = ".subckt micro_electrode metal solution theta params: cdl=40p qmax=260p tau=20m rf=10g width=0.08 offset=0"
    if original.splitlines()[0] != expected:
        raise ValueError("Unexpected electrode parameters or pin order")
    if "Xreturn er sr tr micro_electrode cdl=400p qmax=2600p rf=1g" not in source:
        raise ValueError("Unexpected return parameters")
    if (
        "Cdouble metal solution {cdl}" not in original
        or "Rfaradaic metal solution {rf}" not in original
    ):
        raise ValueError("Unexpected Cdl/Faradaic topology")
    return original


def build_deck():
    source = SOURCE.read_text()
    original = verified_parameters(source)
    replacement = """* Linearized at eta=offset=0, theta0=0.5; third pin is now physical Cads node.
.subckt micro_electrode metal solution adsnode params: cdl=40p qmax=260p tau=20m rf=10g width=0.08 offset=0
Cdouble metal solution {cdl}
Rfaradaic metal solution {rf}
Rads metal adsnode {tau*4*width/qmax}
Cads adsnode solution {qmax/(4*width)}
.ends micro_electrode"""
    return source.replace(original, replacement, 1)


def analyze(columns, data, execution, table):
    v = dict(zip(columns, data.T, strict=True))
    eta = np.array([v["v(ea)"] - v["v(sa)"], v["v(eb)"] - v["v(sb)"], v["v(er)"] - v["v(sr)"]])
    u = np.array([v["v(ta)"] - v["v(sa)"], v["v(tb)"] - v["v(sb)"], v["v(tr)"] - v["v(sr)"]])
    coverage = 0.5 + u / (4 * WIDTH)
    derived = data.copy()
    for index, node in enumerate(["ta", "tb", "tr"]):
        derived[:, columns.index(f"v({node})")] = coverage[index]
    # Reuse non-adsorption circuit bookkeeping. Replace its old nonlinear
    # adsorption estimate below; raw ta/tb/tr are capacitor nodes, not theta.
    result = passive.analyze(columns, derived, execution, table)
    if not np.isfinite(data).all():
        return result
    t = v["time"]

    def integrate(power):
        return float(np.trapezoid(power, t))

    iads = (eta - u) / RADS[:, None]
    stored = 0.5 * CADS[:, None] * u**2
    delta = float(np.sum(stored[:, -1] - stored[:, 0]))
    loss = integrate(np.sum(iads**2 * RADS[:, None], axis=0))
    work = integrate(np.sum(eta * iads, axis=0))
    energy = result["energy_J"]
    energy.pop("signed_adsorption_work")
    energy.update(
        adsorption_RC_storage_delta=delta,
        adsorption_resistive_loss=loss,
        adsorption_terminal_work=work,
        adsorption_RC_balance_residual=work - delta - loss,
    )
    energy["electrode_residual"] = (
        energy["electrode_metal_port_work"]
        - energy["double_layer_delta"]
        - delta
        - loss
        - energy["Faradaic_loss"]
        - energy["solution_resistive_loss"]
    )
    result["diagnostic_checks"]["electrode_energy_2percent"] = abs(
        energy["electrode_residual"]
    ) < max(abs(energy["electrode_metal_port_work"]) * 0.02, 1e-15)
    ratio = float(np.max(abs(eta)) / WIDTH)
    error = float(np.max(abs(1 / (1 + np.exp(-eta / WIDTH)) - (0.5 + eta / (4 * WIDTH)))))
    result["small_signal"] = {
        "max_abs_eta_over_width": ratio,
        "required_strict_upper_limit": 0.01,
        "within_interpretation_gate": ratio < 0.01,
        "max_logistic_equilibrium_linearization_error": error,
        "coverage_min_max": [float(coverage.min()), float(coverage.max())],
        "reference": "theta0=0.5 at eta=0; coverage=.5+(Vadsnode−Vsolution)/(4width)",
        "raw_state_columns": "v(ta),v(tb),v(tr) now physical capacitor-node potentials; never raw coverage",
    }
    result["diagnostic_checks"]["small_signal_interpretation"] = ratio < 0.01
    result["all_diagnostic_checks_pass"] = all(result["diagnostic_checks"].values())
    rf = np.array([10e9, 10e9, 1e9])
    cap = np.array([40e-12, 40e-12, 400e-12])
    currents = np.array([v["i(Vea)"], v["i(Veb)"], v["i(Vreturn)"]])
    residual = (
        np.trapezoid(currents - eta / rf[:, None], t, axis=1)
        - cap * (eta[:, -1] - eta[:, 0])
        - CADS * (u[:, -1] - u[:, 0])
    )
    result["electrode_integrated_charge_KCL_residual_C"] = residual.tolist()
    result["adsorption_energy_scope"] = (
        "Passive RC capacitor storage plus positive resistor heat; original nonlinear signed adsorption work is not a component of this diagnostic"
    )
    result["measurement_change"] = (
        "No probes or save vectors changed from the frozen passive-clamp deck; ta/tb/tr now mean physical capacitor nodes, with coverage reconstructed offline. Removed open-port analytical zeros are inherited from that prior deck."
    )
    result["scope"] = (
        "Small-signal held-input startup only; no large-signal adsorption, released actuation, phase/bending or autonomous validation"
    )
    return result


def run():
    if EVIDENCE.exists() or LOCAL.exists():
        raise FileExistsError("Passive-adsorption destinations must be fresh")
    EVIDENCE.mkdir(parents=True)
    deck = build_deck()
    prior = SOURCE.read_text()
    tc.write_json(
        EVIDENCE / "configuration.json",
        {
            "scope": __doc__,
            "source_deck_sha256": tc.sha(SOURCE),
            "Qmax_C": QMAX.tolist(),
            "width_V": WIDTH,
            "tau_s": TAU,
            "offset_V": 0,
            "reference_coverage": 0.5,
            "Cads_F": CADS.tolist(),
            "Rads_ohm": RADS.tolist(),
            "formula": "Cads=Qmax/(4width); Rads=tau/Cads",
            "topology": "metal→Rads→adsnode→Cads→solution; Cdl and RF remain metal→solution",
            "measurement_change": "No added/removed probes or save vectors; ta/tb/tr change from numerical coverage to physical Cads node, recovered offline",
            "unchanged": "All other TCAD, logic/actuator circuits, clamp resistors, timing, storage, solver and output probes",
            "interpretation_gate": "max(abs(eta))/width <0.01; no large-signal claim",
        },
    )
    tc.write_json(
        EVIDENCE / "execution_counts.json",
        {"transients": 1, "fine": 0, "rescue": 0, "DC": 0, "DD": 0, "layout": 0},
    )
    shutil.copy2(Path(__file__), EVIDENCE / "runner_as_executed.py")
    (EVIDENCE / "deck.diff").write_text(
        "".join(
            difflib.unified_diff(
                prior.splitlines(True),
                deck.splitlines(True),
                fromfile="nonlinear_adsorption",
                tofile="passive_small_signal_adsorption",
            )
        )
    )
    execution = tc.execute(LOCAL, deck)
    for source, target in [
        ("bench.spice", "passive_adsorption.spice"),
        ("ngspice.log", "ngspice.log"),
        ("execution.json", "execution.json"),
    ]:
        shutil.copy2(LOCAL / source, EVIDENCE / target)
    if (LOCAL / "controller.dat").exists():
        columns, data = tc.read_data(LOCAL / "controller.dat")
        result = analyze(columns, data, execution, tc.load_table())
        result["raw_sha256"] = tc.sha(LOCAL / "controller.dat")
        result["raw_local_path"] = str(LOCAL / "controller.dat")
    else:
        result = {"complete": False, "failure": "No transient output"}
    tc.write_json(EVIDENCE / "metrics.json", result)
    tc.write_json(
        EVIDENCE / "status.json",
        {
            "status": "Complete passive small-signal adsorption diagnostic"
            if result["complete"]
            else "Incomplete passive small-signal adsorption diagnostic",
            "acceptance": "Pending Astra review",
            "scope": "Held inputs and small-signal interpretation only",
        },
    )
    (EVIDENCE / "README.md").write_text(f"""# Passive small-signal adsorption diagnostic

One **250 µs / 25 ns** cold-start diagnostic. Complete: **{result["complete"]}**. No fine, rescue, DC, DD or layout run was added. Only the three adsorption state branches change; all other circuits and output probes remain identical to the frozen passive-clamp deck.

Verified working-electrode parameters are Qmax260 pC, width0.08 V, tau20 ms, offset0; Pt return Qmax2600 pC with the same width/tau. Linearizing logistic coverage at eta0=0, theta0=0.5 gives Cads=Qmax/(4width) and Rads=tau/Cads. Each working interface therefore uses **812.5 pF /24.615384615 MΩ**, return **8.125 nF /2.461538462 MΩ**. Rads connects metal to the third node and Cads connects that node to local solution; Cdl and RF remain unchanged. Positive eta charges a positive capacitor voltage and raises reconstructed coverage.

The existing third-node save vectors ta/tb/tr now encode physical capacitor-node potentials. Offline coverage is **0.5+(Vadsnode−Vsolution)/(4width)**. No ideal coverage source, probe change, voltage seed or UIC is introduced. Interpretation requires **max|eta|/width <0.01** over the entire saved trace. This local approximation does not calibrate or qualify large-signal electrochemistry.

Adsorption energy is now physical RC storage change plus nonnegative Rads heat, separately checked against terminal work. It replaces the original model's signed adsorption-work term and is not claimed to reproduce that nonlinear model globally. Cdl, Faradaic, solution, clamp and measured source-load terms remain separate. All checks on an incomplete trace are prefix-only. Held commands remain zero; no released actuation, phase/gait, bending or autonomous-controller validation is made. A changed outcome or trouble equation does not identify a unique cause.

```text
MPLCONFIGDIR=/tmp/opentcad-mpl .venv/bin/python -m examples.microrobot.tcad_passive_adsorption
```

Fresh destinations are required. Exact deck/log/diff and executed source are retained; raw data remain local. Previous evidence/defaults are unchanged. No publication, submission, push or fabrication occurred.
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
                for k in [
                    "complete",
                    "actual_stop_s",
                    "failure",
                    "small_signal",
                    "diagnostic_checks",
                ]
            },
            indent=2,
        )
    )
    return result


if __name__ == "__main__":
    run()
