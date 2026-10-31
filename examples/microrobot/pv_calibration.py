"""Bounded direct-DD optical-throughput feasibility check against supplied S2E.

Only effective reflectance may vary. This is not process identification. Run::

    .venv/bin/python -m examples.microrobot.pv_calibration \
        --source-dir /local/Reynolds-2022-data --output /local/new-results

The output must be fresh. Native observations remain read-only and are never
exported as arrays. Two light DD curves are run; a third is permitted only if
the low-bias training target is bracketed by the physical reflectance interval.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import sys
import time

import numpy as np

from .pv import characterize
from .reynolds_data import SCHEMAS, load_file, observed_iv_summary, terminal_current_A
from .reynolds_fit import HOLDOUT_REGIONS, heldout_mask, occupied_bin_weights
from opentcad.device.optical import BeerLambert
from opentcad.device.solver import Q_C

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
BIN_WIDTH_V = 0.025
AREA_UM2 = 540.0
SERIES_CELLS = 2
VOLTAGE_GRID = np.arange(0, 0.70 + 0.025 / 2, 0.025)


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


def prediction(curve, pair_voltage):
    """Entering current of two equal series cells; series count scales V only."""
    v = np.asarray(pair_voltage, dtype=float)
    grid = np.asarray(curve["voltage_V"]) * SERIES_CELLS
    if np.any(~np.isfinite(v)) or np.any(v < grid[0]) or np.any(v > grid[-1]):
        raise ValueError("Pair voltage outside characterized interval; no extrapolation")
    return -AREA_UM2 * np.interp(v, grid, curve["delivered_A_per_um2"])


def low_bias_difference(groups):
    """Equal mean of shared occupied voltage-bin dark-minus-light means.

    Groups are separate acquisitions; CSV row numbers are never paired. Native
    observations and ordering remain intact. A constant shared observation
    offset cancels under this hypothesis. No negative-voltage point is used.
    """
    arrays = {}
    for name in ("iv_dark", "iv_1sun"):
        group = groups[name]
        v, i = group.values[:, 0], terminal_current_A(group)
        arrays[name] = (v, i)
    bins = []
    for k in (0, 1):
        lo, hi = k * BIN_WIDTH_V, (k + 1) * BIN_WIDTH_V
        row = {"interval_V": [lo, hi], "branches": {}}
        for name, (v, i) in arrays.items():
            mask = (v >= lo) & (v < hi)
            if not np.any(mask):
                raise ValueError("Both branches must occupy both low-bias training bins")
            row["branches"][name] = {
                "points": int(mask.sum()), "mean_entering_A": float(i[mask].mean())
            }
        row["dark_minus_light_A"] = (
            row["branches"]["iv_dark"]["mean_entering_A"]
            - row["branches"]["iv_1sun"]["mean_entering_A"]
        )
        bins.append(row)
    target = float(np.mean([b["dark_minus_light_A"] for b in bins]))
    return {"bins": bins, "photocurrent_target_A": target,
            "responsivity_target_A_W": target / (AREA_UM2 * 1000 * 1e-12)}


def low_bias_model(curve, dark, groups):
    # Evaluate dark/light tables at each branch's own observed voltage; no
    # arbitrary bin-center or non-matching acquisition-row approximation.
    values = []
    for k in (0, 1):
        branch_means = []
        for name, table in (("iv_dark", dark), ("iv_1sun", curve)):
            v = groups[name].values[:, 0]
            mask = (v >= k * BIN_WIDTH_V) & (v < (k + 1) * BIN_WIDTH_V)
            branch_means.append(float(prediction(table, v[mask]).mean()))
        values.append(branch_means[0] - branch_means[1])
    return float(np.mean(values))


def validate_curve(curve, *, fresh):
    v = np.asarray(curve["voltage_V"], dtype=float)
    i = np.asarray(curve["delivered_A_per_um2"], dtype=float)
    if v.shape != VOLTAGE_GRID.shape or not np.allclose(v, VOLTAGE_GRID, atol=1e-14, rtol=0):
        raise ValueError("Incomplete or altered DD voltage grid")
    if i.shape != v.shape or not np.all(np.isfinite(i)):
        raise ValueError("Incomplete or nonfinite DD current")
    if curve["contact_imbalance_relative"] > 1e-5:
        raise ValueError("Final terminal current conservation failed")
    limit = curve["absorbed_photon_limit_A_per_um2"]
    if curve["irradiance_W_m2"] > 0 and not (0 < i[0] <= limit * (1 + 1e-8)):
        raise ValueError("Short-circuit absorbed-photon budget failed")
    result = {"points": len(v), "complete_grid": True, "finite_current": True,
              "short_circuit_photon_budget_passed": True,
              "final_contact_relative_residual": curve["contact_imbalance_relative"]}
    if fresh:
        terminals = np.asarray(curve["terminal_entering_A_per_um2"])
        absolute = np.asarray(curve["contact_imbalance_absolute_A_per_um2"])
        relative = np.asarray(curve["contact_imbalance_relative_by_voltage"])
        if terminals.shape != (len(v), 2) or absolute.shape != v.shape or relative.shape != v.shape:
            raise ValueError("Missing per-voltage terminal audit")
        if not all(np.all(np.isfinite(a)) for a in (terminals, absolute, relative)):
            raise ValueError("Nonfinite terminal audit")
        if not np.allclose(-terminals[:, 0], i, rtol=1e-12, atol=1e-25):
            raise ValueError("Terminal audit disagrees with swept current")
        residual = np.abs(terminals.sum(axis=1))
        if not np.allclose(residual, absolute, rtol=1e-12, atol=1e-25):
            raise ValueError("Terminal residual audit inconsistent")
        # Absolute tolerance protects near-Voc conditioning; relative tolerance
        # is evaluated against each point, never the much larger forward tail.
        if np.any(residual > 1e-20 + 1e-5 * np.max(np.abs(terminals), axis=1)):
            raise ValueError("Per-voltage terminal conservation failed")
        result.update(max_absolute_contact_residual_A_per_um2=float(residual.max()),
                      max_relative_contact_residual=float(relative.max()),
                      conservation_absolute_tolerance_A_per_um2=1e-20,
                      conservation_relative_tolerance=1e-5)
    else:
        result["per_voltage_contact_audit"] = "Unavailable in historical archive"
    return result


def archive_audit(path):
    archive = json.loads(Path(path).read_text())
    checks = {}
    for label in ("dark", "light", "medium_mesh", "coarse_mesh", "short_lifetime"):
        item = archive[label]
        checks[label] = validate_curve(item, fresh=False)
        expected_mesh = {"medium_mesh": 0.08, "coarse_mesh": 0.16}.get(label, 0.04)
        expected_tau = 1e-8 if label == "short_lifetime" else 1e-5
        expected_light = 0 if label == "dark" else 1000
        if (item["mesh_um"] != expected_mesh or item["lifetime_s"] != expected_tau
                or item["irradiance_W_m2"] != expected_light):
            raise ValueError("Archived DD parameters differ from documented conceptual experiment")
        expected_photons = Q_C * BeerLambert(660, expected_light, 3000, 0.3).absorbed_pairs_cm2_s(3) * 1e-8
        if not np.isclose(item["absorbed_photon_limit_A_per_um2"], expected_photons, rtol=1e-12, atol=0):
            raise ValueError("Archived DD optical budget differs")
    return archive, {"path": str(path), "sha256": sha256(path), "checks": checks,
        "source_identity": "Contemporaneous source hashes unavailable; parameters/grid/budget checked; fresh baseline regression required. Archived dark remains conditional evidence.",
        "archived_sensitivity_only": {
            "medium_vs_fine_Isc_relative": archive["medium_mesh"]["isc_A_per_um2"] / archive["light"]["isc_A_per_um2"] - 1,
            "coarse_vs_fine_Isc_relative": archive["coarse_mesh"]["isc_A_per_um2"] / archive["light"]["isc_A_per_um2"] - 1,
            "short_lifetime_vs_nominal_Isc_relative": archive["short_lifetime"]["isc_A_per_um2"] / archive["light"]["isc_A_per_um2"] - 1,
            "interpretation": "Historical sensitivity, not rerun or independent process calibration"}}


def baseline_agreement(fresh, archived):
    i, old = np.asarray(fresh["delivered_A_per_um2"]), np.asarray(archived["delivered_A_per_um2"])
    scale = np.maximum(np.abs(old), abs(old[0]))
    change = np.abs(i - old) / scale
    result = {"max_absolute_current_change_A_per_um2": float(np.max(np.abs(i - old))),
              "max_scaled_current_change": float(change.max()),
              "scale": "max(abs(archived I(V)), archived Isc)",
              "tolerance": 1e-4, "passed": bool(np.max(change) <= 1e-4)}
    if not result["passed"] or fresh["nodes"] != archived["nodes"]:
        raise ValueError("Fresh baseline differs from archive; conditional dark reuse rejected")
    return result


def reflectance_decision(target_A, maximum_A):
    if not np.isfinite(target_A) or not np.isfinite(maximum_A) or maximum_A <= 0:
        raise ValueError("Finite target and positive maximum photocurrent required")
    inferred = 1 - target_A / maximum_A
    return {"target_A": target_A, "maximum_R0_A": maximum_A,
            "bracketed": bool(0 <= target_A <= maximum_A),
            "linearized_required_effective_reflectance": float(inferred),
            "required_input_multiplier_at_R0": float(target_A / maximum_A),
            "relative_shortfall_at_R0": float(1 - maximum_A / target_A) if target_A > 0 else None,
            "inference": "Linearized photocurrent-throughput relation used only to propose a bounded third DD curve; not a fitted process parameter"}


def shared_offset(dark, groups):
    # Training dark low-bias observation residual mean; no holdout/high-forward
    # current can enter this separate observation-model hypothesis.
    offsets = []
    for k in (0, 1):
        v = groups["iv_dark"].values[:, 0]
        i = terminal_current_A(groups["iv_dark"])
        mask = (v >= k * BIN_WIDTH_V) & (v < (k + 1) * BIN_WIDTH_V)
        offsets.append(float(np.mean(i[mask] - prediction(dark, v[mask]))))
    return float(np.mean(offsets))


def residual_stats(voltage, residual):
    if not len(residual):
        return {"points": 0, "equal_bin_rms_A": None}
    weights, bins = occupied_bin_weights(voltage, BIN_WIDTH_V)
    return {"points": len(residual), "occupied_bins": bins,
            "rms_A": float(np.sqrt(np.mean(residual**2))),
            "equal_bin_rms_A": float(np.sqrt(np.sum(weights * residual**2))),
            "bias_A": float(np.mean(residual)),
            "mae_A": float(np.mean(np.abs(residual))),
            "max_absolute_A": float(np.max(np.abs(residual)))}


def evaluate(light, dark, groups, offset):
    result = {}
    for name, table in (("iv_dark", dark), ("iv_1sun", light)):
        v = groups[name].values[:, 0]
        current = terminal_current_A(groups[name])
        in_domain = (v >= 0) & (v <= SERIES_CELLS * table["voltage_V"][-1])
        vv, ii = v[in_domain], current[in_domain]
        residual = prediction(table, vv) + offset - ii
        masks = {"train_nonnegative": ~heldout_mask(vv), "heldout_combined": heldout_mask(vv),
                 "low_bias_train": (vv >= 0) & (vv < 0.05),
                 "forward_train_ge_1p25V": (vv >= 1.25) & ~heldout_mask(vv)}
        masks.update({f"heldout_{lo:.2f}_{hi:.2f}V": (vv >= lo) & (vv < hi)
                      for lo, hi in HOLDOUT_REGIONS})
        result[name] = {key: residual_stats(vv[m], residual[m]) for key, m in masks.items()}
        result[name]["excluded_negative_voltage_points"] = int((v < 0).sum())
        result[name]["excluded_above_DD_voltage_points"] = int((v > SERIES_CELLS * table["voltage_V"][-1]).sum())
    return result


def device_metrics(curve):
    # Keep coarse DD interpolation and sampled MPP explicit.
    i = np.asarray(curve["delivered_A_per_um2"])
    v = np.asarray(curve["voltage_V"])
    index = int(np.argmax(np.maximum(v * i, 0)))
    return {"Isc_pair_A": float(AREA_UM2 * i[0]),
            "Voc_pair_V_linear_interpolation": float(SERIES_CELLS * curve["voc_V"]),
            "MPP_pair_sampled_V_A_W": [float(SERIES_CELLS * v[index]),
                float(AREA_UM2 * i[index]), float(SERIES_CELLS * AREA_UM2 * v[index] * i[index])],
            "responsivity_A_W": curve["responsivity_A_W"],
            "absorbed_photon_ceiling_A_W": curve["absorbed_photon_limit_A_per_um2"] / 1e-9,
            "Isc_to_absorbed_photon_limit": float(i[0] / curve["absorbed_photon_limit_A_per_um2"])}


def plots(groups, curves, dark, offset, target, destination):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(2, 2, figsize=(12, 8), layout="constrained")
    for col, name in enumerate(("iv_dark", "iv_1sun")):
        v, i = groups[name].values[:, 0], terminal_current_A(groups[name])
        mask = (v >= 0) & (v <= 1.4)
        axes[0, col].scatter(v[mask], i[mask] * 1e9, s=2, alpha=.18,
                            color="black", label="Unchanged supplied observations")
        for label, curve in curves.items():
            table = dark if name == "iv_dark" else curve
            grid = np.asarray(table["voltage_V"]) * SERIES_CELLS
            axes[0, col].plot(grid, (prediction(table, grid) + offset) * 1e9, label=label)
            residual = prediction(table, v[mask]) + offset - i[mask]
            axes[1, col].scatter(v[mask], residual * 1e9, s=2, alpha=.25, label=label)
            if name == "iv_dark":
                break  # Same frozen dark prediction for all optical candidates.
        for row in (0, 1):
            ax = axes[row, col]
            for lo, hi in HOLDOUT_REGIONS:
                ax.axvspan(lo, hi, color="gold", alpha=.2)
            ax.set(xlabel="Pair voltage (V)",
                   ylabel="Entering current (nA)" if row == 0 else "Model − measured (nA)",
                   xlim=(0, 1.4), yscale="symlog")
            ax.grid(alpha=.2)
        axes[0, col].set_title(name + "; symmetric log current scale")
        axes[0, col].legend(fontsize=7)
    fig.suptitle("Direct DD optical feasibility; fixed conceptual junction; yellow regions are prior holdouts")
    fig.savefig(destination / "dd_comparison.png", dpi=170)
    plt.close(fig)
    fig, ax = plt.subplots(figsize=(7, 4), layout="constrained")
    names = list(curves)
    values = [curves[k]["responsivity_A_W"] for k in names]
    ax.bar(names, values, color=["#327d9e", "#d08036", "#57915f"][:len(names)])
    ax.axhline(target["responsivity_target_A_W"], color="black", label="Low-bias dark−light training target")
    for k, val in enumerate(values):
        ax.text(k, val + .004, f"{val:.5f}", ha="center")
    ax.set(ylabel="A/W at 1000 W/m²; 540 µm² per cell", ylim=(0, .35),
           title="Achieved DD short-circuit response and training target")
    ax.legend(fontsize=8)
    fig.savefig(destination / "throughput_feasibility.png", dpi=170)
    plt.close(fig)


def readme(report):
    decision, target = report["feasibility"], report["training_target"]
    rows = []
    for name, c in report["curves"].items():
        m = c["device_metrics"]
        rows.append(f"| {name} | {c['reflectance']:.6f} | {m['responsivity_A_W']:.6f} | {m['Isc_pair_A']*1e9:.4f} | {m['Voc_pair_V_linear_interpolation']:.6f} | {m['MPP_pair_sampled_V_A_W'][2]*1e9:.4f} |")
    maximum = report["curves"]["maximum_R0"]
    holdout_rms = maximum["residuals"]["iv_1sun"]["heldout_combined"]["equal_bin_rms_A"]
    return f"""# Direct-DD PV calibration feasibility

