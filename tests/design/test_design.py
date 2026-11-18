"""Design contract validation and bounded adaptive search without simulator mocks bypassing extraction."""
import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

import opentcad.design as design_module
from opentcad import plugins
from opentcad.design import load_design, run_design
from opentcad.io import deck as deck_module
from opentcad.io.deck import DeckError, load_deck


DECK = Path(__file__).resolve().parents[2] / "examples/decks/pn_diode.yaml"
VARIABLE = "structure.layers[0].doping_Na"


@pytest.fixture(autouse=True)
def registry(monkeypatch):
    monkeypatch.setattr(plugins, "_iter_entry_points", lambda: [])
    plugins._reset_for_tests()
    yield
    plugins._reset_for_tests()


def spec():
    base = load_deck(DECK).to_dict()
    base["analyses"] = base["analyses"][:1]
    return {"version": 1, "name": "bounded_diode", "base": base,
            "variables": [{"path": VARIABLE, "lower": 1e17, "upper": 3e17,
                           "initial": 1e17, "scale": "linear"}],
            "targets": [{"name": "current", "analysis": "forward", "metric": "value_at",
                         "options": {"x": 0.3}, "lower": 1.49, "upper": 1.51,
                         "scale": 1, "unit": "A/cm"}],
            "search": {"max_evaluations": 20, "initial_step": 0.25, "min_step": 0.01}}


def fake_simulator(monkeypatch, response=None):
    calls = []

    def run(deck):
        calls.append(deck.to_dict())
        if response:
            data = response(deck, len(calls))
        else:
            x = np.arange(0, 0.6 + 0.1 / 2, 0.1).tolist()
            value = deck.structure.layers[0].doping_Na / 1e17
            data = {"forward": (x, [value] * len(x))}
        return SimpleNamespace(analyses=data, analyses_to_dict=lambda: copy.deepcopy(data))

    monkeypatch.setattr(deck_module, "run_deck", run)
    return calls


def test_load_round_trip_and_relative_base(tmp_path):
    source = spec()
    (tmp_path / "base.yaml").write_text(deck_module.dumps_deck(load_deck(DECK)))
    source["base"] = "base.yaml"
    loaded = load_design(source, base_dir=tmp_path)
    assert load_design(loaded.to_dict()).to_dict() == loaded.to_dict()
    assert loaded.base["device"]["physics"]


@pytest.mark.parametrize("mutation,match", [
    (lambda s: s["variables"][0].update(initial=True), "finite real"),
    (lambda s: s["variables"][0].update(lower=float("nan")), "finite"),
    (lambda s: s["variables"][0].update(upper=float("inf")), "finite"),
    (lambda s: s["variables"][0].update(lower=3e17), "lower < upper"),
    (lambda s: s["variables"][0].update(initial=4e17), "within bounds"),
    (lambda s: s["variables"][0].update(scale="log", lower=0), "positive"),
    (lambda s: s["variables"][0].update(path="device.temperature_K"), "physics"),
    (lambda s: s["variables"][0].update(path="mesh.size_um"), "physics"),
    (lambda s: s["variables"][0].update(path="structure.contacts[0].flat_band_shift_V"), "barriers"),
    (lambda s: s["variables"][0].update(path="structure.layers[0].material"), "numeric"),
    (lambda s: s["variables"].append(copy.deepcopy(s["variables"][0])), "duplicate variable"),
    (lambda s: s["targets"].append(copy.deepcopy(s["targets"][0])), "duplicate target"),
    (lambda s: s["targets"][0].update(lower=True), "finite real"),
    (lambda s: s["targets"][0].update(scale=0), "positive"),
    (lambda s: s["targets"][0].update(scale=float("inf")), "finite"),
    (lambda s: s["targets"][0].update(lower=2, upper=1), "lower exceeds"),
    (lambda s: s["targets"][0].update(unit="A"), "A/cm"),
    (lambda s: s["targets"][0].update(metric="unknown"), "unit contract"),
    (lambda s: s["targets"][0].update(options={"bad": 1}), "required argument"),
    (lambda s: s["targets"][0].update(options={"x": True}), "finite real"),
    (lambda s: s["targets"][0].update(options={"x": 2}), "sweep range"),
    (lambda s: s["search"].update(max_evaluations=True), "positive integer"),
    (lambda s: s["search"].update(max_evaluations=1.5), "positive integer"),
    (lambda s: s["search"].update(max_evaluations=0), "positive integer"),
    (lambda s: s["search"].update(initial_step=True), "min_step"),
    (lambda s: s["search"].update(min_step=0.5), "min_step"),
    (lambda s: s["base"]["device"].pop("physics"), "explicitly"),
    (lambda s: s["base"]["analyses"][0].update(v_end=0.65), "reach v_end"),
    (lambda s: s["base"]["analyses"][0].update(v_step=-0.1), "direction"),
    (lambda s: s["targets"][0].update(analysis="missing"), "IV/CV analysis"),
    (lambda s: s["base"]["analyses"].append({"name": "equilibrium", "type": "fields"})
     or s["targets"][0].update(analysis="equilibrium"), "IV/CV analysis"),
    (lambda s: s.update(unresolved="unknown"), "list of strings"),
    (lambda s: s.update(unknown=1), "unknown fields"),
])
def test_invalid_contracts(mutation, match):
    source = spec()
    mutation(source)
    with pytest.raises(DeckError, match=match):
        load_design(source)


