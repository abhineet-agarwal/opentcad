"""Focused guards for the bounded, fixed-structure direct-DD feasibility check."""

import copy
import inspect
from pathlib import Path

import numpy as np
import pytest

from examples.microrobot import pv
from examples.microrobot.pv_calibration import (
    VOLTAGE_GRID,
    archive_audit,
    baseline_agreement,
    evaluate,
    low_bias_difference,
    main,
    prediction,
    reflectance_decision,
    shared_offset,
    validate_curve,
)
from examples.microrobot.reynolds_data import GroupSpec, LoadedGroup
from examples.microrobot.reynolds_fit import heldout_mask


def groups(offset=2e-9):
    # Different acquisition orders, repeated voltages and unmatched row counts.
    result = {}
    for name, v, current in (
        ("iv_dark", [0.03, -0.2, 0.01, 0.03, 0.93, 1.2, 1.3], 0),
        ("iv_1sun", [0.02, 0.04, 0.02, -0.1, 0.95, 1.19, 1.3], -150e-9),
    ):
        headers = (("Voltage 0 sun (V)", "Current 0 sun (µA)") if name == "iv_dark"
                   else ("Voltage 1 sun (V)", "Current 1 sun (µA)"))
        values = np.column_stack((v, np.full(len(v), (current + offset) * 1e6)))
        values.setflags(write=False)
        result[name] = LoadedGroup(GroupSpec(name, (0, 1)), headers, values,
                                  np.arange(2, len(v) + 2))
    return result


def curve():
    i = 1e-10 * (1 - VOLTAGE_GRID / .5)
    terminals = np.column_stack((-i, i))
    return {"voltage_V": VOLTAGE_GRID.tolist(), "delivered_A_per_um2": i.tolist(),
            "irradiance_W_m2": 1000, "absorbed_photon_limit_A_per_um2": 2e-10,
            "contact_imbalance_relative": 0,
            "terminal_entering_A_per_um2": terminals.tolist(),
            "contact_imbalance_absolute_A_per_um2": np.zeros(len(i)).tolist(),
            "contact_imbalance_relative_by_voltage": np.zeros(len(i)).tolist()}


def test_equal_voltage_bins_cancel_shared_offset_without_mutating_native_data():
    source = groups()
    before = {k: g.values.copy() for k, g in source.items()}
    first = low_bias_difference(source)
    shifted = low_bias_difference(groups(offset=7e-9))
    assert first["photocurrent_target_A"] == pytest.approx(150e-9)
    assert shifted["photocurrent_target_A"] == pytest.approx(first["photocurrent_target_A"])
    assert first["bins"][0]["branches"]["iv_dark"]["points"] == 1
    assert first["bins"][0]["branches"]["iv_1sun"]["points"] == 2
    for name in source:
        assert np.array_equal(source[name].values, before[name])


def test_prior_holdout_currents_cannot_change_target_or_shared_offset():
    source = groups()
    changed = {}
    for name, g in source.items():
        values = g.values.copy()
        values[heldout_mask(values[:, 0]), 1] += 10000
        changed[name] = LoadedGroup(g.spec, g.headers, values, g.source_rows)
    assert low_bias_difference(source) == low_bias_difference(changed)
    assert shared_offset(curve(), source) == shared_offset(curve(), changed)


def test_series_scaling_and_no_negative_voltage_extrapolation():
    c = curve()
    assert prediction(c, [0, .4]) == pytest.approx([-54e-9, -32.4e-9])
    with pytest.raises(ValueError, match="no extrapolation"):
        prediction(c, [-1e-15])
    with pytest.raises(ValueError, match="no extrapolation"):
        prediction(c, [1.401])