**{report['status']}** No application defaults or core physics changed. This milestone is a conditional optical-throughput feasibility check, not process identification or a completed PV calibration.

Actual S2E training target: equal mean of dark-minus-light means in two 25 mV pair-voltage bins covering **0 ≤ Vpair < 0.05 V**: **{target['photocurrent_target_A']*1e9:.6f} nA**, or **{target['responsivity_target_A_W']:.9f} A/W**. Separate acquisitions are binned by voltage, never paired by row. Native current observations, acquisition order and repeated-voltage scatter remain unchanged. A constant shared dark/light observation offset is assumed to cancel in this difference. The diagnostic shared entering-current offset, estimated only from the same dark low-bias training bins, is {report['shared_observation_offset_A']*1e9:.6f} nA; it is not a verified instrument correction and is excluded from device Isc/Voc/MPP.

| Direct DD curve | Effective R | Isc response A/W | Pair Isc nA | Pair Voc V | Pair sampled Pmax nW |
|---|---:|---:|---:|---:|---:|
{chr(10).join(rows)}

Two equal 540 µm² cells in series: **Vpair = 2 Vcell; Ipair = 540 Iper_um²**. There is no factor of two in current. Both fresh sweeps cover 29 points from 0 to 0.70 V/cell, stepping 25 mV/cell; the resulting 50 mV pair grid limits interpolated Voc and sampled MPP accuracy. Optical input is 660 nm, 1000 W/m², α = 3000 cm⁻¹, unity pair yield and single-pass Beer–Lambert generation. Fixed structure: 3 µm Si, 0.3 µm n emitter (ND = 1e18 cm⁻³), 2.7 µm p base (NA = 1e16 cm⁻³), full-width ideal transparent ohmic top/back contacts, insulating sides, 300 K, SRH τn = τp = 1e-5 s, existing default transport/statistics. These are conceptual assumptions, not measured process parameters. No temperature, doping, thickness, absorption, lifetime, area, Rs/Rsh or contact physics was fitted.

