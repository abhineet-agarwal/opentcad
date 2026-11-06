"""
opentcad.plugins — registries for process steps, device analyses, data
folders, and entry-point discovery.
"""
import textwrap
import warnings
from dataclasses import dataclass

import numpy as np
import pytest

from opentcad import plugins
from opentcad.geometry.formats import Material
from opentcad.geometry.structure import Structure
from opentcad.process.topography import Recipe


@pytest.fixture(autouse=True)
def _clean_registry(monkeypatch):
    # No installed entry points leak into these tests.
    monkeypatch.setattr(plugins, "_iter_entry_points", lambda: [])
    plugins._reset_for_tests()
    yield
    plugins._reset_for_tests()


@dataclass(frozen=True)
class UniformAcceptor:
    """Test plugin step: add a uniform acceptor concentration."""
    conc_cm3: float


def _apply_uniform_acceptor(mf, step):
    mf.Na = mf.Na + step.conc_cm3
    return {"added_cm3": step.conc_cm3}


def _small_structure():
    return (Structure(width_um=1.0, name="plug")
            .add_substrate("body", 0.5, Material.SI, doping_Na=1e15)
            .add_contact("top", 0.0, 1.0, "body", surface="top")
            .add_contact("bottom", 0.0, 1.0, "body", surface="bottom"))


# ---- built-ins ---------------------------------------------------------------
def test_builtins_registered_through_the_same_registry():
    steps = plugins.registered_steps()
    assert {n: h.stage for n, h in steps.items()} == {
        "Deposit": "topography", "Etch": "topography", "Oxidize": "topography",
        "Implant": "doping", "Anneal": "doping"}
    assert all(h.source == "opentcad" for h in steps.values())
    assert plugins.available_analyses() == ["ac", "cv", "fields", "iv", "transient"]


def test_builtins_come_back_after_reset():
    plugins._reset_for_tests()
    assert "Implant" in plugins.registered_steps()


# ---- process steps -------------------------------------------------------------
def test_register_step_validation():
    with pytest.raises(TypeError):
        plugins.register_step(UniformAcceptor(1.0), stage="doping",
                              apply=_apply_uniform_acceptor)
    with pytest.raises(ValueError, match="stage"):
        plugins.register_step(UniformAcceptor, stage="lithography",
                              apply=_apply_uniform_acceptor)
    plugins.register_step(UniformAcceptor, stage="doping",
                          apply=_apply_uniform_acceptor)
    with pytest.raises(ValueError, match="already registered"):
        plugins.register_step(UniformAcceptor, stage="doping",
                              apply=_apply_uniform_acceptor)
    plugins.register_step(UniformAcceptor, stage="doping",
                          apply=_apply_uniform_acceptor, replace=True)


def test_plugin_doping_step_runs_in_run_recipe():
    from opentcad.process import run_recipe
    plugins.register_step(UniformAcceptor, stage="doping",
                          apply=_apply_uniform_acceptor,
                          describe=lambda s: f"uniform Na +{s.conc_cm3:.0e}")
    recipe = (Recipe("plug")
              .add(UniformAcceptor(2e16))
              .implant("As", 30, 1e14))
    assert "uniform Na +2e+16" in recipe.summary()
    out = run_recipe(_small_structure(), recipe, mesh_size_um=0.1)
    assert out.topography_state is None              # doping-only recipe
    assert np.all(out.meshfield.Na >= 2e16 + 1e15 - 1.0)
    assert [type(s).__name__ for s, _ in out.doping_result.steps] == [
        "UniformAcceptor", "Implant"]
    assert out.doping_result.steps[0][1] == {"added_cm3": 2e16}
    assert out.doping_result.n_implants == 1


