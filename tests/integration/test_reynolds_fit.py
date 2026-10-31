"""Synthetic checks for separate training-only S2E candidate fits."""

from dataclasses import asdict

import numpy as np
import pytest

from examples.microrobot.reynolds_data import GroupSpec, LoadedGroup, terminal_current_A
from examples.microrobot.reynolds_fit import (
    CURRENT_SCALE_A,
    HOLDOUT_REGIONS,
    IVBranch,
    entering_prediction,
    evaluate,
    fit_candidate,
    heldout_mask,
    main,
    occupied_bin_weights,
    training_branches,
)
from opentcad.device.compact import SingleDiodePV


def synthetic(offset=1.8e-9):
    model = SingleDiodePV(2e-16, 1.2, 150e-9, series_cells=2)
    # Deliberately repeated, acquisition-like reverse order; not a sorted curve.
    voltage = np.r_[np.linspace(-1.2, 1.35, 180), np.linspace(1.35, -1.2, 70), np.zeros(30)]
    branches = [
        IVBranch(name, voltage.copy(), entering_prediction(model, voltage, light, offset), light)
        for name, light in (("dark", 0.0), ("light", 1000.0))
    ]
    return model, branches


@pytest.mark.parametrize(
    "mode,offset", [("zero", 0.0), ("shared_fit", 1.8e-9), ("fixed_dark_median", 1.8e-9)]
)
def test_noiseless_parameter_recovery_and_joint_shared_offset_identifiability(mode, offset):
    actual, branches = synthetic(offset)
    model, fitted_offset, diagnostics = fit_candidate(branches, offset_mode=mode)
    assert model.saturation_A == pytest.approx(actual.saturation_A, rel=2e-5)
    assert model.ideality == pytest.approx(actual.ideality, rel=2e-6)
    assert model.photocurrent_A == pytest.approx(actual.photocurrent_A, rel=2e-7)
    assert fitted_offset == pytest.approx(offset, abs=1e-14)
    assert diagnostics["optimizer"]["chosen_jacobian_rank"] == (4 if mode == "shared_fit" else 3)
    assert diagnostics["training_equal_branch_bin_rms_A"] < 1e-13
    # Offset belongs to observation model, not physical Voc or MPP.
    assert diagnostics["device_only_Voc_1sun_V"] == pytest.approx(model.open_circuit_V())
    assert diagnostics["device_only_MPP_1sun_V_A_W"] == pytest.approx(model.maximum_power_point())
    assert len(diagnostics["optimizer"]["multistarts"]) == 3


def test_heldout_current_changes_cannot_affect_any_fit_input_or_fitted_parameter():
    _, branches = synthetic()
    changed = []
    for b in branches:
        current = b.entering_A.copy()
        current[heldout_mask(b.voltage_V)] += (
            np.linspace(1, 50, heldout_mask(b.voltage_V).sum()) * 1e-3
        )
        changed.append(IVBranch(b.name, b.voltage_V.copy(), current, b.irradiance_W_m2))
    for mode in ("zero", "shared_fit", "fixed_dark_median"):
        first = fit_candidate(branches, offset_mode=mode)
        second = fit_candidate(changed, offset_mode=mode)
        assert asdict(first[0]) == asdict(second[0])
        assert first[1] == second[1]
        assert first[2] == second[2]
    report = evaluate(changed, first[0], first[1])
    assert report["aggregate"]["heldout_combined"]["rms_A"] > 1e-3


def test_holdout_voltage_boundaries_and_training_masks_are_predeclared():
    assert HOLDOUT_REGIONS == ((0.90, 1.05), (1.15, 1.25))
    voltage = np.array([-0.5, 0.899, 0.9, 1.0, 1.05, 1.149, 1.15, 1.249, 1.25])
    assert heldout_mask(voltage).tolist() == [
        False,
        False,
        True,
        True,
        False,
        False,
        True,
        True,
        False,
    ]
    _, branches = synthetic()
    for before, after in zip(branches, training_branches(branches)):
        assert np.array_equal(after.voltage_V, before.voltage_V[~heldout_mask(before.voltage_V)])
        assert not np.any(heldout_mask(after.voltage_V))


