"""External-data contract tests use synthetic inputs, never redistributed CSVs."""

import csv
import json

import numpy as np
import pytest

from examples.microrobot.reynolds_data import (
    FileSpec,
    GroupSpec,
    SCHEMAS,
    compare_pv,
    dataset_summary,
    load_dataset,
    load_file,
    main,
    observed_iv_summary,
    terminal_current_A,
)
from opentcad.device.compact import SingleDiodePV


SIMPLE = FileSpec(
    "sample.csv",
    ("Time (s)", "Current (µA)", "Voltage (V)", "Current (nA)"),
    (GroupSpec("time", (0, 1)), GroupSpec("iv", (2, 3))),
)


def write_csv(path, headers, rows, encoding="utf-8-sig"):
    with path.open("w", encoding=encoding, newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(headers)
        writer.writerows(rows)


@pytest.mark.parametrize("encoding", ["utf-8-sig", "cp1252", "latin1"])
def test_independent_ragged_groups_keep_native_values_order_and_rows(tmp_path, encoding):
    path = tmp_path / "sample.csv"
    write_csv(path, SIMPLE.headers, [[2, -3, 1, 5], [0, -7, "", ""], [1, 8, "", ""]], encoding)
    loaded = load_file(path, SIMPLE)
    assert loaded.groups["time"].values.tolist() == [[2, -3], [0, -7], [1, 8]]
    assert loaded.groups["iv"].values.tolist() == [[1, 5]]
    assert loaded.groups["time"].source_rows.tolist() == [2, 3, 4]
    assert loaded.groups["iv"].source_rows.tolist() == [2]
    assert len(loaded.sha256) == 64
    assert loaded.size_bytes == path.stat().st_size
    assert not loaded.groups["time"].values.flags.writeable
    summary = dataset_summary({"sample.csv": loaded})["sample.csv"]["groups"]
    assert summary["time"]["axis_decreasing_steps"] == 1
    assert summary["iv"]["trailing_padding_rows"] == 2


@pytest.mark.parametrize(
    "rows,match",
    [
        ([[0, 1, 2, ""]], "partial group iv"),
        ([[0, 1, "", ""], [1, 2, 3, 4]], "resumes after padding"),
        ([[0, "broken", 2, 3]], "invalid number"),
        ([[0, "NaN", 2, 3]], "nonfinite number"),
        ([[0, "inf", 2, 3]], "nonfinite number"),
        ([[0, "-inf", 2, 3]], "nonfinite number"),
        ([[0, "1e9999", 2, 3]], "nonfinite number"),
        ([[0, 1, 2]], "expected 4 columns"),
        ([[0, 1, 2, 3, 4]], "expected 4 columns"),
        ([["", "", 2, 3]], "empty group time"),
    ],
)
def test_rejects_incomplete_malformed_nonfinite_and_internal_missingness(tmp_path, rows, match):
    path = tmp_path / "sample.csv"
    write_csv(path, SIMPLE.headers, rows)
    with pytest.raises(ValueError, match=match):
        load_file(path, SIMPLE)


def test_headers_and_csv_syntax_are_strict_but_unicode_micro_symbols_equivalent(tmp_path):
    path = tmp_path / "sample.csv"
    write_csv(path, [h.replace("µ", "μ") for h in SIMPLE.headers], [[0, 1, 2, 3]])
    assert load_file(path, SIMPLE).data_rows == 1
    write_csv(path, [h.replace("µA", "mA") for h in SIMPLE.headers], [[0, 1, 2, 3]])
    with pytest.raises(ValueError, match="headers differ"):
        load_file(path, SIMPLE)
    path.write_text(",".join(SIMPLE.headers) + '\n0,1,2,"unterminated\n')
    with pytest.raises(ValueError, match="malformed CSV"):
        load_file(path, SIMPLE)


def test_complete_six_file_registry_and_axis_mapping(tmp_path):
    for spec in SCHEMAS:
        rows = [["" for _ in spec.headers] for _ in range(3)]
        for index, group in enumerate(spec.groups):
            for row in range(3 if index == 0 else 1):
                for column in group.columns:
                    rows[row][column] = 10 * column + row
        write_csv(tmp_path / spec.filename, spec.headers, rows)
    dataset = load_dataset(tmp_path)
    assert len(dataset) == 6
    s2 = dataset["FigS2_CircuitTesting.csv"]
    assert len(s2.groups) == 8
    assert len(s2.groups["current_2_5sun"].values) == 3
    assert len(s2.groups["iv_1sun"].values) == 1
    s6 = dataset["FigS6_DogbotCircuit.csv"].groups["current_trace"]
    assert s6.headers[s6.spec.axis_column] == "Time (s)"


def test_microamp_conversion_and_historical_delivering_sign(tmp_path):
    spec = next(s for s in SCHEMAS if s.filename == "FigS2_CircuitTesting.csv")
    path = tmp_path / spec.filename
    # All columns are populated to exercise the exact source schema. IV currents
    # have the opposite sign from the reusable delivering-current model.
    model = SingleDiodePV(1e-16, 1.2, 150e-9, series_cells=2)
    voltage = np.array([0.0, 1.3, 0.7, 1.3])
    rows = np.ones((len(voltage), len(spec.headers)))
    for column, light in ((13, 0), (15, 1000)):
        rows[:, column] = voltage
        rows[:, column + 1] = -model.current_A(voltage, light) * 1e6
    write_csv(path, spec.headers, rows)
    loaded = load_file(path, spec)
    assert terminal_current_A(loaded.groups["iv_1sun"]) == pytest.approx(
        -model.current_A(voltage), abs=1e-22
    )
    with pytest.raises(ValueError, match="explicitly mapped"):
        terminal_current_A(loaded.groups["current_2_5sun"])
    historical = tmp_path / "fit.json"
    historical.write_text(json.dumps({"fitted_terminal_model": model.__dict__}))
    comparison, _ = compare_pv({spec.filename: loaded}, historical)
    for branch in comparison["branches"].values():
        assert branch["errors_by_sample"]["all"]["rms_A"] < 1e-21
        assert branch["occupied_25mV_bins"] == 3
    assert (
        comparison["branches"]["iv_1sun"]["direct_observations"]["observed_sample_mpp"][
            "delivered_current_A"
        ]
        > 0
    )


def test_multivalued_voltage_crossings_and_sample_mpp_do_not_sort_or_average():
    v = np.array([1.0, 1.0, 2.0, 0.0, 1.0])
    entering = np.array([-2.0, 2.0, 1.0, -3.0, -4.0]) * 1e-9
    result = observed_iv_summary(v, entering)
    assert result["repeated_voltage_values"] == 1
    assert result["repeated_voltage_max_current_span_A"] == pytest.approx(6e-9)
    assert result["zero_current_crossings"]["count"] == 2
    assert result["zero_current_crossings"]["voltage_range_V"] == pytest.approx([1.0, 1.5])
    assert result["observed_sample_mpp"] == {
        "sample_index_zero_based": 4,
        "voltage_V": 1.0,
        "delivered_current_A": 4e-9,
        "power_W": 4e-9,
    }
    assert result["closest_zero_current_sample"]["sample_index_zero_based"] == 2
    no_crossing = observed_iv_summary(v, np.ones(len(v)))
    assert no_crossing["zero_current_crossings"]["count"] == 0
    assert no_crossing["zero_current_crossings"]["voltage_range_V"] is None
    assert no_crossing["observed_sample_mpp"] is None


def test_requires_explicit_source_and_output_and_preserves_source_directory(tmp_path):
    with pytest.raises(SystemExit):
        main([])
    with pytest.raises(SystemExit):
        main(["--source-dir", str(tmp_path), "--output", str(tmp_path / "derived")])
    assert list(tmp_path.iterdir()) == []


def test_existing_output_archive_and_file_are_rejected_before_any_write(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    for spec in SCHEMAS:
        write_csv(source / spec.filename, spec.headers, [[0] * len(spec.headers)])
    snapshots = {path: path.read_bytes() for path in source.iterdir()}
    archive = tmp_path / "archive"
    archive.mkdir()
    marker = archive / "preserve.txt"
    marker.write_bytes(b"accepted results must survive\n")
    output_file = tmp_path / "existing-file"
    output_file.write_bytes(b"existing user file\n")
    for destination in (archive, output_file):
        with pytest.raises(SystemExit) as error:
            main(["--source-dir", str(source), "--output", str(destination)])
        assert error.value.code == 2
        assert {path: path.read_bytes() for path in source.iterdir()} == snapshots
        assert list(archive.iterdir()) == [marker]
        assert marker.read_bytes() == b"accepted results must survive\n"
        assert output_file.read_bytes() == b"existing user file\n"
