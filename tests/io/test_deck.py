"""
Simulation files (opentcad.io.deck) and the CLI.
"""
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pytest

from opentcad import plugins
from opentcad.cli import main as cli_main
from opentcad.geometry.formats import Material
from opentcad.io.deck import (DeckError, deck_from_dict, dumps_deck, load_deck,
                              parse_material, run_deck, save_deck)

DECKS = Path(__file__).resolve().parents[2] / "examples" / "decks"


@pytest.fixture(autouse=True)
def _clean_registry(monkeypatch):
    monkeypatch.setattr(plugins, "_iter_entry_points", lambda: [])
    plugins._reset_for_tests()
    yield
    plugins._reset_for_tests()


def _minimal(**extra):
    d = {"name": "m",
         "structure": {"width_um": 1.0,
                       "layers": [{"name": "body", "thickness_um": 0.5,
                                   "material": "Si", "doping_Na": 1e16}],
                       "contacts": [{"name": "top", "x_um": [0, 1],
                                     "layer": "body"},
                                    {"name": "bot", "x_um": [0, 1],
                                     "layer": "body", "surface": "bottom"}]}}
    d.update(extra)
    return d


def _problems(data):
    with pytest.raises(DeckError) as info:
        deck_from_dict(data)
    return dict(info.value.problems)


# ---- reading and writing ---------------------------------------------------------
@pytest.mark.parametrize("name", ["pn_diode.yaml", "nmos_implanted.yaml"])
def test_example_decks_load_and_round_trip(name, tmp_path):
    deck = load_deck(DECKS / name)
    again = deck_from_dict(deck.to_dict())
    assert again.to_dict() == deck.to_dict()
    for suffix in (".yaml", ".json"):
        path = save_deck(deck, tmp_path / f"copy{suffix}")
        assert load_deck(path).to_dict() == deck.to_dict()


def test_yaml_exponent_numbers_are_floats(tmp_path):
    path = tmp_path / "d.yaml"
    path.write_text(dumps_deck(deck_from_dict(_minimal())).replace(
        "1.0e+16", "1e16"))
    assert "1e16" in path.read_text()
    assert load_deck(path).structure.layers[0].doping_Na == 1e16


def test_structure_and_recipe_contents():
    deck = load_deck(DECKS / "nmos_implanted.yaml")
    s = deck.structure
    assert [l.name for l in s.layers] == ["p_body", "oxide"]
    assert s.layers[1].material is Material.SIO2
    assert s.regions[0].x_end == 0.5
    assert {c.name for c in s.contacts} == {"source", "drain", "gate", "body"}
    assert [type(st).__name__ for st in deck.recipe] == ["Implant"] * 4 + ["Anneal"]
    assert deck.recipe.steps[0].window_x_um == (0.0, 0.5)
    assert deck.analyses[0].args["hold_contacts"] == {"drain": 0.05}


def test_physics_models_round_trip():
    from opentcad.device.models import Canali, Klaassen, Lombardi
    data = _minimal(device={"physics": {
        "mobility": {"model": "lombardi", "e_normal_axis": "x",
                     "base": {"model": "canali", "base": "klaassen"}},
        "recombination": ["srh", "auger"], "bgn": "slotboom",
        "statistics": "fermi_dirac"}})
    deck = deck_from_dict(data)
    mob = deck.device.physics.mobility
    assert isinstance(mob, Lombardi) and mob.e_normal_axis == "x"
    assert isinstance(mob.base, Canali) and isinstance(mob.base.base, Klaassen)
    assert deck_from_dict(deck.to_dict()).to_dict() == deck.to_dict()
    assert deck.to_dict()["device"]["physics"]["recombination"] == ["srh", "auger"]


def test_material_names():
    assert parse_material("SiO2") is Material.SIO2
    assert parse_material("poly_si") is Material.POLY_SI
    assert parse_material("Silicon") is Material.SI
    with pytest.raises(ValueError, match="unknown material"):
        parse_material("Silicone")


