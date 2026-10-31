"""Single linear behavioral adsorption-current control, with held inputs."""

import difflib
import json
from pathlib import Path
import shutil

import numpy as np

from . import tcad_controller as tc
from . import tcad_passive_adsorption as rc

EVIDENCE = tc.HERE / "results/tcad_linear_bads"
LOCAL = tc.HERE / "local_runs/tcad_linear_bads"
SOURCE = rc.EVIDENCE / "passive_adsorption.spice"
OLD = "Rads metal adsnode {tau*4*width/qmax}"
NEW = "Bads_linear metal adsnode I={qmax/(4*width*tau)*v(metal,adsnode)}"


def build_deck():
    deck = SOURCE.read_text()
    if deck.count(OLD) != 1:
        raise ValueError("Expected one adsorption resistor definition")
    return deck.replace(OLD, NEW)


def analyze(columns, data, execution, table):
    result = rc.analyze(columns, data, execution, table)
    if not np.isfinite(data).all():
        return result
    v = dict(zip(columns, data.T, strict=True))
    t = v["time"]
    drop = np.array([v["v(ea)"] - v["v(ta)"], v["v(eb)"] - v["v(tb)"], v["v(er)"] - v["v(tr)"]])
    eta = np.array([v["v(ea)"] - v["v(sa)"], v["v(eb)"] - v["v(sb)"], v["v(er)"] - v["v(sr)"]])
    current = rc.CADS[:, None] / rc.TAU * drop
    work = float(np.trapezoid(np.sum(eta * current, axis=0), t))
    dissipation = float(np.trapezoid(np.sum(drop * current, axis=0), t))
    energy = result["energy_J"]
    energy.pop("adsorption_resistive_loss")
    energy["linear_B_equivalent_dissipation"] = dissipation
    energy["adsorption_terminal_work"] = work
    energy["adsorption_RC_balance_residual"] = (
        work - energy["adsorption_RC_storage_delta"] - dissipation
    )
    energy["electrode_residual"] = (
        energy["electrode_metal_port_work"]
        - energy["double_layer_delta"]
        - work
        - energy["Faradaic_loss"]
        - energy["solution_resistive_loss"]
    )
    result["diagnostic_checks"]["electrode_energy_2percent"] = abs(
        energy["electrode_residual"]
    ) < max(abs(energy["electrode_metal_port_work"]) * 0.02, 1e-15)
    result["all_diagnostic_checks_pass"] = all(result["diagnostic_checks"].values())
    result["adsorption_energy_scope"] = (
        "Linear B terminal law equals I=V/R, so V*I=V²/R is equivalent nonnegative dissipation in this mathematical RC model; this is not a separately calibrated physical heat device or chemical-energy claim."
    )
    result["scope"] = (
        "Linear behavioral-source held-input control only; no released, nonlinear electrochemical, phase/bending or autonomous validation"
    )
    return result


def run():
    if EVIDENCE.exists() or LOCAL.exists():
        raise FileExistsError("Linear-B destinations must be fresh")
    EVIDENCE.mkdir(parents=True)
    prior = SOURCE.read_text()
    deck = build_deck()
    grid = np.linspace(-2, 2, 41)
    errors = np.max(abs(rc.CADS[:, None] / rc.TAU * grid - grid / rc.RADS[:, None]), axis=1)
    tc.write_json(
        EVIDENCE / "configuration.json",
        {
            "scope": __doc__,
            "source_deck_sha256": tc.sha(SOURCE),
            "exact_replacement": {"old": OLD, "new": NEW},
            "terminal_relation": "I=Qmax/(4width*tau)*V(metal,adsnode)=V/Rads; no nonlinear or common-mode subtraction",
            "voltage_grid_V": [-2, 2],
            "max_current_equivalence_error_A": errors.tolist(),
            "Ca_F": rc.CADS.tolist(),
            "Rads_equivalent_ohm": rc.RADS.tolist(),
            "tau_s": rc.TAU,
            "width_V": rc.WIDTH,
            "energy_interpretation": "Equivalent passive RC bookkeeping under exact terminal-law assumption; behavioral source is not a calibrated physical heat device",
            "unchanged": "All other source/deck/probe/model/timing/storage/solver lines",
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
                fromfile="passed_passive_adsorption",
                tofile="linear_behavioral_adsorption",
            )
        )
    )
    execution = tc.execute(LOCAL, deck)
    for source, target in [
        ("bench.spice", "linear_bads.spice"),
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
            "status": "Complete linear-B held-input startup"
            if result["complete"]
            else "Incomplete linear-B held-input startup",
            "acceptance": "Pending Astra review",
            "limit": "Changed outcome is not proof of a simulator defect or unique cause",
        },
    )
    (EVIDENCE / "README.md").write_text(f"""# Linear behavioral adsorption-current control

Exactly one **250 µs / 25 ns** held-input startup. Complete: **{result["complete"]}**. No fine, rescue, DC, DD or layout run is added.

The passed passive-adsorption deck changes exactly one line: `Rads metal adsnode {{tau*4*width/qmax}}` becomes `Bads_linear metal adsnode I={{qmax/(4*width*tau)*v(metal,adsnode)}}`. Thus the native expression uses the direct metal-to-state voltage and has no nonlinear term or common-mode subtraction. The terminal law is exactly I=V/Rads, with identical model parameters, Cads/Cdl/RF, surrounding circuits, probes, held commands, ramp, storage and solver. The test reverses the single substitution to recover the source deck byte for byte.

Energy uses equivalent RC bookkeeping: the linear behavioral branch gives nonnegative V·I=V²/R, with capacitor storage and terminal work reported separately. This mathematical equivalence is not a claim of a separately calibrated physical heat device or chemical energy. Local current discrepancies remain explicit. Checks on an incomplete trace are prefix-only; no released actuation, phase, bending or autonomous operation is validated. Neither a changed outcome nor a reported trouble equation establishes a unique cause or simulator defect.

```text
MPLCONFIGDIR=/tmp/opentcad-mpl .venv/bin/python -m examples.microrobot.tcad_linear_bads
```

Fresh destinations are required. Exact diff/deck/log and executed source are retained; raw data remain local. Previous evidence/defaults are unchanged. No publication, submission, push or fabrication occurred.
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
