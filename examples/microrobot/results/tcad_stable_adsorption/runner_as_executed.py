"""One stable nonlinear adsorption-expression held-input diagnostic."""

from decimal import Decimal, localcontext
import difflib
import json
import math
from pathlib import Path
import shutil

import numpy as np

from . import tcad_controller as tc
from . import tcad_charge_adsorption as charge
from . import tcad_passive_adsorption as rc

EVIDENCE = tc.HERE / "results/tcad_stable_adsorption"
LOCAL = tc.HERE / "local_runs/tcad_stable_adsorption"
SOURCE = tc.HERE / "results/tcad_linear_bads/linear_bads.spice"
CROSSOVER = 1e-3
OLD = "Bads_linear metal adsnode I={qmax/(4*width*tau)*v(metal,adsnode)}"
FUNCTION = ".func ads_c(z) {abs(z)<1e-3 ? -z*z*z*(1/3-z*z*(2/15-z*z*17/315)) : tanh(z)-z}"
NEW = "Bads_stable metal adsnode I={qmax/(4*width*tau)*(v(metal,adsnode)-offset+2*width*ads_c((v(metal,solution)-offset)/(2*width)))}"


def correction(z):
    return (
        -z * z * z * (1 / 3 - z * z * (2 / 15 - z * z * 17 / 315))
        if abs(z) < CROSSOVER
        else math.tanh(z) - z
    )


def correction_derivative(z):
    return (
        -z * z + (2 / 3) * z**4 - (17 / 45) * z**6
        if abs(z) < CROSSOVER
        else (1 - math.tanh(z) ** 2) - 1
    )


def build_deck():
    source = SOURCE.read_text()
    if source.count(OLD) != 1 or source.count(".subckt micro_electrode ") != 1:
        raise ValueError("Unexpected source deck")
    return source.replace(OLD, NEW).replace(
        ".subckt micro_electrode ", FUNCTION + "\n.subckt micro_electrode ", 1
    )