The physical R range is [0,1]. At R=0 the achieved low-bias model photocurrent is **{decision['maximum_R0_A']*1e9:.6f} nA**, short by **{decision['relative_shortfall_at_R0']*100:.3f}%** of the training target. The linearized required effective reflectance is **{decision['linearized_required_effective_reflectance']:.6f}** and the R=0 input multiplier would be **{decision['required_input_multiplier_at_R0']:.6f}**. These quantify the discrepancy; an unphysical R or increased irradiance is not accepted as calibration. The candidate run decision is determined only by the low-bias target and physical bounds. {report['third_curve_decision']}

The R=0 analytical absorbed-photon ceiling is {maximum['device_metrics']['absorbed_photon_ceiling_A_W']:.9f} A/W. Achieved Isc uses {maximum['device_metrics']['Isc_to_absorbed_photon_limit']*100:.3f}% of it; the target would require {report['required_information']['target_fraction_of_R0_absorbed_photon_ceiling']*100:.3f}% collection at the assumed absorption. A photon ceiling alone therefore cannot diagnose the missing structure or collection. Required additional evidence: measured thickness/emitter and doping profiles, contact geometry/selectivity and surface/interface recombination, actual wavelength/irradiance and illuminated active area, reflection/transmission or absorption information, plus dark IV and temperature/offset characterization. The required-current ratio is a discrepancy indicator, not a unique proposal for changing thickness, absorption, area or collection physics. No fabricated parameter identification is made.