# ---- problems ---------------------------------------------------------------------
def test_every_problem_is_reported_with_its_location():
    data = _minimal(colour="red",
                    recipe=[{"step": "implant", "species": "As", "energy": 30,
                             "dose_cm2": 1e15},
                            {"step": "bake", "temperature_C": 900},
                            {"step": "anneal", "temperature_C": 1000, "time_s": -5},
                            {"step": "implant", "species": "Sb", "energy_keV": 30,
                             "dose_cm2": 1e15}],
                    device={"physics": {"mobility": {"model": "lombardi",
                                                     "base": "klasen"}}},
                    analyses=[{"type": "iv", "anode": "top",
                               "cathode_contact": "bot", "v_start": 0,
                               "v_end": 1, "v_step": 0.1},
                              {"type": "noise"},
                              {"type": "iv", "anode_contact": "gate",
                               "cathode_contact": "bot", "v_start": 0,
                               "v_end": 1, "v_step": 0.1}])
    data["structure"]["layers"][0]["material"] = "Silicone"
    data["structure"]["contacts"][0]["layer"] = "poly"
    p = _problems(data)
    assert "unknown field" in p["colour"]
    assert "unknown material" in p["structure.layers[0].material"]
    assert "no layer named 'poly'" in p["structure.contacts[0].layer"]
    assert "unknown field" in p["recipe[0].energy"]
    assert "Unknown step 'bake'" in p["recipe[1].step"]
    assert "time must be" in p["recipe[2]"]
    assert "Unknown implant species 'Sb'" in p["recipe[3]"]
    assert "Unknown mobility model 'klasen'" in p["device.physics.mobility.base"]
    assert "unknown argument" in p["analyses[0].anode"]
    assert "Unknown analysis 'noise'" in p["analyses[1].type"]
    assert "no contact named 'gate'" in p["analyses[2].anode_contact"]


def test_section_level_problems():
    assert "missing required field 'structure'" in _problems({"name": "x"})[""]
    assert "unsupported version" in _problems(_minimal(version=2))["version"]
    p = _problems(_minimal(analyses=[{"type": "iv", "anode_contact": "top",
                                      "cathode_contact": "bot", "v_start": 0,
                                      "v_end": 1, "v_step": 0.5}]))
    assert "need a 'device' section" in p["analyses"]
    two = {"name": "a", "type": "iv", "anode_contact": "top",
           "cathode_contact": "bot", "v_start": 0, "v_end": 1, "v_step": 0.5}
    p = _problems(_minimal(device={}, analyses=[two, dict(two)]))
    assert "duplicate analysis name" in p["analyses[1].name"]
    p = _problems(_minimal(mesh={"size_um": -1}))
    assert "must be > 0" in p["mesh.size_um"]


def test_invalid_yaml_is_a_deck_error(tmp_path):
    path = tmp_path / "broken.yaml"
    path.write_text("structure: [unclosed\n")
    with pytest.raises(DeckError, match="not valid YAML"):
        load_deck(path)


# ---- plugins in files -------------------------------------------------------------
@dataclass(frozen=True)
class UniformAcceptor:
    conc_cm3: float


def test_plugin_step_in_a_deck():
    plugins.register_step(UniformAcceptor, stage="doping",
                          apply=lambda mf, s: setattr(mf, "Na", mf.Na + s.conc_cm3))
    deck = deck_from_dict(_minimal(recipe=[{"step": "uniform_acceptor",
                                            "conc_cm3": "2e16"}]))
    assert deck.recipe.steps[0] == UniformAcceptor(2e16)
    assert deck.to_dict()["recipe"] == [{"step": "uniform_acceptor",
                                         "conc_cm3": 2e16}]
    out = run_deck(deck)
    assert np.all(out.meshfield.Na >= 2e16 + 1e16 - 1.0)


# ---- running ---------------------------------------------------------------------
@pytest.mark.requires_devsim
def test_run_diode_deck_and_cli(tmp_path, capsys):
    deck = load_deck(DECKS / "pn_diode.yaml")
    res = run_deck(deck)
    v, i = res.analyses["forward"]
    assert len(v) == 7 and abs(i[-1]) > 1e3 * abs(i[1]) > 0
    json.dumps(res.analyses_to_dict())

    out = tmp_path / "r.json"
    assert cli_main(["run", str(DECKS / "pn_diode.yaml"), "-o", str(out)]) == 0
    payload = json.loads(out.read_text())
    assert payload["deck"] == "pn_diode"
    assert np.allclose(payload["analyses"]["forward"][1], i, rtol=1e-6)


def test_cli_check(tmp_path, capsys):
    assert cli_main(["check", str(DECKS / "nmos_implanted.yaml")]) == 0
    assert "OK" in capsys.readouterr().out
    bad = tmp_path / "bad.yaml"
    bad.write_text("structure: {width_um: 1, layers: "
                   "[{name: a, thickness_um: 0.5, material: Silcon}]}\n")
    assert cli_main(["check", str(bad)]) == 1
    assert "unknown material 'Silcon'" in capsys.readouterr().err
    assert cli_main(["run", str(bad)]) == 1


def test_cli_plugins_lists_registries(capsys):
    assert cli_main(["plugins"]) == 0
    out = capsys.readouterr().out
    assert "implant" in out and "lombardi" in out and "Entry-point plugins: none" in out