def offline_audit():
    with localcontext() as context:
        context.prec = 80
        D = Decimal
        # tanh^(n)(z)=P_n(tanh z), P_(n+1)=(1-t²)P'_n.
        poly = [0, 1]
        for _ in range(9):
            derivative = [(i + 1) * poly[i + 1] for i in range(len(poly) - 1)]
            nxt = derivative + [0, 0]
            for i, value in enumerate(derivative):
                nxt[i + 2] -= value
            poly = nxt
        r = D("0.001")
        bound9 = sum(D(abs(value)) * r**power for power, value in enumerate(poly))
        c_bound = bound9 * r**9 / D(math.factorial(9))
        cp_bound = bound9 * r**8 / D(math.factorial(8))
        remainder = derivative_remainder = D(0)
        for i in range(101):
            z = r * D(i) / 100
            e = (2 * z).exp()
            tanh = (e - 1) / (e + 1)
            p = -(z**3) / 3 + 2 * z**5 / 15 - 17 * z**7 / 315
            dp = -(z**2) + 2 * z**4 / 3 - 17 * z**6 / 45
            remainder = max(remainder, abs(tanh - z - p))
            derivative_remainder = max(derivative_remainder, abs(-(tanh**2) - dp))
        zs = [
            -20,
            -5,
            -1,
            -0.01,
            -CROSSOVER * (1 + 1e-8),
            -CROSSOVER,
            -CROSSOVER * (1 - 1e-8),
            -1e-6,
            -1e-12,
            0,
            1e-12,
            1e-6,
            CROSSOVER * (1 - 1e-8),
            CROSSOVER,
            CROSSOVER * (1 + 1e-8),
            0.01,
            1,
            5,
            20,
        ]
        current_error = partial_error = tau_error = 0.0
        count = 0
        boundary_ok = True
        for q in [260e-12, 2600e-12]:
            dq = D(str(q))
            dw = D("0.08")
            dt = D("0.02")
            dg = dq / (4 * dw * dt)
            g = q / (4 * 0.08 * 0.02)
            for offset in [-0.1, 0, 0.05]:
                for solution in [0, 0.93]:
                    for theta in [0, 0.5, 1]:
                        for z_requested in zs:
                            metal = solution + offset + 2 * 0.08 * z_requested
                            state = solution + 4 * 0.08 * (theta - 0.5)
                            dm, ds, dx, do = (
                                D.from_float(x) for x in [metal, solution, state, offset]
                            )
                            dz = (dm - ds - do) / (2 * dw)
                            exp = (2 * dz).exp()
                            tanh = (exp - 1) / (exp + 1)
                            target = (1 + tanh) / 2
                            dtheta = D(".5") + (dx - ds) / (4 * dw)
                            reference = dq / dt * (target - dtheta)
                            z = (metal - solution - offset) / (0.16)
                            value = g * (metal - state - offset + 0.16 * correction(z))
                            cp = correction_derivative(z)
                            partials = [g * (1 + cp), -g * cp, -g, -g * (1 + cp)]
                            refs = [
                                dg * (1 - tanh * tanh),
                                dg * tanh * tanh,
                                -dg,
                                -dg * (1 - tanh * tanh),
                            ]
                            current_error = max(
                                current_error, float(abs(D.from_float(value) - reference))
                            )
                            partial_error = max(
                                partial_error,
                                max(
                                    float(abs(D.from_float(a) - b)) for a, b in zip(partials, refs)
                                ),
                            )
                            tau_error = max(
                                tau_error, float(abs(D.from_float(-value / 0.02) + reference / dt))
                            )
                            count += 1
                            if (
                                theta == 0
                                and reference < D("-1e-21")
                                or theta == 1
                                and reference > D("1e-21")
                            ):
                                boundary_ok = False
        polynomial_at_r = -(CROSSOVER**3) * (
            1 / 3 - CROSSOVER**2 * (2 / 15 - CROSSOVER**2 * 17 / 315)
        )
        derivative_at_r = -(CROSSOVER**2) + 2 * CROSSOVER**4 / 3 - 17 * CROSSOVER**6 / 45
        return {
            "precision_decimal_digits": 80,
            "grid_cases": count,
            "z_values": zs,
            "offsets_V": [-0.1, 0, 0.05],
            "coverage_grid": [0, 0.5, 1],
            "solution_common_modes_V": [0, 0.93],
            "max_current_error_A": current_error,
            "max_voltage_offset_partial_error_A_per_V": partial_error,
            "max_tau_partial_error_A_per_s": tau_error,
            "partials_checked": ["metal", "solution", "state", "offset", "tau"],
            "crossover": CROSSOVER,
            "ninth_derivative_polynomial_coefficients": poly,
            "uniform_remainder_derivation": "|tanh z|<=|z|; tanh^(9)=P9(tanh z), so M9=sum|P9k|r^k. Taylor through degree8 bounds c-p7 by M9*r^9/9! and cprime-p7prime by M9*r^8/8!. Floating arithmetic has separately measured error.",
            "uniform_c_remainder_bound": str(c_bound),
            "uniform_cprime_remainder_bound": str(cp_bound),
            "high_precision_sample_max_c_remainder": str(remainder),
            "high_precision_sample_max_cprime_remainder": str(derivative_remainder),
            "float_c_switch_gap": abs(math.tanh(CROSSOVER) - CROSSOVER - polynomial_at_r),
            "float_cprime_switch_gap": abs(((1 - math.tanh(CROSSOVER) ** 2) - 1) - derivative_at_r),
            "boundary_signs_pass": boundary_ok,
            "partial_method": "Symbolic piecewise-expression voltage/offset partials in float64, including outside-branch subtraction; native automatic derivatives are not separately instrumented",
            "native_syntax": "ngspice .func, abs, ternary, multiplication and tanh; no extra native preflight run",
            "passed": current_error < 5e-21
            and partial_error < 5e-21
            and tau_error < 5e-19
            and remainder <= c_bound
            and derivative_remainder <= cp_bound
            and boundary_ok,
        }