def test_missing_bounds_and_options_rejected():
    source = spec()
    del source["targets"][0]["lower"]
    del source["targets"][0]["upper"]
    with pytest.raises(DeckError, match="at least one"):
        load_design(source)


def test_reaches_target_and_keeps_evidence(tmp_path, monkeypatch):
    calls = fake_simulator(monkeypatch)
    original = spec()
    result = run_design(load_design(original), tmp_path / "run")
    assert result.stop_reason == "target_met"
    assert len(result.attempts) == len(calls) == 2
    assert result.best["metrics"]["current"] == pytest.approx(1.5)
    assert result.best["score"] == 0
    assert result.best["completion"]["forward"]["observed_points"] == 7
    assert original == spec()
    assert all(c["device"] == calls[0]["device"] for c in calls)
    assert all(c["analyses"] == calls[0]["analyses"] for c in calls)
    for row in result.attempts:
        exact = (result.outdir / row["deck"]).read_text()
        assert hashlib.sha256(exact.encode()).hexdigest() == row["deck_sha256"]
        record = json.loads((result.outdir / row["result"]).read_text())
        assert record["values"] == row["values"]
        assert record["settings"]["max_evaluations"] == 20
    assert (result.outdir / "best.yaml").read_text() == (result.outdir / result.best["deck"]).read_text()
    manifest = json.loads((result.outdir / "environment.json").read_text())
    assert manifest["materials"]["Si"]["sha256"]
    assert manifest["versions"]["numpy"]


def test_hard_budget_bounds_and_determinism(tmp_path, monkeypatch):
    calls = fake_simulator(monkeypatch)
    source = spec()
    source["targets"][0].update(lower=99, upper=100)
    source["search"]["max_evaluations"] = 4
    one = run_design(load_design(source), tmp_path / "one")
    two = run_design(load_design(source), tmp_path / "two")
    assert one.stop_reason == two.stop_reason == "budget_exhausted"
    assert len(one.attempts) == len(two.attempts) == 4
    assert len(calls) == 8
    assert [r["values"] for r in one.attempts] == [r["values"] for r in two.attempts]
    assert all(1e17 <= r["values"][VARIABLE] <= 3e17 for r in one.attempts)
    assert len({r["values"][VARIABLE] for r in one.attempts}) == 4


