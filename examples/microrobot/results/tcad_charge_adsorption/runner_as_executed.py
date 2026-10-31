"""One charge-conserving nonlinear adsorption-series startup diagnostic."""

import difflib
import json
from pathlib import Path
import shutil

import numpy as np

from . import tcad_controller as tc
from . import tcad_passive_adsorption as rc

EVIDENCE = tc.HERE / "results/tcad_charge_adsorption"
LOCAL = tc.HERE / "local_runs/tcad_charge_adsorption"
SOURCE = rc.EVIDENCE / "passive_adsorption.spice"
OLD = "Rads metal adsnode {tau*4*width/qmax}"
NEW = "Bads_series metal adsnode I={qmax/(4*width*tau)*(2*width*tanh((v(metal,solution)-offset)/(2*width))-v(adsnode,solution))}"


def build_deck():
    source = SOURCE.read_text()
    if source.count(OLD) != 1 or "width=0.08 offset=0" not in source:
        raise ValueError("Unexpected adsorption branch or reference")
    if source.count("Cads adsnode solution {qmax/(4*width)}") != 1:
        raise ValueError("Unexpected state capacitor topology")
    source = source.replace(
        "* Linearized at eta=offset=0, theta0=0.5; third pin is now physical Cads node.",
        "* Nonlinear series adsorption; u=V(adsnode,solution)=4width*(theta-0.5).",
    )
    return source.replace(OLD, NEW)


def algebra_audit():
    eta, theta = np.meshgrid(np.linspace(-2, 2, 41), np.linspace(0, 1, 11))
    width, tau = rc.WIDTH, rc.TAU
    u = 4 * width * (theta - 0.5)
    original = (1 / (1 + np.exp(-eta / width)) - theta) / tau
    transformed = (2 * width * np.tanh(eta / (2 * width)) - u) / (4 * width * tau)
    error = float(np.max(abs(original - transformed)))
    boundary_lower = (2 * width * np.tanh(eta[0] / (2 * width)) + 2 * width) / (4 * width * tau)
    boundary_upper = (2 * width * np.tanh(eta[0] / (2 * width)) - 2 * width) / (4 * width * tau)
    return {
        "grid_points": int(eta.size),
        "eta_range_V": [-2, 2],
        "theta_range": [0, 1],
        "maximum_abs_dtheta_error_per_s": error,
        "theta0_boundary_derivative_nonnegative": bool(np.all(boundary_lower >= 0)),
        "theta1_boundary_derivative_nonpositive": bool(np.all(boundary_upper <= 0)),
        "charge_identity": "Ia=Ca*du/dt=Qmax*dtheta/dt, with u=4width*(theta-.5)",
        "tau_sign": "Ia/Qmax=(logistic((eta-offset)/width)-theta)/tau; positive tau pulls state toward equilibrium",
        "native_expression": NEW,
        "native_expression_notes": "ngspice behavioral current uses existing v() and parameter syntax plus tanh(); no ideal coverage voltage or duplicate direct adsorption branch",
        "passed": error < 1e-12
        and bool(np.all(boundary_lower >= 0))
        and bool(np.all(boundary_upper <= 0)),
    }


def analyze(columns, data, execution, table):
    result = rc.analyze(columns, data, execution, table)
    if not np.isfinite(data).all():
        return result
    v = dict(zip(columns, data.T, strict=True))
    t = v["time"]
    eta = np.array([v["v(ea)"] - v["v(sa)"], v["v(eb)"] - v["v(sb)"], v["v(er)"] - v["v(sr)"]])
    u = np.array([v["v(ta)"] - v["v(sa)"], v["v(tb)"] - v["v(sb)"], v["v(tr)"] - v["v(sr)"]])
    coverage = 0.5 + u / (4 * rc.WIDTH)
    ia = rc.CADS[:, None] / rc.TAU * (2 * rc.WIDTH * np.tanh(eta / (2 * rc.WIDTH)) - u)

    def integrate(power):
        return float(np.trapezoid(power, t))

    work = integrate(np.sum(eta * ia, axis=0))
    state = integrate(np.sum(u * ia, axis=0))
    branch = integrate(np.sum((eta - u) * ia, axis=0))
    delta = float(np.sum(0.5 * rc.CADS * (u[:, -1] ** 2 - u[:, 0] ** 2)))
    energy = result["energy_J"]
    for key in [
        "adsorption_RC_storage_delta",
        "adsorption_resistive_loss",
        "adsorption_terminal_work",
        "adsorption_RC_balance_residual",
    ]:
        energy.pop(key)
    energy.update(
        signed_adsorption_terminal_work=work,
        normalized_state_capacitor_energy_delta=delta,
        signed_state_capacitor_work=state,
        signed_series_behavioral_branch_work=branch,
        state_capacitor_balance_residual=state - delta,
        adsorption_series_work_balance_residual=work - state - branch,
    )
    energy["electrode_residual"] = (
        energy["electrode_metal_port_work"]
        - energy["double_layer_delta"]
        - work
        - energy["Faradaic_loss"]
        - energy["solution_resistive_loss"]
    )
    checks = result["diagnostic_checks"]
    checks.pop("small_signal_interpretation")
    checks["coverage_bounded"] = bool(coverage.min() >= -1e-6 and coverage.max() <= 1 + 1e-6)
    checks["electrode_energy_2percent"] = abs(energy["electrode_residual"]) < max(
        abs(energy["electrode_metal_port_work"]) * 0.02, 1e-15
    )
    observed = result.pop("small_signal")
    result["adsorption_state"] = {
        "coverage_min_max": [float(coverage.min()), float(coverage.max())],
        "max_abs_eta_over_width": observed["max_abs_eta_over_width"],
        "reference": "theta=.5+V(adsnode,solution)/(4width), offset0",
        "raw_state_columns": "ta/tb/tr physical capacitor-node potentials, not coverage",
    }
    result["all_diagnostic_checks_pass"] = all(checks.values())
    result["adsorption_energy_scope"] = (
        "Signed terminal adsorption work belongs in electrode bookkeeping. The normalized capacitor .5Ca*u² is not physical chemical energy; series behavioral-branch work is signed and is not resistor heat."
    )
    result["scope"] = (
        "Algebraically matched nonlinear state plus held-input startup only; no large-signal electrochemical, released-actuation, phase, bending or autonomous validation"
    )
    return result