def analyze(columns, data, execution, table):
    result = charge.analyze(columns, data, execution, table)
    if not np.isfinite(data).all():
        return result
    v = dict(zip(columns, data.T, strict=True))
    t = v["time"]
    metal = np.array([v["v(ea)"], v["v(eb)"], v["v(er)"]])
    solution = np.array([v["v(sa)"], v["v(sb)"], v["v(sr)"]])
    state = np.array([v["v(ta)"], v["v(tb)"], v["v(tr)"]])
    eta = metal - solution
    u = state - solution
    z = eta / (2 * rc.WIDTH)
    c = np.array([[correction(float(x)) for x in row] for row in z])
    ia = rc.CADS[:, None] / rc.TAU * (metal - state + 2 * rc.WIDTH * c)

    def integrate(power):
        return float(np.trapezoid(power, t))

    energy = result["energy_J"]
    work = integrate(np.sum(eta * ia, axis=0))
    state_work = integrate(np.sum(u * ia, axis=0))
    branch = integrate(np.sum((metal - state) * ia, axis=0))
    energy.update(
        signed_adsorption_terminal_work=work,
        signed_state_capacitor_work=state_work,
        signed_series_behavioral_branch_work=branch,
        state_capacitor_balance_residual=state_work
        - energy["normalized_state_capacitor_energy_delta"],
        adsorption_series_work_balance_residual=work - state_work - branch,
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
    result["diagnostic_checks"]["startup_small_signal"] = (
        result["adsorption_state"]["max_abs_eta_over_width"] < 0.01
    )
    result["all_diagnostic_checks_pass"] = all(result["diagnostic_checks"].values())
    result["scope"] = (
        "Bounded-approximation nonlinear expression and held-input startup only; no released or large-signal physical validation"
    )
    return result


def run():
    if EVIDENCE.exists() or LOCAL.exists():
        raise FileExistsError("Stable-adsorption destinations must be fresh")
    EVIDENCE.mkdir(parents=True)
    audit = offline_audit()
    tc.write_json(EVIDENCE / "offline_checks.json", audit)
    if not audit["passed"]:
        raise RuntimeError("Offline precision/derivative/remainder checks failed; no transient run")
    prior = SOURCE.read_text()
    deck = build_deck()
    tc.write_json(
        EVIDENCE / "configuration.json",
        {
            "scope": __doc__,
            "source_deck_sha256": tc.sha(SOURCE),
            "law": NEW,
            "correction_function": FUNCTION,
            "actual_offset_V": 0,
            "crossover": CROSSOVER,
            "approximation": "Degree7 correction inside; tanh(z)-z outside, with explicit Taylor remainder and floating audit bounds",
            "unchanged": "Every other circuit, model, probe, storage, source, held input, tolerance and timing line",
            "duration_s": 250e-6,
            "max_step_s": 25e-9,
            "energy_limit": "Normalized capacitor energy is not chemical energy; behavioral branch work is signed, not resistor heat",
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
                fromfile="accepted_linear_B",
                tofile="stable_nonlinear_B",
            )
        )
    )
    execution = tc.execute(LOCAL, deck)
    for source, target in [
        ("bench.spice", "stable_adsorption.spice"),
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
            "status": "Complete stable nonlinear held-input startup"
            if result["complete"]
            else "Incomplete stable nonlinear held-input startup",
            "acceptance": "Pending Astra review",
            "limit": "No unique cause, simulator-defect, large-signal physical or released-actuation conclusion",
        },
    )
    (EVIDENCE / "README.md").write_text(f"""# Stable nonlinear adsorption correction

One **250 µs / 25 ns** held-input diagnostic. Complete: **{result["complete"]}**. No repeat, fine, rescue, DC, DD or layout run is added.

Starting from accepted linear B, only its adsorption current expression and one explicit `.func` change. With g=Qmax/(4width·tau), the law is **Ia=g·[V(metal,state)−offset+2width·c(z)]**, **z=(V(metal,solution)−offset)/(2width)**. Outside|z|<10⁻³, c=tanh(z)−z; inside it uses **−z³/3+2z⁵/15−17z⁷/315**. This bounded approximation avoids forming the near-equal linear terms in the principal metal-to-state current; it is not claimed exact. Ca, Cdl, RF and all surrounding circuitry/probes/timing are unchanged.

Offline Decimal80-digit checks cover crossover neighbors on both sides, zero, large eta, theta0/0.5/1, nonzero offsets and common modes. Current and metal/solution/state/offset/tau partials are compared with the original logistic-state reference. Taylor remainder bounds follow the derivative recurrence P(n+1)=(1−t²)P'n and |tanh(z)|≤|z|; offline_checks.json records bounds and floating error separately. Native automatic derivatives are not separately instrumented. The sole startup run is the only native syntax/execution check.

Signed adsorption terminal work is retained. Normalized0.5Ca·u² is not chemical energy, and signed behavioral-branch work is not resistor heat. Coverage is recovered offline from physical state-to-solution voltage. Current discrepancies remain explicit; no exact numerical-conservation claim is made. Incomplete traces support prefix checks only. No released actuation, phase, bending, large-signal electrochemical or autonomous validation follows, and changed execution does not establish a unique cause.

```text
MPLCONFIGDIR=/tmp/opentcad-mpl .venv/bin/python -m examples.microrobot.tcad_stable_adsorption
```

Fresh destinations are required. Exact deck/diff/log, precision checks and executed runner are retained; raw data remain local. Prior evidence/defaults are unchanged. No submission, publication, push or fabrication occurred.
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
