"""opentcad.calibrate: the least-squares fit and the material-file helpers."""
import math

import numpy as np
import pytest
import yaml

from opentcad.calibrate import Parameter, apply_overrides, fit, write_material_variant
from opentcad.materials.database import load_material

X = np.linspace(0.5, 3.0, 12)
TRUE = {"a": 2.5e3, "b": 1.7}


def power_law(values):
    """Module-level so worker processes can import it."""
    return values["a"] * X ** values["b"] / (TRUE["a"] * X ** TRUE["b"]) - 1.0


def test_parameter_checks_its_bounds():
    with pytest.raises(ValueError, match="outside"):
        Parameter("x", 5.0, 1.0, 2.0)
    with pytest.raises(ValueError, match="lower > 0"):
        Parameter("x", 1.0, 0.0, 2.0)
    p = Parameter("x", 3.0, -10.0, 10.0, log=False)
    assert p.from_internal(p.to_internal(3.0)) == pytest.approx(3.0)
    with pytest.raises(ValueError, match="step"):
        Parameter("x", 1.0, 0.1, 2.0, step=0.0)


def test_a_parameter_can_set_its_own_step():
    params = [Parameter("a", 1e3, 1e1, 1e5, step=0.001),
              Parameter("b", 1.0, 0.0, 3.0, log=False, step=1e-4)]
    res = fit(power_law, params, log=None)
    assert res.values["b"] == pytest.approx(TRUE["b"], abs=1e-3)
    # The first Jacobian probes a by a factor 10^0.001 and b by 1e-4.
    probes = [e.values for e in res.evaluations[1:3]]
    assert round(math.log10(probes[0]["a"] / 1e3), 9) == 0.001
    assert round(probes[1]["b"] - 1.0, 9) == 1e-4


def test_fit_recovers_known_parameters():
    params = [Parameter("a", 1e3, 1e1, 1e5), Parameter("b", 1.0, 0.0, 3.0, log=False)]
    res = fit(power_law, params, log=None)
    assert res.success
    assert res.values["a"] == pytest.approx(TRUE["a"], rel=1e-3)
    assert res.values["b"] == pytest.approx(TRUE["b"], abs=1e-3)
    assert res.rms < 1e-3 < res.initial_rms        # the default tolerance is 1e-3
    assert res.initial_values == {"a": 1e3, "b": 1.0}
    assert res.evaluations[0].values == {"a": pytest.approx(1e3), "b": 1.0}
    assert res.correlation.shape == (2, 2)
    assert res.to_dict()["parameters"][0]["fitted"] == pytest.approx(TRUE["a"], rel=1e-3)
    assert res.at_bound == []


def test_fit_in_worker_processes_matches_serial():
    params = [Parameter("a", 1e3, 1e1, 1e5), Parameter("b", 1.0, 0.0, 3.0, log=False)]
    serial = fit(power_law, params, log=None)
    parallel = fit(power_law, params, workers=2, log=None)
    assert parallel.values["a"] == pytest.approx(serial.values["a"], rel=1e-9)
    assert parallel.values["b"] == pytest.approx(serial.values["b"], rel=1e-9)


def test_a_bound_that_stops_the_fit_is_reported():
    res = fit(power_law, [Parameter("a", 1e3, 1e1, 2e3), Parameter("b", 1.0, 0.0, 3.0, log=False)],
              log=None)
    assert res.values["a"] == pytest.approx(2e3)
    assert res.at_bound == ["a"]


def test_a_failed_run_is_an_error():
    with pytest.raises(ValueError, match="not a finite vector"):
        fit(lambda v: [math.nan], [Parameter("a", 1.0, 0.1, 10.0)], log=None)


def test_apply_overrides_sets_material_fields():
    si = load_material("Si")
    out = apply_overrides(si, {"mobility_lombardi.delta_e": 2e18,
                               "velocity_saturation.vsat_e_cm_s": 1.1e7})
    assert out.mobility_lombardi.delta_e == 2e18
    assert out.velocity_saturation.vsat_e_cm_s == 1.1e7
    assert out.raw["mobility_lombardi"]["delta_e"] == 2e18
    assert si.mobility_lombardi.delta_e == 3.58e18           # the original is untouched
    assert out.mobility_klaassen == si.mobility_klaassen and out.defaulted == []
    with pytest.raises(KeyError, match="not a material parameter"):
        apply_overrides(si, {"mobility_lombardi.nope": 1.0})
    with pytest.raises(ValueError, match="block.field"):
        apply_overrides(si, {"delta_e": 1.0})


def test_material_variant_loads_as_a_process(tmp_path, monkeypatch):
    from opentcad import plugins
    monkeypatch.setattr(plugins, "_iter_entry_points", lambda: [])
    plugins._reset_for_tests()
    try:
        path = write_material_variant(
            tmp_path / "fab" / "Si.yaml", load_material("Si"),
            {"mobility_lombardi.B_e": 5e7},
            calibration={"status": "fitted", "calibrated_against": "a test"})
        assert path.read_text().startswith("# Silicon — a calibrated variant of Si.yaml")
        plugins.register_data_dir("materials", tmp_path)
        fab = load_material("Si", process="fab")
        assert fab.mobility_lombardi.B_e == 5e7
        assert fab.mobility_lombardi.C_e == load_material("Si").mobility_lombardi.C_e
        assert fab.raw["calibration"] == {"status": "fitted", "calibrated_against": "a test"}
        assert fab.defaulted == []
        assert yaml.safe_load(path.read_text())["symbol"] == "Si"
    finally:
        plugins._reset_for_tests()