def test_unregistered_step_is_rejected():
    from opentcad.process.doping import apply_doping_recipe
    with pytest.raises(TypeError, match="register_step"):
        Recipe().add(UniformAcceptor(1e16))
    recipe = Recipe()
    recipe.steps.append(UniformAcceptor(1e16))        # bypasses add()
    assert "UniformAcceptor(conc_cm3=" in recipe.summary()
    mf = _small_structure().to_meshfield(mesh_size_um=0.2)
    with pytest.raises(TypeError, match="UniformAcceptor"):
        apply_doping_recipe(mf, recipe)


def test_plugin_topography_step_runs_in_simulate():
    pytest.importorskip("viennals")
    from opentcad.process import run_recipe

    @dataclass(frozen=True)
    class Probe:
        tag: str

    seen = []
    plugins.register_step(Probe, stage="topography",
                          apply=lambda state, step: seen.append(
                              (step.tag, len(state.layers))))
    recipe = (Recipe("probe")
              .add(Probe("before"))
              .deposit(Material.SIO2, 0.02)
              .add(Probe("after")))
    out = run_recipe(_small_structure(), recipe, mesh_size_um=0.1)
    assert out.topography_state is not None
    assert seen == [("before", 1), ("after", 2)]
    assert out.doping_result.steps == []


# ---- analyses ------------------------------------------------------------------
def test_register_analysis_validation():
    with pytest.raises(ValueError):
        plugins.register_analysis("", lambda s: None)
    with pytest.raises(TypeError):
        plugins.register_analysis("x", 3)
    with pytest.raises(ValueError, match="already registered"):
        plugins.register_analysis("iv", lambda s: None)
    with pytest.raises(KeyError, match="available"):
        plugins.get_analysis("nope")


@pytest.mark.requires_devsim
def test_plugin_analysis_runs_on_solver(simple_si_meshfield):
    from opentcad.device.solver import DeviceSolver
    from opentcad.materials.database import load_material

    def forward_current(solver, *, contact, volts):
        solver.set_contact_voltage(contact, 0.0)
        solver.solve_dc()
        out = []
        for v in volts:
            solver.set_contact_voltage(contact, v)
            solver.solve_dc()
            out.append(solver.contact_current_A_per_cm(contact))
        return out

    plugins.register_analysis("forward_current", forward_current)
    solver = DeviceSolver(simple_si_meshfield, {"Silicon": load_material("Si")})
    with pytest.raises(RuntimeError, match="solve_equilibrium"):
        solver.set_contact_voltage("anode", 0.1)
    solver.solve_equilibrium()
    i = solver.run("forward_current", contact="anode", volts=[0.1, 0.2, 0.3])
    assert abs(i[2]) > abs(i[1]) > abs(i[0]) > 0          # forward diode
    v_iv, i_iv = solver.run("iv", anode_contact="anode",
                            cathode_contact="cathode", v_start=0.0,
                            v_end=0.3, v_step=0.1)
    assert np.allclose(np.abs(i_iv[1:]), np.abs(i), rtol=1e-6)
    with pytest.raises(KeyError):
        solver.run("nope")


# ---- data folders ---------------------------------------------------------------
_SB_IMPLANT = textwrap.dedent("""\
    # Test fixture only: made-up moments, not literature values.
    species: antimony
    symbol: Sb
    target: Si
    dopant_kind: donor
    moments:
      - {energy_keV: 10, Rp_um: 0.010, dRp_um: 0.004, gamma: 0.0, beta: 3.0}
      - {energy_keV: 100, Rp_um: 0.050, dRp_um: 0.015, gamma: 0.0, beta: 3.0}
""")
_SB_DIFFUSION = textwrap.dedent("""\
    # Test fixture only: made-up coefficients.
    species: antimony
    symbol: Sb
    intrinsic: {D0_cm2s: 1.0, Ea_eV: 4.0}
""")


