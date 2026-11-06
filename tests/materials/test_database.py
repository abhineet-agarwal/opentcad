"""Tests for the material parameter database."""
import pytest
from opentcad.materials.database import load_material, MaterialParams

def test_load_silicon():
    si = load_material("Si")
    assert isinstance(si, MaterialParams)
    assert si.symbol == "Si"

def test_silicon_mobility_values():
    si = load_material("Si")
    assert abs(si.mobility_constant.electron_cm2_Vs - 1350.0) < 1.0
    assert abs(si.mobility_constant.hole_cm2_Vs - 480.0) < 1.0

def test_silicon_bandgap():
    si = load_material("Si")
    assert abs(si.band_structure.Eg_eV_300K - 1.124) < 0.01

def test_silicon_ni():
    si = load_material("Si")
    assert 5e9 < si.band_structure.ni_cm3_300K < 2e10

def test_missing_material_raises():
    with pytest.raises(FileNotFoundError, match="unobtainium"):
        load_material("unobtainium")

def test_raw_dict_available():
    si = load_material("Si")
    assert "bandgap" in si.raw


# ---- no silent silicon values -----------------------------------------------------
import copy

import yaml as _yaml

from opentcad.materials.database import (MaterialFileError, PARAMS_DIR,
                                         params_from_dict)


def _si_raw():
    return _yaml.safe_load((PARAMS_DIR / "Si.yaml").read_text())


def test_silicon_file_is_complete():
    assert load_material("Si").defaulted == []


def test_semiconductor_missing_required_fields_is_an_error():
    raw = _si_raw()
    del raw["ni_cm3_300K"]
    del raw["mobility_constant"]
    with pytest.raises(MaterialFileError) as info:
        params_from_dict(raw, "X")
    msg = str(info.value)
    assert "ni_cm3_300K" in msg and "mobility_constant.electron_cm2_Vs" in msg


def test_insulator_needs_only_permittivity():
    p = params_from_dict({"is_insulator": True, "permittivity_relative": 7.5}, "Ox")
    assert p.band_structure.permittivity_relative == 7.5
    with pytest.raises(MaterialFileError, match="permittivity_relative"):
        params_from_dict({"is_insulator": True}, "Ox")


def test_optional_blocks_are_recorded_when_filled_in():
    raw = _si_raw()
    del raw["mobility_klaassen"]
    del raw["recombination"]["B_rad_cm3_per_s"]
    raw["avalanche"] = {"a_n_per_cm": 1.0}
    p = params_from_dict(raw, "X")
    assert "mobility_klaassen" in p.defaulted
    assert "recombination.B_rad_cm3_per_s" in p.defaulted
    assert "avalanche.b_n_V_per_cm" in p.defaulted
    assert "avalanche.a_n_per_cm" not in p.defaulted
    assert p.avalanche.a_n_per_cm == 1.0


def test_radiative_coefficient_is_read_from_the_file():
    raw = _si_raw()
    raw["recombination"]["B_rad_cm3_per_s"] = 1.1e-10
    assert params_from_dict(raw, "X").recombination.B_rad_cm3_per_s == 1.1e-10


@pytest.mark.requires_devsim
def test_solver_refuses_models_on_defaulted_parameters(simple_si_meshfield):
    from opentcad.device.models import Auger, ConstantMobility, Klaassen
    from opentcad.device.physics import PhysicsConfig
    from opentcad.device.solver import DeviceSolver
    raw = _si_raw()
    del raw["mobility_klaassen"]
    del raw["recombination"]["Cn_cm6_per_s"]
    params = params_from_dict(raw, "Si", source="test")
    s = DeviceSolver(simple_si_meshfield, {"Silicon": params},
                     physics=PhysicsConfig(mobility=Klaassen(), recombination=[Auger()]))
    with pytest.raises(ValueError) as info:
        s.solve_equilibrium()
    msg = str(info.value)
    assert "Klaassen needs mobility_klaassen" in msg
    assert "Auger needs recombination.Cn_cm6_per_s" in msg
    ok = DeviceSolver(simple_si_meshfield, {"Silicon": copy.deepcopy(params)},
                      physics=PhysicsConfig(mobility=ConstantMobility()))
    ok.solve_equilibrium()                   # constant mobility + SRH: all given
