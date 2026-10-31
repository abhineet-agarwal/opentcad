"""Separate candidate terminal fits to supplied Reynolds S2E PV observations.

The historical raster fit and application defaults are never changed. Fit-only
training regions, equal occupied voltage bins and additive observation-offset
hypotheses are explicit; no physical TCAD or temperature calibration is implied.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path

import numpy as np
from scipy.optimize import least_squares

from examples.microrobot.reynolds_data import load_dataset, terminal_current_A
from opentcad.device.compact import SingleDiodePV

HOLDOUT_REGIONS = ((0.90, 1.05), (1.15, 1.25))
BIN_WIDTHS_V = (0.025, 0.0125, 0.050)
OFFSET_MODES = ("zero", "shared_fit", "fixed_dark_median")
CURRENT_SCALE_A = 1e-9  # Numerical residual scale, not measurement uncertainty.
PARAMETER_BOUNDS = {
    "saturation_A": [1e-30, 1e-6],
    "ideality": [0.5, 4.0],
    "photocurrent_A": [1e-12, 1e-5],
    "shared_offset_A": [-10e-9, 10e-9],
}


@dataclass(frozen=True)
class IVBranch:
    name: str
    voltage_V: np.ndarray
    entering_A: np.ndarray
    irradiance_W_m2: float

    def __post_init__(self):
        v, i = np.asarray(self.voltage_V), np.asarray(self.entering_A)
        if (
            v.ndim != 1
            or i.shape != v.shape
            or not len(v)
            or not np.all(np.isfinite(v))
            or not np.all(np.isfinite(i))
        ):
            raise ValueError(
                "Equal nonempty finite one-dimensional voltage/current arrays required"
            )
        if self.irradiance_W_m2 not in (0.0, 1000.0):
            raise ValueError("S2E branches must be dark or 1000 W/m2")


def heldout_mask(voltage_V):
    """Predeclared voltage-only split; lower-inclusive, upper-exclusive."""
    v = np.asarray(voltage_V)
    mask = np.zeros(v.shape, dtype=bool)
    for lower, upper in HOLDOUT_REGIONS:
        mask |= (v >= lower) & (v < upper)
    return mask


def occupied_bin_weights(voltage_V, width_V):
    """Point weights whose weighted MSE gives each occupied bin equal weight.

    Bins are [k*width, (k+1)*width), anchored at 0 V, including negative k.
    The mathematical weights, not bin-averaged observations, enter the objective.
    """
    v = np.asarray(voltage_V, dtype=float)
    if (
        v.ndim != 1
        or not len(v)
        or not np.all(np.isfinite(v))
        or not np.isfinite(width_V)
        or width_V <= 0
    ):
        raise ValueError("Finite nonempty 1D voltages and positive finite bin width required")
    bins = np.floor(v / width_V).astype(np.int64)
    unique, inverse, counts = np.unique(bins, return_inverse=True, return_counts=True)
    return 1.0 / (len(unique) * counts[inverse]), len(unique)


def entering_prediction(model, voltage_V, irradiance_W_m2, offset_A=0.0):
    """Observation model: device entering current plus one constant offset."""
    return -model.current_A(voltage_V, irradiance_W_m2) + offset_A


def training_branches(branches):
    if len(branches) != 2 or {b.irradiance_W_m2 for b in branches} != {0.0, 1000.0}:
        raise ValueError("Joint dark and one-sun branches required for offset identifiability")
    if len({b.name for b in branches}) != 2:
        raise ValueError("Branch names must be unique")
    result = []
    for b in branches:
        mask = ~heldout_mask(b.voltage_V)
        if np.sum(mask) < 6 or not np.any(b.voltage_V[mask] > 1.25):
            raise ValueError(
                "Each branch needs training observations including forward region >1.25 V"
            )
        result.append(IVBranch(b.name, b.voltage_V[mask], b.entering_A[mask], b.irradiance_W_m2))
    return result


def fit_candidate(branches, *, bin_width_V=0.025, offset_mode="zero"):
    """Fit training points only. Held-out currents never enter seeds or scales."""
    train = training_branches(branches)
    if offset_mode not in OFFSET_MODES:
        raise ValueError("Unknown offset hypothesis")
    dark = next(b for b in train if b.irradiance_W_m2 == 0)
    near = np.abs(dark.voltage_V) < 0.01
    if offset_mode == "fixed_dark_median" and not np.any(near):
        raise ValueError("Fixed dark offset requires training samples at |V|<0.01 V")
    fixed_offset = (
        float(np.median(dark.entering_A[near])) if offset_mode == "fixed_dark_median" else 0.0
    )
    weights = [occupied_bin_weights(b.voltage_V, bin_width_V) for b in train]
    root_weights = [np.sqrt(w / len(train)) / CURRENT_SCALE_A for w, _ in weights]
    v = np.concatenate([b.voltage_V for b in train])
    measured = np.concatenate([b.entering_A for b in train])
    light = np.concatenate([np.full(len(b.voltage_V), b.irradiance_W_m2) for b in train])
    root_weight = np.concatenate(root_weights)
    low = np.log([PARAMETER_BOUNDS[k][0] for k in ("saturation_A", "ideality", "photocurrent_A")])
    high = np.log([PARAMETER_BOUNDS[k][1] for k in ("saturation_A", "ideality", "photocurrent_A")])
    if offset_mode == "shared_fit":
        low, high = np.r_[low, -10.0], np.r_[high, 10.0]  # Offset optimization unit is nA.

    def unpack(x):
        i0, ideality, iph = np.exp(x[:3])
        model = SingleDiodePV(i0, ideality, iph, series_cells=2, temperature_K=300.0)
        return model, float(x[3] * CURRENT_SCALE_A) if offset_mode == "shared_fit" else fixed_offset

    def residual(x):
        model, offset = unpack(x)
        return (entering_prediction(model, v, light, offset) - measured) * root_weight

    illuminated = next(b for b in train if b.irradiance_W_m2 == 1000)
    low_v = np.abs(illuminated.voltage_V) < 0.05
    estimate = (
        -float(np.median(illuminated.entering_A[low_v]))
        if np.any(low_v)
        else -float(np.min(illuminated.entering_A))
    )
    iph_guess = np.clip(estimate + fixed_offset, 1e-11, 1e-6)
    forward = int(np.argmax(v))
    forward_current = max(float(measured[forward]) + iph_guess * light[forward] / 1000, 1e-9)
    starts = []
    for n in (0.8, 1.2, 2.0):
        a = SingleDiodePV(1e-16, n, iph_guess, series_cells=2).diode_voltage_V
        i0 = np.clip(forward_current / np.expm1(v[forward] / a), 1e-29, 1e-7)
        seed = np.log([i0, n, iph_guess])
        if offset_mode == "shared_fit":
            seed = np.r_[seed, 0.0]
        fit = least_squares(
            residual,
            seed,
            bounds=(low, high),
            x_scale="jac",
            loss="linear",
            max_nfev=1000,
            ftol=1e-12,
            xtol=1e-12,
            gtol=1e-10,
        )
        starts.append(fit)
    successful = [f for f in starts if f.success and np.all(np.isfinite(f.fun))]
    if not successful:
        raise RuntimeError("No deterministic training multistart converged")
    best = min(successful, key=lambda f: np.dot(f.fun, f.fun))
    model, offset = unpack(best.x)
    return (
        model,
        offset,
        {
            "bin_width_V": bin_width_V,
            "offset_mode": offset_mode,
            "fitted_on": "Training only; no all-data refit or holdout-based hypothesis selection",
            "model": asdict(model),
            "shared_entering_observation_offset_A": offset,
            "offset_role": "Observation hypothesis, excluded from device-only Voc/MPP; no source correction applied",
            "device_only_Voc_1sun_V": model.open_circuit_V(),
            "device_only_MPP_1sun_V_A_W": list(model.maximum_power_point()),
            "objective_dimensionless": float(np.dot(best.fun, best.fun)),
            "training_equal_branch_bin_rms_A": float(
                np.sqrt(np.dot(best.fun, best.fun)) * CURRENT_SCALE_A
            ),
            "training_counts": {
                b.name: {"points": len(b.voltage_V), "occupied_bins": n}
                for b, (_, n) in zip(train, weights)
            },
            "optimizer": {
                "method": "scipy.optimize.least_squares; linear loss; log positive parameters; offset in nA",
                "parameter_bounds": PARAMETER_BOUNDS,
                "multistarts": [
                    {
                        "success": bool(f.success),
                        "status": int(f.status),
                        "evaluations": int(f.nfev),
                        "objective": float(np.dot(f.fun, f.fun)),
                        "message": str(f.message),
                    }
                    for f in starts
                ],
                "chosen_active_mask": best.active_mask.tolist(),
                "chosen_optimality": float(best.optimality),
                "chosen_jacobian_rank": int(np.linalg.matrix_rank(best.jac)),
            },
        },
    )


def _errors(residual, voltage, width):
    if not len(residual):
        return {
            "points": 0,
            "occupied_bins": 0,
            "rms_A": None,
            "mae_A": None,
            "bias_A": None,
            "max_abs_A": None,
            "equal_bin_rms_A": None,
        }
    weights, count = occupied_bin_weights(voltage, width)
    return {
        "points": len(residual),
        "occupied_bins": count,
        "rms_A": float(np.sqrt(np.mean(residual**2))),
        "mae_A": float(np.mean(np.abs(residual))),
        "bias_A": float(np.mean(residual)),
        "max_abs_A": float(np.max(np.abs(residual))),
        "equal_bin_rms_A": float(np.sqrt(np.sum(weights * residual**2))),
    }


def evaluation_masks(voltage):
    return {
        "train": ~heldout_mask(voltage),
        "heldout_combined": heldout_mask(voltage),
        **{
            f"heldout_{lower:.2f}_{upper:.2f}V": (voltage >= lower) & (voltage < upper)
            for lower, upper in HOLDOUT_REGIONS
        },
        "all_diagnostic": np.ones(len(voltage), dtype=bool),
    }


def evaluate(branches, model, offset_A, *, bin_width_V=0.025):
    """Residual = predicted entering current minus unchanged measured entering current."""
    by_branch = {}
    arrays = {}
    for b in branches:
        residual = (
            entering_prediction(model, b.voltage_V, b.irradiance_W_m2, offset_A) - b.entering_A
        )
        arrays[b.name] = (b, residual)
        by_branch[b.name] = {
            name: _errors(residual[mask], b.voltage_V[mask], bin_width_V)
            for name, mask in evaluation_masks(b.voltage_V).items()
        }
    aggregate = {}
    for name in next(iter(by_branch.values())):
        residuals = [r[evaluation_masks(b.voltage_V)[name]] for b, r in arrays.values()]
        flat = np.concatenate(residuals)
        branch_errors = [by_branch[b.name][name] for b in branches]
        valid = [e for e in branch_errors if e["points"]]
        aggregate[name] = {
            "points": len(flat),
            "rms_A": float(np.sqrt(np.mean(flat**2))) if len(flat) else None,
            "mae_A": float(np.mean(np.abs(flat))) if len(flat) else None,
            "bias_A": float(np.mean(flat)) if len(flat) else None,
            "max_abs_A": float(np.max(np.abs(flat))) if len(flat) else None,
            "equal_branch_bin_rms_A": float(
                np.sqrt(np.mean([e["equal_bin_rms_A"] ** 2 for e in valid]))
            )
            if valid
            else None,
        }
    return {"bin_width_V": bin_width_V, "branches": by_branch, "aggregate": aggregate}


def _plots(branches, historical, candidates, output):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(2, 2, figsize=(12, 8), layout="constrained")
    for col, b in enumerate(branches):
        v = np.linspace(min(b.voltage_V), max(b.voltage_V), 800)
        axes[0, col].scatter(
            b.voltage_V,
            b.entering_A * 1e9,
            s=2,
            alpha=0.15,
            color="black",
            label="Supplied observations",
        )
        for label, model, offset in [("Frozen raster fit", historical, 0.0), *candidates]:
            axes[0, col].plot(
                v, entering_prediction(model, v, b.irradiance_W_m2, offset) * 1e9, label=label
            )
            error = (
                entering_prediction(model, b.voltage_V, b.irradiance_W_m2, offset) - b.entering_A
            )
            axes[1, col].scatter(b.voltage_V, error * 1e9, s=2, alpha=0.22, label=label)
        for row in range(2):
            ax = axes[row, col]
            for lo, hi in HOLDOUT_REGIONS:
                ax.axvspan(lo, hi, color="gold", alpha=0.2)
            ax.set(
                xlabel="Pair voltage (V)",
                ylabel="Entering current (nA)" if row == 0 else "Model − measured (nA)",
            )
            ax.grid(alpha=0.2)
        axes[0, col].set_title(b.name + "; yellow bands withheld from fitting")
        axes[0, col].legend(fontsize=8)
    fig.suptitle(
        "Training-only effective pair candidates; 300 K assumed; offset hypotheses retained"
    )
    fig.savefig(output / "pv_candidates_and_residuals.png", dpi=160)
    plt.close(fig)


def _readme(report):
    lines = [
        "# Separate Reynolds S2E candidate fits",
        "",
        "Training-only ideal single-diode effective pair candidates; application defaults and historical fit unchanged.",
        "",
        "300 K is assumed, not measured. Two series cells, each 540 µm², and one sun = 1000 W/m² follow the figure context; no TCAD geometry is calibrated.",
        "",
        "Holdout regions [0.90,1.05) and [1.15,1.25) V were excluded from both branches before any fitting, initialization, scaling or fixed-offset estimation. Both main hypotheses are retained without selecting a winner using holdouts. These are conditional model diagnostics, not an independent final accuracy test.",
        "",
        "Objective: each branch has equal weight; within a branch each occupied voltage bin has equal weight, and native residuals within each bin are averaged in squared current. Bins are anchored at 0 V. The 1 nA residual scale serves numerical conditioning only, not experimental uncertainty. No point sorting, merging, trimming or offset subtraction is applied to observations.",
        "",
        "| Training bin | Offset hypothesis | Offset nA | n (per cell) | Iph nA | Device Voc V | Device Pmax nW | Heldout equal-branch/bin RMS nA |",
        "|---:|---|---:|---:|---:|---:|---:|---:|",
    ]
    for c in report["candidates"]:
        m = c["model"]
        lines.append(
            f"| {c['bin_width_V'] * 1000:g} mV | {c['offset_mode']} | {c['shared_entering_observation_offset_A'] * 1e9:.4f} | {m['ideality']:.6f} | {m['photocurrent_A'] * 1e9:.4f} | {c['device_only_Voc_1sun_V']:.6f} | {c['device_only_MPP_1sun_V_A_W'][2] * 1e9:.4f} | {c['evaluation']['aggregate']['heldout_combined']['equal_branch_bin_rms_A'] * 1e9:.4f} |"
        )
    old = report["historical"]["evaluation"]["aggregate"]["heldout_combined"][
        "equal_branch_bin_rms_A"
    ]
    lines += [
        "",
        f"Frozen historical fit diagnostic on the candidate-heldout regions, equal-branch/bin RMS at 25 mV: {old * 1e9:.4f} nA. Historical model observation offset remains zero. It was fitted to the full plotted raster curve, including these voltages: this is not a holdout-trained baseline or a fairness-controlled benchmark.",
        "",
        "The shared fitted offset is bounded ±10 nA. A third sensitivity hypothesis fixes it to the training dark |V|<0.01 V median; none establishes a true instrument correction. Device Voc/MPP exclude this additive observation offset. Candidate parameter variation across 12.5/25/50 mV bins and offset choices is algorithmic sensitivity, not a confidence interval.",
        "",
        "The single exponential leaves structural residuals, repeated-voltage scatter and possible instrumental effects. No Rs, shunt resistance, breakdown, mismatch, storage, electrochemistry or temperature dependence is inferred. Only n*T is constrained by the exponential slope at fixed series count; assumed T does not produce a unique physical ideality or a calibrated TCAD process. These DC results do not validate circuit transients, logic-PV scaling or robot mechanics.",
        "",
        "Source authorship/archive version/license remain user-reported and unverified. JSON contains source hashes and aggregate fit diagnostics, not raw arrays. No raw files were copied or altered. The old model and application defaults remain unchanged.",
        "",
        "Regenerate into a NEW or empty directory with:",
        "",
        "```sh",
        ".venv/bin/python -m examples.microrobot.reynolds_fit --source-dir /local/Reynolds-2022-data --output /local/new-fit-results",
        "```",
        "",
        "The command refuses nonempty output archives and destinations inside the source directory; no --force option exists.",
    ]
    return "\n".join(lines) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--historical-fit",
        type=Path,
        default=Path(__file__).parent / "results/published/pv_fit.json",
    )
    args = parser.parse_args(argv)
    if args.output.resolve().is_relative_to(args.source_dir.resolve()):
        parser.error("Output must be outside read-only source directory")
    if args.output.exists() and (not args.output.is_dir() or any(args.output.iterdir())):
        parser.error("Output must be a fresh or empty directory; existing archive preserved")
    dataset = load_dataset(args.source_dir)
    raw_old = args.historical_fit.read_bytes()
    historical = SingleDiodePV(**json.loads(raw_old)["fitted_terminal_model"])
    groups = dataset["FigS2_CircuitTesting.csv"].groups
    branches = [
        IVBranch(name, groups[name].values[:, 0], terminal_current_A(groups[name]), light)
        for name, light in (("iv_dark", 0.0), ("iv_1sun", 1000.0))
    ]
    report = {
        "status": "Separate training-only PV candidates; both main hypotheses retained; no application default changes",
        "analysis_code_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "loader_code_sha256": hashlib.sha256(
            (Path(__file__).parent / "reynolds_data.py").read_bytes()
        ).hexdigest(),
        "core_model_code_sha256": hashlib.sha256(
            Path(__import__("opentcad.device.compact", fromlist=["__file__"]).__file__).read_bytes()
        ).hexdigest(),
        "sources": {
            name: {"sha256": f.sha256, "size_bytes": f.size_bytes} for name, f in dataset.items()
        },
        "provenance": "User-supplied local files; claimed Zenodo origin, archive identity and license unverified; no raw arrays copied",
        "model_assumptions": {
            "temperature_K": 300.0,
            "temperature_measured": False,
            "series_cells": 2,
            "each_cell_area_um2": 540,
            "reference_irradiance_W_m2": 1000.0,
            "area_role": "Caption context only; no area scaling fitted",
            "absent": ["Rs", "Rsh", "breakdown", "junction charge", "temperature dependence"],
        },
        "method": {
            "objective": "Equal branch mean of equal occupied voltage-bin mean squared native entering-current residuals divided by (1 nA)^2",
            "bin_origin_V": 0,
            "bin_boundary": "[k*width, (k+1)*width); k=floor(V/width)",
            "residual_scale_A": CURRENT_SCALE_A,
            "scale_is_experimental_sigma": False,
            "main_bin_width_V": 0.025,
            "sensitivity_bin_widths_V": list(BIN_WIDTHS_V),
            "offset_hypotheses": list(OFFSET_MODES),
            "offset_bounds_A": [-1e-8, 1e-8],
            "entering_prediction": "-SingleDiodePV.current_A(V, irradiance) + shared_offset_A",
            "heldout_regions_V": [list(r) for r in HOLDOUT_REGIONS],
            "heldout_boundary": "lower inclusive, upper exclusive",
            "holdout_current_use": "Evaluation only, never optimizer, initial guesses, scales, fixed offset or hypothesis selection",
            "selection": "Both main hypotheses retained; sensitivities not used to select a holdout winner; no all-data refit",
            "native_data": "Original points/order and currents retained; weights only; no sorting, deduplication, normalization or offset subtraction",
            "uncertainty": "No measurement sigma supplied; numerical objective and sensitivity are not confidence intervals or validation guarantees",
        },
        "split_counts": {
            b.name: {name: int(mask.sum()) for name, mask in evaluation_masks(b.voltage_V).items()}
            for b in branches
        },
        "historical": {
            "path": str(args.historical_fit),
            "sha256": hashlib.sha256(raw_old).hexdigest(),
            "model": asdict(historical),
            "observation_offset_A": 0.0,
            "baseline_caveat": "Frozen historical raster fit used full plotted curve including candidate-heldout voltages; not a holdout-trained baseline or fairness-controlled benchmark",
            "evaluation": evaluate(branches, historical, 0.0),
        },
        "candidates": [],
        "limitations": [
            "Effective terminal fit does not identify unique physical TCAD parameters or logic PV scaling",
            "300 K assumed; slope constrains n*T at fixed series count, not measured temperature or unique ideality",
            "Unmodeled structural discrepancy and repeated-voltage scatter remain; offset hypotheses are not established instrument corrections",
            "Device-only Voc/MPP exclude observation offset; no charge, transient, actuator or robot-mechanics calibration",
            "Heldout voltage-region comparisons are conditional diagnostics, not independent final accuracy guarantees",
        ],
    }
    plot_models = []
    for width in BIN_WIDTHS_V:
        for mode in OFFSET_MODES:
            model, offset, result = fit_candidate(branches, bin_width_V=width, offset_mode=mode)
            result["role"] = (
                "main retained hypothesis"
                if width == 0.025 and mode != "fixed_dark_median"
                else "sensitivity only"
            )
            result["evaluation"] = evaluate(branches, model, offset, bin_width_V=width)
            # The same frozen comparator is evaluated at each bin width for fair sensitivity comparisons.
            result["historical_evaluation_same_bin_width"] = evaluate(
                branches, historical, 0.0, bin_width_V=width
            )
            report["candidates"].append(result)
            if result["role"] == "main retained hypothesis":
                plot_models.append((mode + " (25 mV train)", model, offset))
            print(
                json.dumps(
                    {
                        "bin_mV": width * 1000,
                        "offset_mode": mode,
                        "offset_nA": offset * 1e9,
                        "ideality": model.ideality,
                        "heldout_equal_bin_rms_nA": result["evaluation"]["aggregate"][
                            "heldout_combined"
                        ]["equal_branch_bin_rms_A"]
                        * 1e9,
                    }
                ),
                flush=True,
            )
    args.output.mkdir(parents=True, exist_ok=True)
    _plots(branches, historical, plot_models, args.output)
    (args.output / "fit_report.json").write_text(
        json.dumps(report, indent=2, allow_nan=False) + "\n"
    )
    (args.output / "README.md").write_text(_readme(report))
    print(json.dumps({"output": str(args.output), "candidate_fits": len(report["candidates"])}))


if __name__ == "__main__":
    main()
