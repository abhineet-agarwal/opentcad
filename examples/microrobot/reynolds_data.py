"""Strict, read-only ingestion of the user-supplied Reynolds (2022) CSVs.

Run from the repository root with::

    python -m examples.microrobot.reynolds_data --source-dir /local/data --output /local/report

The source files are external inputs, not package assets. Only aggregate JSON and
rendered figures are written. Native values and acquisition order remain intact
in memory; independent column groups have independent lengths. This comparison
does not refit or replace the historical raster-derived terminal model.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
import hashlib
import io
import json
from pathlib import Path

import numpy as np

from opentcad.device.compact import SingleDiodePV


@dataclass(frozen=True)
class GroupSpec:
    name: str
    columns: tuple[int, ...]
    axis_column: int = 0  # Index within this group, not within the source file.


@dataclass(frozen=True)
class FileSpec:
    filename: str
    headers: tuple[str, ...]
    groups: tuple[GroupSpec, ...]

    def __post_init__(self):
        columns = [column for group in self.groups for column in group.columns]
        if sorted(columns) != list(range(len(self.headers))):
            raise ValueError("Every source column must belong to exactly one group")
        if len({g.name for g in self.groups}) != len(self.groups):
            raise ValueError("Group names must be unique within a file")
        if any(not 0 <= g.axis_column < len(g.columns) for g in self.groups):
            raise ValueError("Invalid group axis column")


SCHEMAS = (
    FileSpec(
        "Fig3_PurcellBot.csv",
        ("Time (s)", "Distance (µm)", "Time inset (s)", "Distance inset (µm)"),
        (GroupSpec("motion", (0, 1)), GroupSpec("inset", (2, 3))),
    ),
    FileSpec(
        "Fig4_PurcellBot.csv",
        (
            "Time (s)",
            "Distance (µm)",
            "Speed (µm / s)",
            "Time (s)",
            "Foot Position 1 (µm)",
            "Foot Position 2 (µm)",
        ),
        (GroupSpec("motion", (0, 1, 2)), GroupSpec("feet", (3, 4, 5))),
    ),
    FileSpec("Fig5_Dogbot.csv", ("Time (s)", "Position (µm)"), (GroupSpec("motion", (0, 1)),)),
    FileSpec(
        "FigS2_CircuitTesting.csv",
        (
            "Time 2.5 sun (s)",
            "Current 2.5 sun (µA)",
            "Time 7 sun (s)",
            "Current 7 sun (µA)",
            "Time V 2 phase (s)",
            "Voltage phase 1 (V)",
            "Voltage phase 2 (V)",
            "Power In V meas (kW / m2)",
            "Voltage (V)",
            "Power in I meas (kW / m2)",
            "Current (µm)",
            "Power in f meas (kW / m2)",
            "Frequency (Hz)",
            "Voltage 0 sun (V)",
            "Current 0 sun (µA)",
            "Voltage 1 sun (V)",
            "Current 1 sun (µA)",
        ),
        (
            GroupSpec("current_2_5sun", (0, 1)),
            GroupSpec("current_7sun", (2, 3)),
            GroupSpec("phase_voltages", (4, 5, 6)),
            GroupSpec("irradiance_voltage", (7, 8)),
            GroupSpec("irradiance_current_header_ambiguous", (9, 10)),
            GroupSpec("irradiance_frequency", (11, 12)),
            GroupSpec("iv_dark", (13, 14)),
            GroupSpec("iv_1sun", (15, 16)),
        ),
    ),
    FileSpec(
        "FigS4_LEGO_purcell.csv",
        ("Time (s)", "Distance (cm)", "Time inset (s)", "Distance inset (cm)"),
        (GroupSpec("motion", (0, 1)), GroupSpec("inset", (2, 3))),
    ),
    FileSpec(
        "FigS6_DogbotCircuit.csv",
        ("Current (nA)", "Time (s)"),
        (GroupSpec("current_trace", (0, 1), axis_column=1),),
    ),
)


@dataclass(frozen=True)
class LoadedGroup:
    spec: GroupSpec
    headers: tuple[str, ...]
    values: np.ndarray
    source_rows: np.ndarray  # One-based CSV line numbers; header is line one.


@dataclass(frozen=True)
class LoadedFile:
    spec: FileSpec
    sha256: str
    size_bytes: int
    encoding: str
    data_rows: int
    groups: dict[str, LoadedGroup]


def _header(value: str) -> str:
    # Only spelling-equivalent Unicode micro symbols, BOM and outer whitespace.
    return value.lstrip("\ufeff").strip().replace("μ", "µ")


def load_file(path: Path | str, spec: FileSpec) -> LoadedFile:
    """Validate every cell, accepting complete trailing padding per column group.

    Blank padding may shorten one independent series, but half-pairs, resumed
    data after padding, extra/missing columns, invalid numbers and NaN/Inf fail.
    UTF-8 with optional BOM and Windows-1252 (including latin1 µ) are supported.
    No numeric values are sorted, shifted, deduplicated or converted here.
    """
    path = Path(path)
    raw = path.read_bytes()
    try:
        text = raw.decode("utf-8-sig")
        encoding = "utf-8-sig"
    except UnicodeDecodeError:
        text = raw.decode("cp1252")
        encoding = "cp1252"
    reader = csv.reader(io.StringIO(text, newline=""), strict=True)
    try:
        headers = next(reader)
    except StopIteration as exc:
        raise ValueError(f"{path.name}: empty file") from exc
    except csv.Error as exc:
        raise ValueError(f"{path.name}: malformed CSV header") from exc
    if tuple(map(_header, headers)) != spec.headers:
        raise ValueError(f"{path.name}: headers differ from explicit schema: {headers!r}")
    values = {g.name: [] for g in spec.groups}
    rows = {g.name: [] for g in spec.groups}
    padded = {g.name: False for g in spec.groups}
    data_rows = 0
    try:
        for row in reader:
            line = reader.line_num
            data_rows += 1
            if len(row) != len(headers):
                raise ValueError(
                    f"{path.name}:{line}: expected {len(headers)} columns, received {len(row)}"
                )
            for group in spec.groups:
                cells = [row[c].strip() for c in group.columns]
                if not any(cells):
                    padded[group.name] = True
                    continue
                if not all(cells):
                    raise ValueError(f"{path.name}:{line}: partial group {group.name}")
                if padded[group.name]:
                    raise ValueError(f"{path.name}:{line}: {group.name} resumes after padding")
                try:
                    numbers = [float(cell) for cell in cells]
                except ValueError as exc:
                    raise ValueError(f"{path.name}:{line}: invalid number in {group.name}") from exc
                if not np.all(np.isfinite(numbers)):
                    raise ValueError(f"{path.name}:{line}: nonfinite number in {group.name}")
                values[group.name].append(numbers)
                rows[group.name].append(line)
    except csv.Error as exc:
        raise ValueError(f"{path.name}:{reader.line_num}: malformed CSV") from exc
    groups = {}
    for group in spec.groups:
        if not values[group.name]:
            raise ValueError(f"{path.name}: empty group {group.name}")
        array = np.asarray(values[group.name], dtype=float)
        source_rows = np.asarray(rows[group.name], dtype=int)
        array.setflags(write=False)
        source_rows.setflags(write=False)
        groups[group.name] = LoadedGroup(
            group, tuple(spec.headers[c] for c in group.columns), array, source_rows
        )
    return LoadedFile(spec, hashlib.sha256(raw).hexdigest(), len(raw), encoding, data_rows, groups)


def load_dataset(source_dir: Path | str) -> dict[str, LoadedFile]:
    """Require all six named source files; unrelated files are ignored."""
    source = Path(source_dir)
    return {spec.filename: load_file(source / spec.filename, spec) for spec in SCHEMAS}


def _range(values) -> list[float]:
    return [float(np.min(values)), float(np.max(values))]


def dataset_summary(dataset: dict[str, LoadedFile]) -> dict:
    result = {}
    for name, file in dataset.items():
        groups = {}
        for key, group in file.groups.items():
            axis = group.values[:, group.spec.axis_column]
            steps = np.diff(axis)
            groups[key] = {
                "points": len(axis),
                "columns_zero_based": list(group.spec.columns),
                "source_line_range": [int(group.source_rows[0]), int(group.source_rows[-1])],
                "trailing_padding_rows": file.data_rows - len(axis),
                "native_column_ranges": {
                    h: _range(group.values[:, i]) for i, h in enumerate(group.headers)
                },
                "axis_header": group.headers[group.spec.axis_column],
                "axis_strictly_increasing": bool(np.all(steps > 0)),
                "axis_decreasing_steps": int(np.sum(steps < 0)),
                "axis_equal_steps": int(np.sum(steps == 0)),
                "axis_unique_values": int(len(np.unique(axis))),
            }
        result[name] = {
            "sha256": file.sha256,
            "size_bytes": file.size_bytes,
            "encoding": file.encoding,
            "data_rows": file.data_rows,
            "groups": groups,
        }
    return result


def terminal_current_A(group: LoadedGroup) -> np.ndarray:
    """Explicit native µA -> A, retaining the measured entering-current sign."""
    if group.headers != ("Voltage 0 sun (V)", "Current 0 sun (µA)") and group.headers != (
        "Voltage 1 sun (V)",
        "Current 1 sun (µA)",
    ):
        raise ValueError("Expected one of the explicitly mapped S2E IV groups")
    return group.values[:, 1] * 1e-6


def observed_iv_summary(voltage: np.ndarray, entering_A: np.ndarray) -> dict:
    """Sampled MPP and acquisition-adjacent crossings, never a sorted IV curve.

    Repeated voltages may have different currents. Adjacent-current sign changes
    are linearly interpolated locally and summarized as a distribution, not a
    unique Voc. Opposite currents at identical voltage remain valid crossings
    at that voltage; no division by a voltage difference is needed.
    """
    voltage, entering_A = np.asarray(voltage), np.asarray(entering_A)
    if (
        voltage.ndim != 1
        or voltage.shape != entering_A.shape
        or not len(voltage)
        or not np.all(np.isfinite(voltage))
        or not np.all(np.isfinite(entering_A))
    ):
        raise ValueError("Equal nonempty finite one-dimensional IV arrays required")
    crossing = (entering_A[:-1] < 0) & (entering_A[1:] > 0)
    crossing |= (entering_A[:-1] > 0) & (entering_A[1:] < 0)
    indices = np.flatnonzero(crossing)
    zeros = voltage[entering_A == 0]
    if len(indices):
        fraction = -entering_A[indices] / (entering_A[indices + 1] - entering_A[indices])
        zeros = np.concatenate(
            (zeros, voltage[indices] + fraction * (voltage[indices + 1] - voltage[indices]))
        )
    closest = int(np.argmin(np.abs(entering_A)))
    power = -voltage * entering_A
    generating = (voltage >= 0) & (entering_A <= 0)
    mpp = None
    if np.any(generating):
        index = int(np.argmax(np.where(generating, power, -np.inf)))
        mpp = {
            "sample_index_zero_based": index,
            "voltage_V": float(voltage[index]),
            "delivered_current_A": float(-entering_A[index]),
            "power_W": float(power[index]),
        }
    unique, inverse, counts = np.unique(voltage, return_inverse=True, return_counts=True)
    low, high = np.full(len(unique), np.inf), np.full(len(unique), -np.inf)
    np.minimum.at(low, inverse, entering_A)
    np.maximum.at(high, inverse, entering_A)
    repeated = counts > 1
    return {
        "observed_sample_mpp": mpp,
        "zero_current_crossings": {
            "adjacent_sign_changes": len(indices),
            "exact_zero_samples": int(np.sum(entering_A == 0)),
            "count": len(zeros),
            "voltage_range_V": _range(zeros) if len(zeros) else None,
            "median_voltage_V": float(np.median(zeros)) if len(zeros) else None,
        },
        "closest_zero_current_sample": {
            "sample_index_zero_based": closest,
            "voltage_V": float(voltage[closest]),
            "entering_current_A": float(entering_A[closest]),
        },
        "repeated_voltage_values": int(np.sum(repeated)),
        "repeated_voltage_max_current_span_A": float(np.max((high - low)[repeated]))
        if np.any(repeated)
        else 0.0,
        "near_zero_voltage_abs_below_10mV": {
            "points": int(np.sum(np.abs(voltage) < 0.01)),
            "median_entering_current_A": float(np.median(entering_A[np.abs(voltage) < 0.01]))
            if np.any(np.abs(voltage) < 0.01)
            else None,
            "entering_current_range_A": _range(entering_A[np.abs(voltage) < 0.01])
            if np.any(np.abs(voltage) < 0.01)
            else None,
            "interpretation": "Local observed current distribution; no exact Isc interpolation or offset correction.",
        },
        "method": "Acquisition order retained; no global interpolation, sorting, averaging or offsets. "
        "MPP is the maximum observed generating sample, sensitive to noise and extreme-value selection; "
        "it is not a smoothed/continuous-curve estimate or a model validation tolerance. "
        "Crossings may reflect noise or sweep reversal and are not a unique measured Voc.",
    }


def _errors(residual: np.ndarray, voltage: np.ndarray, mask: np.ndarray) -> dict:
    r = residual[mask]
    return {
        "points": len(r),
        "voltage_range_V": _range(voltage[mask]) if len(r) else None,
        "mean_model_minus_measured_A": float(np.mean(r)) if len(r) else None,
        "rms_A": float(np.sqrt(np.mean(r * r))) if len(r) else None,
        "mae_A": float(np.mean(np.abs(r))) if len(r) else None,
        "maximum_absolute_A": float(np.max(np.abs(r))) if len(r) else None,
    }


def compare_pv(
    dataset: dict[str, LoadedFile], historical_fit: Path | str
) -> tuple[dict, SingleDiodePV]:
    path = Path(historical_fit)
    raw = path.read_bytes()
    historical = json.loads(raw)
    model = SingleDiodePV(**historical["fitted_terminal_model"])
    branches = {}
    groups = dataset["FigS2_CircuitTesting.csv"].groups
    for name, irradiance in (("iv_dark", 0.0), ("iv_1sun", 1000.0)):
        group = groups[name]
        voltage, measured = group.values[:, 0], terminal_current_A(group)
        predicted = -model.current_A(voltage, irradiance)
        residual = predicted - measured
        masks = {
            "all": np.ones(len(voltage), dtype=bool),
            "entering_negative": measured < 0,
            "entering_nonnegative": measured >= 0,
        }
        for label, lower, upper in (
            ("V_below_0", -np.inf, 0),
            ("V_0_to_0.8", 0, 0.8),
            ("V_0.8_to_1.1", 0.8, 1.1),
            ("V_1.1_to_1.3", 1.1, 1.3),
            ("V_above_1.3", 1.3, np.inf),
        ):
            masks[label] = (voltage >= lower) & (voltage < upper)
        # An additional diagnostic reduces unequal voltage occupancy without
        # treating jittering, multivalued records as a single interpolated IV.
        bins = np.floor(voltage / 0.025).astype(int)
        mse = [np.mean(residual[bins == b] ** 2) for b in np.unique(bins)]
        branches[name] = {
            "irradiance_W_m2": irradiance,
            "errors_by_sample": {
                label: _errors(residual, voltage, mask) for label, mask in masks.items()
            },
            "equal_occupied_25mV_bin_rms_A": float(np.sqrt(np.mean(mse))),
            "occupied_25mV_bins": len(mse),
            "direct_observations": observed_iv_summary(voltage, measured),
        }
    observed = branches["iv_1sun"]["direct_observations"]
    mpp = observed["observed_sample_mpp"]
    near_zero = observed["near_zero_voltage_abs_below_10mV"]["median_entering_current_A"]
    historical_pmax = model.maximum_power_point()[2]
    historical_isc = float(model.current_A(0))
    branches["iv_1sun"]["method_dependent_ratios_to_historical_model"] = {
        "observed_sample_MPP_power_ratio": mpp["power_W"] / historical_pmax
        if mpp is not None and historical_pmax > 0
        else None,
        "near_zero_voltage_median_delivered_current_ratio": -near_zero / historical_isc
        if near_zero is not None and historical_isc > 0
        else None,
        "interpretation": "Ratios compare different extraction methods: an extreme observed sample "
        "versus a smooth model MPP, and a finite-voltage-window median versus model current at V=0. "
        "They are not measurement uncertainty, validation tolerance or recalibration factors.",
    }
    return {
        "historical_fit_path": str(path),
        "historical_fit_sha256": hashlib.sha256(raw).hexdigest(),
        "historical_model_parameters": historical["fitted_terminal_model"],
        "historical_model_Voc_1sun_V": model.open_circuit_V(),
        "historical_model_MPP_1sun_V_A_W": list(model.maximum_power_point()),
        "measured_current_convention": "Conventional terminal entering current; native µA multiplied "
        "by 1e-6. Model current_A delivers current and is negated.",
        "comparison": "Frozen historical raster fit; no optimization or default parameter changes. "
        "Sample metrics weight every acquisition equally; the additional RMS gives "
        "equal weight to each occupied 25mV bin's mean squared residual. "
        "Voltage intervals include the lower bound and exclude the upper bound.",
        "measurement_context": {
            "figure": "S2E",
            "series_cells": 2,
            "each_cell_area_um2": 540,
            "1sun_W_m2": 1000,
            "context_source": "Supplement Fig. S2 caption and historical fit metadata",
            "temperature_K": model.temperature_K,
            "temperature_provenance": "Historical fit assumption; not a measured temperature.",
        },
        "branches": branches,
    }, model


def write_plots(dataset: dict[str, LoadedFile], model: SingleDiodePV, output: Path):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(2, 2, figsize=(12, 8), layout="constrained")
    for column, (name, light, title) in enumerate(
        (("iv_dark", 0, "S2E: dark"), ("iv_1sun", 1000, "S2E: 1 sun"))
    ):
        group = dataset["FigS2_CircuitTesting.csv"].groups[name]
        v, i = group.values[:, 0], terminal_current_A(group)
        grid = np.linspace(v.min(), v.max(), 600)
        for ax in axes[:, column]:
            ax.scatter(v, i * 1e9, s=2, alpha=0.15, rasterized=True, label="Native samples")
            ax.plot(
                grid,
                -model.current_A(grid, light) * 1e9,
                color="black",
                label=f"Historical raster fit ({model.temperature_K:g} K assumed)",
            )
            ax.axhline(0, color="gray", linewidth=0.6)
            ax.set(xlabel="Terminal voltage (V)", ylabel="Entering current (nA)")
            ax.grid(alpha=0.2)
        axes[0, column].set_title(title + ": full measured range")
        axes[1, column].set(xlim=(0.8, 1.33), ylim=(-175, 180), title=title + ": knee / crossing")
    axes[0, 0].legend(fontsize=8)
    fig.suptitle(
        "Local CSV comparison: two 540 µm² actuator PVs in series; frozen historical model"
    )
    fig.savefig(output / "pv_comparison.png", dpi=160)
    plt.close(fig)

    fig, axes = plt.subplots(4, 3, figsize=(15, 14), layout="constrained")
    panels = [
        ("Fig3_PurcellBot.csv", "motion", "Fig. 3: motion", (1,)),
        ("Fig4_PurcellBot.csv", "motion", "Fig. 4: Antbot motion", (1,)),
        ("Fig4_PurcellBot.csv", "feet", "Fig. 4: Antbot feet", (1, 2)),
        ("Fig5_Dogbot.csv", "motion", "Fig. 5: motion", (1,)),
        ("FigS4_LEGO_purcell.csv", "motion", "Fig. S4: LEGO motion", (1,)),
        ("FigS6_DogbotCircuit.csv", "current_trace", "Fig. S6: circuit current", (0,)),
        ("FigS2_CircuitTesting.csv", "current_2_5sun", "S2: current, 2.5 sun", (1,)),
        ("FigS2_CircuitTesting.csv", "current_7sun", "S2: current, 7 sun", (1,)),
        ("FigS2_CircuitTesting.csv", "phase_voltages", "S2: two phase voltages", (1, 2)),
        ("FigS2_CircuitTesting.csv", "irradiance_voltage", "S2C: output voltage amplitude", (1,)),
        (
            "FigS2_CircuitTesting.csv",
            "irradiance_current_header_ambiguous",
            "S2C: current amplitude (figure confirms µA)",
            (1,),
        ),
        ("FigS2_CircuitTesting.csv", "irradiance_frequency", "S2D: output frequency", (1,)),
    ]
    for ax, (filename, name, title, ys) in zip(axes.flat, panels):
        group = dataset[filename].groups[name]
        x = group.values[:, group.spec.axis_column]
        for y in ys:
            if name.startswith("irradiance_"):
                ax.scatter(x, group.values[:, y], s=18, label=group.headers[y])
            else:
                ax.plot(x, group.values[:, y], linewidth=0.6, label=group.headers[y])
        ax.set(
            title=title,
            xlabel=group.headers[group.spec.axis_column],
            ylabel=group.headers[ys[0]]
            if len(ys) == 1
            else "Voltage (V)"
            if "phase" in name
            else "Foot position (µm)",
        )
        if len(ys) > 1:
            ax.legend(fontsize=7)
        ax.grid(alpha=0.2)
        if name == "irradiance_current_header_ambiguous":
            ax.set_ylabel("Current (µA); CSV header literally µm")
        if "inset" in dataset[filename].groups and name == "motion":
            inset = dataset[filename].groups["inset"]
            iax = ax.inset_axes([0.6, 0.12, 0.36, 0.35])
            iax.plot(*inset.values.T, linewidth=0.8)
            iax.set_title("Native inset series", fontsize=7)
            iax.tick_params(labelsize=6)
        if filename == "Fig4_PurcellBot.csv" and name == "motion":
            iax = ax.inset_axes([0.6, 0.12, 0.36, 0.35])
            iax.plot(x, group.values[:, 2], linewidth=0.6)
            iax.set_title("Speed (µm/s) vs time (s)", fontsize=7)
            iax.tick_params(labelsize=6)
    fig.suptitle(
        "Reynolds (2022) local source overview — native axes, acquisition order and offsets\n"
        "S2C Current (µm) header corrected to µA from the published figure axis; values unchanged"
    )
    fig.savefig(output / "dataset_overview.png", dpi=150)
    plt.close(fig)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source-dir",
        required=True,
        type=Path,
        help="Read-only local directory containing the six named CSV files",
    )
    parser.add_argument(
        "--output", required=True, type=Path, help="Directory for derived JSON/PNGs"
    )
    parser.add_argument(
        "--historical-fit",
        type=Path,
        default=Path(__file__).parent / "results/published/pv_fit.json",
    )
    args = parser.parse_args(argv)
    if args.output.resolve().is_relative_to(args.source_dir.resolve()):
        parser.error("Use an output directory outside the read-only source directory")
    if args.output.exists():
        if not args.output.is_dir():
            parser.error("Output destination is an existing file; choose a fresh directory")
        if any(args.output.iterdir()):
            parser.error("Output directory is not empty; choose a fresh or empty directory")
    dataset = load_dataset(args.source_dir)
    comparison, model = compare_pv(dataset, args.historical_fit)
    report = {
        "analysis_code_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "status": "Derived comparison only; historical model unchanged; no new fit or simulation",
        "source_provenance": {
            "description": "Six local CSVs supplied by user as Reynolds (2022) data",
            "user_claimed_repository": "Zenodo; source identity and redistribution license not independently verified",
            "article_doi": "10.1126/scirobotics.abq2296",
            "raw_files_copied": False,
        },
        "ingestion": "Explicit column groups; UTF-8-sig or Windows-1252 decoding; finite complete "
        "rows with trailing group padding only. No sorting, deduplication or offsets.",
        "source_header_override": {
            "file": "FigS2_CircuitTesting.csv",
            "column_zero_based": 10,
            "literal_header": "Current (µm)",
            "interpreted_unit": "µA",
            "evidence": "Supplementary Fig. S2C right y-axis explicitly labels Current (µA); "
            "visually checked by coordinator from local supplement page 8 render.",
            "policy": "Literal header and native numeric values retained; SI current would be native * 1e-6.",
        },
        "measurement_context": {
            "Fig3_PurcellBot.csv": "Purcell motion, 660 nm laser (main paper Fig. 3)",
            "Fig4_PurcellBot.csv": "Filename retained literally; paper Fig. 4 is Antbot, 600 nm LED",
            "Fig5_Dogbot.csv": "Dogbot motion, 660 nm laser (main paper Fig. 5)",
            "FigS2_CircuitTesting.csv": "Circuit characterization; 660 nm illumination. "
            "S2A lowest-frequency setting; S2D nominal 8 Hz setting. "
            "A sun denotes 1 kW/m², not a standard solar spectrum.",
            "context_evidence": "Main paper Fig. 3–5 and supplementary Fig. S2 captions, "
            "locally provided reference documents; no new measurement inferred.",
        },
        "datasets": dataset_summary(dataset),
        "pv_comparison": comparison,
        "limitations": [
            "The literal S2C header Current (µm) is preserved; figure-confirmed µA override is explicit.",
            "S2C voltage/current describe output amplitudes, not PV Voc or PV IV.",
            "S2E characterizes large actuator PVs; it does not calibrate small logic PVs or physical TCAD parameters.",
            "Historical 300 K and 1 sun=1000 W/m² are explicit comparison assumptions/context.",
            "No uncertainties, unique monotone IV curve or acquisition sweep timing are provided for S2E.",
            "Observed MPP and local zero crossings are sampling/noise dependent; no unique measured Voc inferred.",
            "No license or redistribution rights inferred from possession of these local files.",
        ],
    }
    args.output.mkdir(parents=True, exist_ok=True)
    write_plots(dataset, model, args.output)
    (args.output / "comparison.json").write_text(
        json.dumps(report, indent=2, allow_nan=False) + "\n"
    )
    print(
        json.dumps(
            {
                "output": str(args.output),
                "files": len(dataset),
                "iv_points_per_branch": {
                    k: v["errors_by_sample"]["all"]["points"]
                    for k, v in comparison["branches"].items()
                },
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