def test_adapts_and_halves_step_to_reach_narrow_target(tmp_path, monkeypatch):
    fake_simulator(monkeypatch)
    source = spec()
    source["targets"][0].update(lower=1.624, upper=1.626)
    result = run_design(load_design(source), tmp_path / "run")
    assert result.stop_reason == "target_met"
    assert result.best["metrics"]["current"] == pytest.approx(1.625)
    assert min(r["step"] for r in result.attempts) < 0.25
    assert len(result.attempts) <= 20


def test_log_coordinate_and_one_sided_targets(tmp_path, monkeypatch):
    fake_simulator(monkeypatch)
    source = spec()
    source["variables"][0].update(lower=1e16, upper=1e18, initial=1e17, scale="log")
    source["targets"][0].update(lower=3, upper=3.3)
    result = run_design(load_design(source), tmp_path / "log")
    assert result.stop_reason == "target_met"
    assert result.best["values"][VARIABLE] == pytest.approx(10 ** 17.5)
    source["targets"][0].pop("upper")
    assert load_design(source).targets[0].upper is None


@pytest.mark.parametrize("response", [
    lambda d, n: {},
    lambda d, n: {"forward": ([0, 0.1], [1, 1])},
    lambda d, n: {"forward": ([0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6], [1] * 6)},
    lambda d, n: {"forward": ([0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6], [float("nan")] * 7)},
    lambda d, n: {"forward": ([0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.7], [1] * 7)},
])
def test_incomplete_or_nonfinite_analysis_never_qualifies(tmp_path, monkeypatch, response):
    calls = fake_simulator(monkeypatch, response)
    source = spec()
    source["search"]["max_evaluations"] = 3
    result = run_design(load_design(source), tmp_path / "run")
    assert result.stop_reason == "no_valid_candidates"
    assert len(calls) == len(result.attempts) == 3
    assert result.best is None
    assert all(r["status"] == "failed" for r in result.attempts)
    text = (result.outdir / "design.json").read_text()
    assert "NaN" not in text
    assert json.loads(text)["best"] is None


def test_simulator_failures_consume_budget_and_recovery_is_possible(tmp_path, monkeypatch):
    def response(deck, count):
        if count == 1:
            raise RuntimeError("solver failed")
        return {"forward": (np.arange(0, 0.65, 0.1).tolist(), [1.5] * 7)}

    calls = fake_simulator(monkeypatch, response)
    result = run_design(load_design(spec()), tmp_path / "run")
    assert len(calls) == 2
    assert result.attempts[0]["status"] == "failed"
    assert "solver failed" in result.attempts[0]["error"]
    assert result.stop_reason == "target_met"


@pytest.mark.parametrize("value", [float("nan"), float("inf"), True, np.array([1.5])])
def test_nonfinite_or_non_scalar_metric_fails(tmp_path, monkeypatch, value):
    fake_simulator(monkeypatch)
    monkeypatch.setattr(design_module, "get_metric", lambda name: lambda result, x: value)
    source = spec()
    source["search"]["max_evaluations"] = 1
    result = run_design(load_design(source), tmp_path / "run")
    assert result.stop_reason == "no_valid_candidates"
    assert "finite real scalar" in result.attempts[0]["error"]


def test_stalled_search_and_no_duplicate_calls(tmp_path, monkeypatch):
    def response(deck, count):
        return {"forward": (np.arange(0, 0.65, 0.1).tolist(), [1] * 7)}

    calls = fake_simulator(monkeypatch, response)
    source = spec()
    source["search"].update(max_evaluations=100, min_step=0.25)
    result = run_design(load_design(source), tmp_path / "run")
    assert result.stop_reason == "search_stalled"
    assert len(calls) == 2  # baseline plus one neighbor; clipped duplicate is cached.