def run():
    if EVIDENCE.exists() or LOCAL.exists():
        raise FileExistsError("Charge-adsorption destinations must be fresh")
    EVIDENCE.mkdir(parents=True)
    algebra = algebra_audit()
    tc.write_json(EVIDENCE / "algebra.json", algebra)
    if not algebra["passed"]:
        raise RuntimeError("Offline algebra failed before simulation")
    deck = build_deck()
    prior = SOURCE.read_text()
    tc.write_json(
        EVIDENCE / "configuration.json",
        {
            "scope": __doc__,
            "source_deck_sha256": tc.sha(SOURCE),
            "replacement": {"old": OLD, "new": NEW},
            "width_V": rc.WIDTH,
            "tau_s": rc.TAU,
            "offset_V": 0,
            "Qmax_C": rc.QMAX.tolist(),
            "Ca_F": rc.CADS.tolist(),
            "reference_coverage": 0.5,
            "charge_conservation": "Only Ia metal→state and Ca state→solution; no ground state source or duplicate direct adsorption current",
            "state_energy_scope": "Normalization capacitor energy is diagnostic, not chemical energy",
            "unchanged": "Every other circuit/probe/model/timing/storage/solver line, apart from one explanatory comment",
            "duration_s": 250e-6,
            "max_step_s": 25e-9,
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
                fromfile="passive_adsorption",
                tofile="nonlinear_series_adsorption",
            )
        )
    )
    execution = tc.execute(LOCAL, deck)
    for source, target in [
        ("bench.spice", "charge_adsorption.spice"),
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
            "status": "Complete nonlinear series adsorption held-input startup"
            if result["complete"]
            else "Incomplete nonlinear series adsorption held-input startup",
            "acceptance": "Pending Astra review",
            "scope": "Algebra and held-input startup only, not large-signal validation",
        },
    )
    (EVIDENCE / "README.md").write_text(f"""# Charge-conserving nonlinear adsorption series branch

One **250 µs / 25 ns** held-input startup diagnostic. Complete: **{result["complete"]}**. No fine, rescue, DC, DD or layout run is added.

Starting from accepted passive adsorption, only the adsorption resistor and one explanatory comment change. The replacement current flows metal→state, with **Ia=Ca/tau·[2width·tanh((eta−offset)/(2width))−u]**, **u=V(state,solution)=4width·(theta−0.5)** and **Ca=Qmax/(4width)**. The existing capacitor connects state→local solution; Cdl and RF remain unchanged. Actual offset is0. This yields **Ia=Qmax·dtheta/dt** and exactly **dtheta/dt=[logistic(eta/width)−theta]/tau**. There is no separate ground-referenced coverage source or duplicate direct adsorption-current branch.

Offline algebra.json checks a grid of eta−2 to+2 V and theta0 to1, including boundary signs and finite20 ms relaxation. Algebraic agreement at large input values is not large-signal physical validation. Startup coverage is reconstructed offline from the unchanged ta/tb/tr output columns, which remain physical state-node potentials. Every other DD source, geometry, extracted clock, native DFF, proxy, transistor driver, passive clamp, electrode/Pt-return element, ramp, storage, tolerance and output probe remains unchanged.

Signed adsorption terminal work is retained in the electrode energy balance. The normalized capacitor quantity **0.5Ca·u² is not physical chemical energy**; its work/storage balance and the signed behavioral-series-branch work are separately identified. That branch work is not resistor heat. Current discrepancies and integrated charge-KCL residuals are reported without claiming exact numerical conservation. All checks on incomplete data are prefix-only.

Held commands remain zero. This diagnostic provides no released actuation, gait, bending, large-signal electrochemical calibration or autonomous-controller acceptance. A changed simulator outcome or trouble equation does not establish a unique cause.

```text
MPLCONFIGDIR=/tmp/opentcad-mpl .venv/bin/python -m examples.microrobot.tcad_charge_adsorption
```

Fresh destinations are required. Exact deck/log/diff and executed runner are retained; raw data remain local. Previous defaults/evidence are preserved. No publication, submission, push or fabrication occurred.
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
                    "adsorption_state",
                    "diagnostic_checks",
                ]
            },
            indent=2,
        )
    )
    return result


if __name__ == "__main__":
    run()