def test_dopant_folder_adds_a_species(tmp_path):
    from opentcad.process.doping import (apply_implant, available_species,
                                         diffusivity_intrinsic, moments_for)
    from opentcad.process.doping.pearson_iv import canonicalize_species
    with pytest.raises(ValueError, match="Unknown implant species"):
        canonicalize_species("Sb")
    (tmp_path / "Sb_in_Si.yaml").write_text(_SB_IMPLANT)
    (tmp_path / "Sb_diffusion.yaml").write_text(_SB_DIFFUSION)
    plugins.register_data_dir("dopants", tmp_path)
    assert canonicalize_species("Sb") == "antimony"
    assert "antimony" in available_species()
    assert moments_for("sb", 10).Rp_um == pytest.approx(0.010)
    assert diffusivity_intrinsic("Sb", 1273.15) > 0
    mf = _small_structure().to_meshfield(mesh_size_um=0.05)
    apply_implant(mf, "Sb", 50, 1e14)
    assert mf.get_species("antimony").max() > 0
    assert mf.Nd.max() > 0


def test_dopant_folder_cannot_redefine_a_builtin(tmp_path):
    from opentcad.process.doping.pearson_iv import canonicalize_species
    clash = _SB_IMPLANT.replace("antimony", "boron").replace("Sb", "Bx")
    (tmp_path / "Bx_in_Si.yaml").write_text(clash)
    plugins.register_data_dir("dopants", tmp_path)
    with pytest.raises(ValueError, match="defined in both"):
        canonicalize_species("B")


def test_material_folder_adds_and_refuses_duplicates(tmp_path):
    from opentcad.materials.database import load_material
    (tmp_path / "TestOx.yaml").write_text("is_insulator: true\npermittivity_relative: 7.5\n")
    (tmp_path / "Si.yaml").write_text("permittivity_relative: 1.0\n")
    plugins.register_data_dir("materials", tmp_path)
    assert load_material("TestOx").band_structure.permittivity_relative == 7.5
    with pytest.raises(ValueError, match="more than one data folder"):
        load_material("Si")


def test_register_data_dir_validation(tmp_path):
    with pytest.raises(ValueError, match="kind"):
        plugins.register_data_dir("meshes", tmp_path)
    with pytest.raises(FileNotFoundError):
        plugins.register_data_dir("materials", tmp_path / "missing")
    plugins.register_data_dir("materials", tmp_path)
    plugins.register_data_dir("materials", tmp_path)       # idempotent
    assert plugins.data_dirs("materials").count(tmp_path.resolve()) == 1


# ---- entry points -----------------------------------------------------------------
class _FakeEntryPoint:
    def __init__(self, name, target):
        self.name = name
        self._target = target

    def load(self):
        if isinstance(self._target, Exception):
            raise self._target
        return self._target


def test_entry_points_load_once_and_failures_warn(monkeypatch):
    calls = []

    def good():
        calls.append(1)
        plugins.register_analysis("from_plugin", lambda solver: "ok")

    eps = [_FakeEntryPoint("good", good),
           _FakeEntryPoint("broken", ImportError("no such module"))]
    monkeypatch.setattr(plugins, "_iter_entry_points", lambda: eps)
    plugins._reset_for_tests()
    with pytest.warns(RuntimeWarning, match="broken"):
        assert "from_plugin" in plugins.available_analyses()
    status = plugins.plugin_status()
    assert status["good"] == "loaded"
    assert status["broken"].startswith("ImportError")
    plugins.available_analyses()
    assert calls == [1]
    assert plugins._analyses["from_plugin"][1] == "plugin:good"


def test_entry_points_can_be_disabled(monkeypatch):
    def good():
        plugins.register_analysis("from_plugin", lambda solver: "ok")

    monkeypatch.setattr(plugins, "_iter_entry_points",
                        lambda: [_FakeEntryPoint("good", good)])
    monkeypatch.setenv(plugins.DISABLE_ENV_VAR, "1")
    plugins._reset_for_tests()
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        assert "from_plugin" not in plugins.available_analyses()
    assert plugins.plugin_status() == {}