def test_bin_objective_weights_native_points_without_collapsing_observations():
    voltage = np.array([-0.02, -0.01, 0.0, 0.01, 0.02, 0.03])
    weights, count = occupied_bin_weights(voltage, 0.025)
    assert count == 3
    assert weights == pytest.approx([1 / 6, 1 / 6, 1 / 9, 1 / 9, 1 / 9, 1 / 3])
    residual = np.array([1.0, 3.0, 2.0, 4.0, 6.0, 10.0])
    assert np.sum(weights * residual**2) == pytest.approx(np.mean([5.0, 56 / 3, 100.0]))
    assert CURRENT_SCALE_A == 1e-9  # Declared numerical scale, not sigma.
    more = np.r_[voltage, 0.03, 0.03]
    more_residual = np.r_[residual, 10.0, 10.0]
    w, _ = occupied_bin_weights(more, 0.025)
    assert np.sum(w * more_residual**2) == pytest.approx(np.sum(weights * residual**2))
    assert np.array_equal(voltage, [-0.02, -0.01, 0.0, 0.01, 0.02, 0.03])


@pytest.mark.parametrize("width", [0, -0.025, np.nan, np.inf])
def test_invalid_bin_widths_fail(width):
    with pytest.raises(ValueError, match="bin width"):
        occupied_bin_weights(np.array([0.0]), width)


def test_current_unit_sign_and_shared_offset_semantics():
    model, branches = synthetic()
    b = branches[1]
    native = np.column_stack((b.voltage_V, b.entering_A * 1e6))
    group = LoadedGroup(
        GroupSpec("iv_1sun", (15, 16)),
        ("Voltage 1 sun (V)", "Current 1 sun (µA)"),
        native,
        np.arange(len(native)) + 2,
    )
    assert terminal_current_A(group) == pytest.approx(b.entering_A, abs=1e-22)
    expected = -model.current_A(b.voltage_V, 1000.0) + 1.8e-9
    assert entering_prediction(model, b.voltage_V, 1000.0, 1.8e-9) == pytest.approx(expected)
    assert entering_prediction(model, 0.0, 1000.0, 1.8e-9) < 0
    assert entering_prediction(model, 0.0, 0.0, 1.8e-9) == pytest.approx(1.8e-9)


def test_evaluation_branch_and_aggregate_metrics_reconcile_with_fit_objective():
    _, branches = synthetic()
    model, offset, fit = fit_candidate(branches, offset_mode="shared_fit")
    metrics = evaluate(branches, model, offset)
    assert metrics["aggregate"]["train"]["equal_branch_bin_rms_A"] == pytest.approx(
        fit["training_equal_branch_bin_rms_A"], abs=1e-22
    )
    for b in branches:
        m = metrics["branches"][b.name]
        assert (
            m["all_diagnostic"]["points"] == m["train"]["points"] + m["heldout_combined"]["points"]
        )
        assert m["heldout_combined"]["points"] == sum(
            m[k]["points"] for k in m if k.startswith("heldout_") and k != "heldout_combined"
        )
    assert metrics["aggregate"]["heldout_combined"]["rms_A"] < 1e-13


def test_dark_and_light_are_both_required_for_identifiable_shared_offset():
    _, branches = synthetic()
    with pytest.raises(ValueError, match="dark and one-sun"):
        fit_candidate(branches[:1], offset_mode="shared_fit")
    with pytest.raises(ValueError, match="Unknown offset"):
        fit_candidate(branches, offset_mode="independent_light_offset")


def test_archive_guard_precedes_source_reads_and_preserves_existing_files(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    marker = source / "untouched.csv"
    marker.write_bytes(b"source sentinel\n")
    archive = tmp_path / "accepted"
    archive.mkdir()
    keep = archive / "accepted.json"
    keep.write_text('{"accepted":true}\n')
    existing = tmp_path / "user.txt"
    existing.write_bytes(b"user work\n")
    for destination in (archive, existing, source / "derived", source):
        with pytest.raises(SystemExit) as error:
            main(["--source-dir", str(source), "--output", str(destination)])
        assert error.value.code == 2
        assert marker.read_bytes() == b"source sentinel\n"
        assert keep.read_text() == '{"accepted":true}\n'
        assert existing.read_bytes() == b"user work\n"
    assert list(source.iterdir()) == [marker]


def test_main_demands_explicit_source_and_output():
    with pytest.raises(SystemExit):
        main([])