Photon budget, finite complete grids, both terminal currents at every fresh voltage, and fresh-baseline/archive regression are checked in metrics.json. Baseline maximum scaled current change is {report['archive']['fresh_baseline_agreement']['max_scaled_current_change']:.3g}. Terminal conservation tolerance is 1e-20 A/µm² absolute plus 1e-5 times the local terminal-current scale. Core solver equations/sweep are unchanged; an application-local subclass reads both contacts after each successful voltage point. Archived dark/mesh/lifetime curves pass recorded parameter/grid/photon-limit checks. Their contemporaneous source hashes and per-voltage terminal audits are unavailable: fresh baseline agreement supports conditional reuse, not proof of historical source identity. No new dark, mesh or lifetime sweep was run.

Training and holdout residuals against unchanged observations are recorded separately for dark and light. Existing holdouts [0.90,1.05) and [1.15,1.25) V are retained; they were previously inspected and are **not a fresh blind validation set**. All negative-voltage observations are excluded from DD residual evaluation because no negative-voltage extrapolation is allowed. The residual sign is model entering current plus shared offset minus measured entering current. R=0 illuminated holdout equal-bin RMS is {holdout_rms*1e9:.6f} nA. The fixed dark shape and Voc/MPP remain independent reasons a photocurrent-only fit could not promote this model. No numerical pass tolerance for experimental accuracy is claimed without measurement uncertainty and a calibrated structure. Observed MPP is a noisy maximum sample and observed zero-current crossings are an acquisition-order distribution, not a unique reference Voc.

