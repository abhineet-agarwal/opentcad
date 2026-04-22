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
