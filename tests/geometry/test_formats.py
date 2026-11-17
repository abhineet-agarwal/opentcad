"""Tests for MeshField — the foundational data format."""
import numpy as np
import pytest
import pyvista as pv
from opentcad.geometry.formats import ContactTag, Material, MeshField, ProcessStep


def make_tetra():
    pts = np.array([[0,0,0],[1,0,0],[.5,1,0],[.5,.5,1]], dtype=float)
    cells = np.array([4,0,1,2,3])
    ct = np.array([pv.CellType.TETRA])
    grid = pv.UnstructuredGrid(cells, ct, pts)
    grid.cell_data["material_id"] = np.array([int(Material.SI)], dtype=np.int32)
    return MeshField(grid=grid)


def test_construction():
    mf = make_tetra()
    assert mf.n_points == 4
    assert mf.n_cells == 1

def test_requires_material_id():
    pts = np.array([[0,0,0],[1,0,0],[.5,1,0],[.5,.5,1]], dtype=float)
    cells = np.array([4,0,1,2,3])
    grid = pv.UnstructuredGrid(cells, np.array([pv.CellType.TETRA]), pts)
    with pytest.raises(ValueError, match="material_id"):
        MeshField(grid=grid)

def test_doping_assignment():
    mf = make_tetra()
    nd = np.array([1e16, 1e16, 1e16, 1e16])
    na = np.array([1e15, 1e15, 1e15, 1e15])
    mf.Nd = nd; mf.Na = na
    assert mf.has_doping
    np.testing.assert_allclose(mf.Nd, nd)
    np.testing.assert_allclose(mf.Na, na)

def test_negative_doping_raises():
    mf = make_tetra()
    with pytest.raises(AssertionError):
        mf.Nd = np.array([-1e16, 1e16, 1e16, 1e16])

def test_get_missing_contact_raises():
    mf = make_tetra()
    with pytest.raises(KeyError):
        mf.get_contact("source")

def test_add_contact_replace():
    mf = make_tetra()
    mf.add_contact(ContactTag("drain", np.array([0])))
    mf.add_contact(ContactTag("drain", np.array([1, 2])))
    assert len(mf.contacts) == 1
    np.testing.assert_array_equal(mf.get_contact("drain").boundary_nodes, [1, 2])

def test_save_load_roundtrip(tmp_path):
    mf = make_tetra()
    mf.Nd = np.array([1e16, 2e16, 3e16, 4e16])
    mf.Na = np.array([1e15]*4)
    mf.add_contact(ContactTag("anode", np.array([0, 1])))
    mf.process_history.append(ProcessStep("test", "B", {"dose": 1e13}))
    mf.metadata["key"] = "val"
    p = tmp_path / "mesh"
    mf.save(p)
    mf2 = MeshField.load(p)
    assert mf2.n_points == 4
    np.testing.assert_allclose(mf2.Nd, mf.Nd, rtol=1e-6)
    assert mf2.contacts[0].name == "anode"
    assert mf2.metadata["key"] == "val"
    assert mf2.process_history[0].species == "B"

def test_summary_runs():
    mf = make_tetra()
    s = mf.summary()
    assert "Silicon" in s


def test_species_fields_default_empty():
    mf = make_tetra()
    assert mf.species_names() == []
    np.testing.assert_array_equal(mf.get_species("boron"), np.zeros(4))


def test_species_fields_set_get_and_dont_touch_totals():
    mf = make_tetra()
    mf.Nd = np.full(4, 1e16)
    mf.set_species("phosphorus", np.full(4, 2e15))
    mf.set_species("arsenic", np.full(4, 3e15))
    assert mf.species_names() == ["arsenic", "phosphorus"]
    np.testing.assert_allclose(mf.get_species("arsenic"), 3e15)
    # Species fields are bookkeeping only; Nd is owned by the caller.
    np.testing.assert_allclose(mf.Nd, 1e16)
    with pytest.raises(AssertionError):
        mf.set_species("boron", np.array([-1.0, 0, 0, 0]))
    with pytest.raises(AssertionError):
        mf.set_species("boron", np.zeros(3))


def test_species_fields_survive_save_load(tmp_path):
    mf = make_tetra()
    mf.set_species("boron", np.array([1e15, 2e15, 3e15, 4e15]))
    p = tmp_path / "mesh"
    mf.save(p)
    mf2 = MeshField.load(p)
    assert mf2.species_names() == ["boron"]
    np.testing.assert_allclose(mf2.get_species("boron"), [1e15, 2e15, 3e15, 4e15])
    assert "boron" in mf2.summary()


# ---- save / load keeps every contact field ------------------------------------
def test_save_load_keeps_all_contact_fields(tmp_path):
    import json
    from opentcad.geometry.structure import Structure
    from opentcad.geometry.formats import MESHFIELD_FORMAT, Material, MeshField
    mf = (Structure(width_um=1.0, name="rt")
          .add_substrate("b", 0.5, Material.SI, doping_Na=1e17)
          .add_layer("ox", 0.005, Material.SIO2)
          .add_contact("gate", 0.2, 0.8, "ox", flat_band_shift_V=-0.564)
          .add_contact("body", 0, 1, "b", surface="bottom", contact_type="schottky",
                       work_function_eV=4.8)).to_meshfield(mesh_size_um=0.1)
    mf.save(tmp_path / "m")
    back = MeshField.load(tmp_path / "m")
    for a, b in zip(mf.contacts, back.contacts):
        assert (a.name, a.contact_type, a.work_function_eV, a.flat_band_shift_V) == \
               (b.name, b.contact_type, b.work_function_eV, b.flat_band_shift_V)
        assert np.array_equal(a.boundary_nodes, b.boundary_nodes)
    meta = json.loads((tmp_path / "m.json").read_text())
    assert meta["meshfield_format"] == MESHFIELD_FORMAT
    # Files written before versioning (no format, no flat_band_shift_V) still load.
    for c in meta["contacts"]:
        del c["flat_band_shift_V"]
    del meta["meshfield_format"]
    (tmp_path / "m.json").write_text(json.dumps(meta))
    assert MeshField.load(tmp_path / "m").contacts[0].flat_band_shift_V == 0.0
    meta["meshfield_format"] = MESHFIELD_FORMAT + 1
    (tmp_path / "m.json").write_text(json.dumps(meta))
    with pytest.raises(ValueError, match="MeshField format"):
        MeshField.load(tmp_path / "m")