def test_unphysical_reflectance_stops_and_bracketed_candidate_stays_bounded():
    impossible = reflectance_decision(150e-9, 104.45e-9)
    assert not impossible["bracketed"]
    assert impossible["linearized_required_effective_reflectance"] < 0
    assert impossible["relative_shortfall_at_R0"] == pytest.approx(.3036666667)
    feasible = reflectance_decision(70e-9, 100e-9)
    assert feasible["bracketed"]
    assert feasible["linearized_required_effective_reflectance"] == pytest.approx(.3)
    for target in (0, 100e-9):
        assert reflectance_decision(target, 100e-9)["bracketed"]
    assert not reflectance_decision(-1e-9, 100e-9)["bracketed"]


def test_complete_grid_photon_budget_and_local_terminal_conservation_required():
    c = curve()
    assert validate_curve(c, fresh=True)["points"] == 29
    incomplete = copy.deepcopy(c)
    incomplete["voltage_V"].pop()
    with pytest.raises(ValueError, match="grid"):
        validate_curve(incomplete, fresh=True)
    nonfinite = copy.deepcopy(c)
    nonfinite["delivered_A_per_um2"][5] = float("nan")
    with pytest.raises(ValueError, match="nonfinite"):
        validate_curve(nonfinite, fresh=True)
    overbudget = copy.deepcopy(c)
    overbudget["absorbed_photon_limit_A_per_um2"] = 0.5e-10
    with pytest.raises(ValueError, match="photon"):
        validate_curve(overbudget, fresh=True)
    unbalanced = copy.deepcopy(c)
    unbalanced["terminal_entering_A_per_um2"][3][1] += 1e-12
    unbalanced["contact_imbalance_absolute_A_per_um2"][3] = 1e-12
    with pytest.raises(ValueError, match="conservation"):
        validate_curve(unbalanced, fresh=True)


def test_app_local_observer_returns_original_current_and_records_sweep_only(monkeypatch):
    calls = []

    def read(self, contact):
        calls.append(contact)
        return {"p": -3.0, "n": 3.0}[contact]

    def sweep(self, *args, **kwargs):
        return [0., .025], [self._get_contact_current("p") for _ in range(2)]

    monkeypatch.setattr(pv.DeviceSolver, "_get_contact_current", read)
    monkeypatch.setattr(pv.DeviceSolver, "iv_sweep", sweep)
    instance = object.__new__(pv._AuditedPVSolver)
    voltage, current = instance.iv_sweep("p", "n", 0, .025, .025)
    assert voltage == [0, .025]
    assert current == [-3, -3]
    assert instance.terminal_samples_A_per_cm == [(-3, 3), (-3, 3)]
    instance._get_contact_current("p")
    assert len(instance.terminal_samples_A_per_cm) == 2
    assert calls == ["p", "n", "p", "n", "p"]
    assert inspect.signature(pv.characterize).parameters["reflectance"].default == .3


def test_archived_curves_conditionally_reusable_and_drift_rejected():
    archive, audit = archive_audit(Path(__file__).parents[2] / "examples/microrobot/results/pv.json")
    assert audit["checks"]["dark"]["complete_grid"]
    assert baseline_agreement(archive["light"], archive["light"])["passed"]
    changed = copy.deepcopy(archive["light"])
    changed["delivered_A_per_um2"][0] *= 1.01
    with pytest.raises(ValueError, match="differs"):
        baseline_agreement(changed, archive["light"])


def test_residuals_retain_holdouts_exclude_negative_and_report_both_branches():
    result = evaluate(curve(), curve(), groups(), 0)
    for name in ("iv_dark", "iv_1sun"):
        assert result[name]["excluded_negative_voltage_points"] == 1
        assert result[name]["heldout_combined"]["points"] == 2
        assert result[name]["train_nonnegative"]["points"] == 4


def test_nonempty_archive_refused_before_reading_source(tmp_path):
    output = tmp_path / "old"
    output.mkdir()
    sentinel = output / "keep.txt"
    sentinel.write_text("preserve")
    with pytest.raises(SystemExit) as error:
        main(["--source-dir", str(tmp_path / "absent"), "--output", str(output)])
    assert error.value.code == 2
    assert sentinel.read_text() == "preserve"
