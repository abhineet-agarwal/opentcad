"""Parameter sweeps (opentcad.io.sweep), metrics, and `opentcad sweep`."""
import csv
import json
from pathlib import Path

import numpy as np
import pytest

from opentcad import plugins
from opentcad.cli import main as cli_main
from opentcad.device import builtin_metrics as metrics
from opentcad.io.deck import DeckError, load_deck
from opentcad.io.sweep import load_sweep, run_sweep, set_path

DECKS = Path(__file__).resolve().parents[2] / "examples" / "decks"


@pytest.fixture(autouse=True)
def _clean_registry(monkeypatch):
    monkeypatch.setattr(plugins, "_iter_entry_points", lambda: [])
    plugins._reset_for_tests()
    yield
    plugins._reset_for_tests()


def _diode_sweep(**over):
    base = load_deck(DECKS / "pn_diode.yaml").to_dict()
    base["analyses"][0]["v_end"] = 0.4
    s = {"name": "diode_doping", "base": base,
         "vary": {"structure.layers[1].doping_Nd": [1e16, 1e17]},
         "metrics": [{"name": "i_at_0p3", "analysis": "forward",
                      "metric": "value_at", "x": 0.3},
                     {"name": "imax", "analysis": "forward", "metric": "max_abs"}]}
    s.update(over)
    return s


def _problems(src, **kw):
    with pytest.raises(DeckError) as info:
        load_sweep(src, **kw)
    return dict(info.value.problems)


# ---- paths ---------------------------------------------------------------------
def test_set_path():
    d = {"a": [{"b": 1}, {"b": 2}], "c": {"x": [0, 1]}}
    set_path(d, "a[1].b", 5)
    set_path(d, "c.x[0]", 9)
    set_path(d, "c.new", 3)                 # absent key on a mapping: allowed
    assert d == {"a": [{"b": 1}, {"b": 5}], "c": {"x": [9, 1], "new": 3}}
    with pytest.raises(ValueError, match="index out of range"):
        set_path(d, "a[2].b", 0)
    with pytest.raises(ValueError, match="no such field"):
        set_path(d, "nope.b", 0)
    with pytest.raises(ValueError, match="not a list"):
        set_path(d, "c[0]", 0)


# ---- metrics --------------------------------------------------------------------
def test_metric_functions():
    v = [0.0, 0.5, 1.0]
    i = [0.0, -2.0, -4.0]
    assert metrics.value_at((v, i), 0.75) == pytest.approx(3.0)
    assert metrics.max_abs((v, i)) == 4.0
    with pytest.raises(ValueError, match="outside the swept range"):
        metrics.value_at((v, i), 2.0)
    with pytest.raises(ValueError, match=r"\(x, y\) result"):
        metrics.max_abs(3.0)
    vv = np.linspace(0, 1, 51)
    ii = 1e-9 * 10 ** ((vv - 0.3) / 0.08)
    assert metrics.vth_constant_current((vv, ii), 1e-7) == pytest.approx(0.46)
    assert plugins.available_metrics() == ["max_abs", "value_at",
                                           "vth_constant_current", "vth_max_gm"]


# ---- loading -------------------------------------------------------------------
def test_example_sweep_loads():
    s = load_sweep(DECKS / "nmos_tox_sweep.yaml")
    assert s.mode == "zip" and len(s.points) == 3
    assert s.points[2] == {"structure.layers[1].thickness_um": 0.007,
                           "structure.regions[0].y_um[1]": 0.507,
                           "structure.regions[1].y_um[1]": 0.507}
    deck = s.point_deck(s.points[2])
    assert deck["structure"]["layers"][1]["thickness_um"] == 0.007
    assert s.base["structure"]["layers"][1]["thickness_um"] == 0.005   # untouched