def test_no_overwrite_and_unresolved_prevents_execution(tmp_path, monkeypatch):
    calls = fake_simulator(monkeypatch)
    source = spec()
    source["unresolved"] = ["Missing allowed process range"]
    with pytest.raises(DeckError, match="resolve before"):
        run_design(load_design(source), tmp_path / "unresolved")
    assert not (tmp_path / "unresolved").exists()
    existing = tmp_path / "existing"
    existing.mkdir()
    (existing / "keep.txt").write_text("user data")
    with pytest.raises(FileExistsError):
        run_design(load_design(spec()), existing)
    assert (existing / "keep.txt").read_text() == "user data"
    assert not calls


def test_invalid_candidate_geometry_counts_as_attempt(tmp_path, monkeypatch):
    calls = fake_simulator(monkeypatch)
    source = spec()
    source["variables"] = [{"path": "structure.width_um", "lower": 0.1, "upper": 1,
                            "initial": 1, "scale": "linear"}]
    source["search"]["max_evaluations"] = 2
    result = run_design(load_design(source), tmp_path / "run")
    assert len(result.attempts) == 2
    assert len(calls) == 1
    assert result.attempts[1]["status"] == "failed"
    assert (result.outdir / result.attempts[1]["deck"]).exists()


def test_material_drift_fails_candidate_and_stops(tmp_path, monkeypatch):
    material = tmp_path / "Si.yaml"
    material.write_text("fixed physics")
    snapshot = {"materials": {"Si": {"source": str(material),
                                    "sha256": hashlib.sha256(b"fixed physics").hexdigest()}}}
    monkeypatch.setattr(design_module, "_environment", lambda b, p: snapshot)

    def response(deck, count):
        material.write_text("changed physics")
        return {"forward": (np.arange(0, 0.65, 0.1).tolist(), [1.5] * 7)}

    calls = fake_simulator(monkeypatch, response)
    result = run_design(load_design(spec()), tmp_path / "run")
    assert len(calls) == 1
    assert result.stop_reason == "no_valid_candidates"
    assert result.best is None
    assert "material source changed" in result.attempts[0]["error"]
    assert json.loads((result.outdir / "design.json").read_text())["material_drift"]


def test_cv_unit_and_completion_contract(tmp_path, monkeypatch):
    source = spec()
    source["base"]["analyses"] = [{"name": "capacitance", "type": "cv", "terminal": "anode",
                                  "reference": "cathode", "v_start": 0, "v_end": 0.2, "v_step": 0.1}]
    source["targets"][0].update(analysis="capacitance", metric="max_abs", options={}, unit="F/cm")

    def response(deck, count):
        return {"capacitance": ([0, 0.1, 0.2], [1.5] * 3)}

    fake_simulator(monkeypatch, response)
    result = run_design(load_design(source), tmp_path / "run")
    assert result.stop_reason == "target_met"
    assert result.best["completion"]["capacitance"]["observed_points"] == 3


def test_variable_paths_are_exactly_the_fields_a_design_may_vary():
    from opentcad.design import variable_paths
    base = load_deck(DECK.parent / "nmos_implanted.yaml").to_dict()
    paths = variable_paths(base)
    assert paths["structure.layers[0].doping_Na"] == 1e17
    assert paths["recipe[4].time_s"] == 1800
    assert "structure.regions[0].x_um[1]" in paths
    assert not any(p.startswith(("device", "mesh", "analyses")) for p in paths)
    assert not any("flat_band" in p or "barrier" in p for p in paths)
    for path, value in paths.items():          # each one is accepted as a variable
        source = spec()
        source["base"] = base
        source["targets"] = [{"name": "vth", "analysis": "idvg", "metric": "vth_max_gm",
                              "options": {"vds": 0.05}, "lower": 0.4, "scale": 0.1, "unit": "V"}]
        lo, hi = (value - 1, value + 1) if value == 0 else sorted((value * 0.9, value * 1.1))
        source["variables"] = [{"path": path, "lower": lo, "upper": hi, "initial": value,
                                "scale": "linear"}]
        assert load_design(source).variables[0].path == path