![Direct DD versus observations and residuals](dd_comparison.png)
![Optical throughput feasibility](throughput_feasibility.png)

## Reproduction and scope

Executed with the existing repository .venv; package versions, UTC time, runtime, executing source hashes, source/archived-data hashes and DD tables are in metrics.json and dd_curves.json. Local source identity is checked against the prior read-only inventory. Local hashes do not independently authenticate the user-reported data authorship/archive version/license. No source data, local PDFs or raw SPICE transients are included.

```sh
.venv/bin/python -m examples.microrobot.pv_calibration --source-dir /Users/abhineet/Downloads/Reynolds-2022-data --output /tmp/new-pv-feasibility
.venv/bin/python -m pytest tests/integration/test_pv_calibration.py -q
```

The output must be new or empty and outside the input directory. No network access, package installation, full system/circuit rerun, submission, fabrication, publication or push was performed. requirements.txt records the actual relevant installed versions for reproduction; it is not an independently tested clean-environment lockfile.
"""


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--archive", type=Path, default=HERE / "results/pv.json")
    args = parser.parse_args(argv)
    if args.output.resolve().is_relative_to(args.source_dir.resolve()):
        parser.error("Output must be outside read-only source directory")
    if args.output.exists() and (not args.output.is_dir() or any(args.output.iterdir())):
        parser.error("Output must be fresh or empty; existing archive preserved")
    started = time.perf_counter()
    spec = next(s for s in SCHEMAS if s.filename == "FigS2_CircuitTesting.csv")
    source = load_file(args.source_dir / spec.filename, spec)
    inventory_path = HERE / "data/reynolds2022_inventory.json"
    inventory = json.loads(inventory_path.read_text())
    audited_source = next(f for f in inventory["files"] if f["filename"] == spec.filename)
    if source.sha256 != audited_source["sha256"]:
        raise ValueError("Source differs from prior read-only inventory; review provenance before DD")
    groups = source.groups
    target = low_bias_difference(groups)
    archive, audit = archive_audit(args.archive)
    args.output.mkdir(parents=True, exist_ok=True)
    curves, validations, elapsed = {}, {}, {}

    def run_curve(label, reflectance):
        before = time.perf_counter()
        print(json.dumps({"running": label, "reflectance": reflectance}), flush=True)
        curve = characterize(mesh_um=0.04, lifetime_s=1e-5, irradiance_W_m2=1000,
                             reflectance=reflectance)
        validations[label] = validate_curve(curve, fresh=True)
        elapsed[label] = time.perf_counter() - before
        curves[label] = curve
        write_json(args.output / "dd_curves.json", curves)
        print(json.dumps({"completed": label, "seconds": elapsed[label],
                          "responsivity_A_W": curve["responsivity_A_W"]}), flush=True)
        return curve

    baseline = run_curve("baseline_R0p3", 0.3)
    audit["fresh_baseline_agreement"] = baseline_agreement(baseline, archive["light"])
    maximum = run_curve("maximum_R0", 0.0)
    dark = archive["dark"]
    maximum_low = low_bias_model(maximum, dark, groups)
    decision = reflectance_decision(target["photocurrent_target_A"], maximum_low)
    if decision["bracketed"]:
        candidate = run_curve("candidate_Rbounded", decision["linearized_required_effective_reflectance"])
        candidate_low = low_bias_model(candidate, dark, groups)
        decision["candidate_low_bias_A"] = candidate_low
        decision["candidate_minus_target_A"] = candidate_low - target["photocurrent_target_A"]
        third = "A bounded third DD candidate was executed; matching photocurrent alone does not establish calibrated dark shape, Voc or MPP."
        status = "Low-bias target bracketed; conditional candidate only; PV calibration remains unproven"
    else:
        third = "The target is not bracketed: third DD candidate skipped, and the bounded optical family is infeasible."
        status = "Infeasible within the fixed-structure effective-reflectance family; PV calibration incomplete"
    offset = shared_offset(dark, groups)
    code_paths = [Path(__file__), HERE / "pv.py", HERE / "reynolds_data.py", HERE / "reynolds_fit.py"]
    code_paths += list((ROOT / "opentcad/device").glob("*.py"))
    code_paths += list((ROOT / "opentcad/geometry").glob("*.py"))
    code_paths += [ROOT / "opentcad/materials/database.py", ROOT / "opentcad/materials/params/Si.yaml"]
    versions = {n: importlib.metadata.version(n) for n in ("numpy", "scipy", "devsim", "gmsh", "pyvista", "matplotlib", "pydantic", "PyYAML")}
    report = {"status": status, "executed_UTC": datetime.now(timezone.utc).isoformat(),
        "execution": {"command_argv": sys.argv, "python": platform.python_version(),
            "executable": sys.executable, "platform": platform.platform(), "packages": versions,
            "fresh_light_DD_sweeps": len(curves), "curve_seconds": elapsed,
            "total_seconds": time.perf_counter() - started,
            "code_sha256": {str(p.relative_to(ROOT)): sha256(p) for p in sorted(set(code_paths))}},
        "source": {"path": str(args.source_dir / spec.filename), "sha256": source.sha256,
            "size_bytes": source.size_bytes, "inventory_sha256": sha256(inventory_path),
            "matches_prior_local_inventory": True,
            "provenance": "User-supplied local data; user-reported origin not independently authenticated; license unverified"},
        "method": {"variable": "effective_reflectance only", "bounds": [0, 1],
            "all_other_physics_fixed": True, "training_pair_voltage_V": [0, .05],
            "training_upper_boundary_exclusive": True, "training_bin_width_V": BIN_WIDTH_V,
            "holdouts_V": [list(x) for x in HOLDOUT_REGIONS], "holdouts_fresh_blind": False,
            "pair_voltage_relation": "2 * cell voltage", "pair_current_relation": "540 * current_per_um2",
            "dark_light_offset_assumption": "One constant shared entering-current offset cancels in equal-voltage-bin difference",
            "negative_voltage_extrapolation": False, "process_identification": False},
        "training_target": target, "feasibility": decision, "third_curve_decision": third,
        "shared_observation_offset_A": offset, "archive": audit,
        "curves": {label: {"reflectance": curve["reflectance"], "validation": validations[label],
                    "device_metrics": device_metrics(curve),
                    "low_bias_photocurrent_A": low_bias_model(curve, dark, groups),
                    "residuals": evaluate(curve, dark, groups, offset)} for label, curve in curves.items()},
        "observed_1sun_summary_unchanged": observed_iv_summary(groups["iv_1sun"].values[:, 0], terminal_current_A(groups["iv_1sun"])),
        "required_information": {"target_fraction_of_R0_absorbed_photon_ceiling": target["responsivity_target_A_W"] / device_metrics(maximum)["absorbed_photon_ceiling_A_W"],
            "missing": ["actual optical irradiance/wavelength and illuminated area", "measured reflection/absorption", "absorber/emitter geometry and doping profiles", "contact selectivity/geometry and surface recombination", "temperature and observation offsets", "dark-IV shape and independent validation"]},
        "promotion": {"promoted": False, "reason": "Photocurrent-only feasibility does not calibrate dark shape/Voc/MPP; fixed conceptual structure and conditional archived dark cannot identify the measured process"}}
    plots(groups, curves, dark, offset, target, args.output)
    write_json(args.output / "metrics.json", report)
    (args.output / "README.md").write_text(readme(report))
    (args.output / "requirements.txt").write_text("# Relevant installed versions; not a clean-environment validation\n" + "".join(f"{n}=={v}\n" for n, v in versions.items()))
    write_json(args.output / "sha256.json", {p.name: sha256(p) for p in sorted(args.output.iterdir()) if p.is_file()})
    print(json.dumps({"status": status, "output": str(args.output), "feasibility": decision}), flush=True)


if __name__ == "__main__":
    main()