def test_product_mode_counts_every_combination():
    s = load_sweep(_diode_sweep(vary={"structure.layers[1].doping_Nd": [1e16, 1e17],
                                      "device.temperature_K": [290, 300, 310]}))
    assert len(s.points) == 6


def test_sweep_problems():
    p = _problems(_diode_sweep(mode="zip", vary={
        "structure.layers[1].doping_Nd": [1e16, 1e17],
        "device.temperature_K": [300]}))
    assert "equal length" in p["vary"]
    p = _problems(_diode_sweep(vary={"structure.layers[5].doping_Nd": [1e16]},
                               metrics=[{"name": "x", "analysis": "nope",
                                         "metric": "max_abs"},
                                        {"name": "y", "analysis": "forward",
                                         "metric": "slope"},
                                        {"name": "z", "analysis": "forward",
                                         "metric": "value_at", "v": 1}]))
    assert "index out of range" in p["vary.structure.layers[5].doping_Nd"]
    assert "no analysis named 'nope'" in p["metrics[0].analysis"]
    assert "Unknown metric 'slope'" in p["metrics[1].metric"]
    assert "value_at" in p["metrics[2]"]
    # Every point is checked as a simulation file before anything runs.
    p = _problems(_diode_sweep(vary={"structure.layers[0].thickness_um": [0.5, -1]}))
    key = next(k for k in p if k.startswith("point 1"))
    assert "thickness must be > 0" in p[key]
    assert "missing required field 'vary'" in _problems({"base": {}})[""]


def test_bad_base_file_is_reported(tmp_path):
    (tmp_path / "sweep.yaml").write_text("base: missing.yaml\nvary: {name: [a]}\n")
    assert "cannot read" in _problems(tmp_path / "sweep.yaml")["base"]


# ---- running -------------------------------------------------------------------
@pytest.mark.requires_devsim
def test_run_sweep_writes_table_and_points(tmp_path):
    s = load_sweep(_diode_sweep(metrics=[
        {"name": "i_at_0p3", "analysis": "forward", "metric": "value_at", "x": 0.3},
        {"name": "vth", "analysis": "forward", "metric": "vth_max_gm", "vds": 0}]))
    res = run_sweep(s, tmp_path / "out")
    rows = list(csv.DictReader((tmp_path / "out" / "table.csv").open()))
    assert [r["status"] for r in rows] == ["ok", "ok"]
    # The two n-side dopings must give different, positive currents.
    i0, i1 = float(rows[0]["i_at_0p3"]), float(rows[1]["i_at_0p3"])
    assert i0 > 0 and i1 > 0 and i0 != pytest.approx(i1, rel=1e-3)
    # A diode's gm peaks at the last bias point: the metric is recorded as
    # missing with a note, and the point still counts as run.
    assert rows[0]["vth"] == "" and "last bias point" in rows[0]["notes"]
    point = json.loads((tmp_path / "out" / "points" / "point_001.json").read_text())
    assert point["values"] == {"structure.layers[1].doping_Nd": 1e17}
    assert len(point["analyses"]["forward"][0]) == 5
    assert load_deck(tmp_path / "out" / "points" / "point_001.yaml"
                     ).structure.layers[1].doping_Nd == 1e17
    assert res.rows[1]["i_at_0p3"] == pytest.approx(i1)


@pytest.mark.requires_devsim
def test_cli_sweep_and_check(tmp_path, capsys):
    path = tmp_path / "sweep.yaml"
    import yaml
    path.write_text(yaml.safe_dump(_diode_sweep()))
    assert cli_main(["check", str(path)]) == 0
    assert "2 point(s)" in capsys.readouterr().out
    assert cli_main(["sweep", str(path), "-o", str(tmp_path / "o")]) == 0
    assert (tmp_path / "o" / "table.csv").exists()
    bad = tmp_path / "bad.yaml"
    bad.write_text(yaml.safe_dump(_diode_sweep(mode="spiral")))
    assert cli_main(["sweep", str(bad)]) == 1
