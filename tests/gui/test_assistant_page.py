"""
The assistant page, run headless with Streamlit's AppTest and a scripted
model. Needs streamlit (the ``gui`` extra); skipped otherwise.
"""
import json
from pathlib import Path

import pytest

st_testing = pytest.importorskip("streamlit.testing.v1")

ROOT = Path(__file__).resolve().parents[2]
PAGE = str(ROOT / "opentcad" / "gui" / "pages" / "assistant.py")


@pytest.fixture
def fake_model(monkeypatch):
    """draft_deck returns the NMOS template with a 4 nm oxide."""
    import opentcad.assist as assist
    from opentcad.assist import Draft, Flag
    from opentcad.io import load_deck

    def fake_draft(request, *, client, current=None, **kw):
        d = load_deck(ROOT / "examples" / "decks" / "nmos_implanted.yaml")
        data = d.to_dict()
        data["structure"]["layers"][1]["thickness_um"] = 0.004
        for r in data["structure"]["regions"]:
            r["y_um"][1] = 0.504
        from opentcad.io import deck_from_dict
        return Draft(deck=deck_from_dict(data), data=data, attempts=1,
                     flags=[Flag("structure.regions[0].y_um[1]", 0.504,
                                 "windows reach the new top", True)])

    monkeypatch.setattr(assist, "draft_deck", fake_draft)


def _button(at, label):
    return next(b for b in at.button if b.label == label)


@pytest.mark.requires_devsim
def test_draft_review_run(fake_model):
    at = st_testing.AppTest.from_file(PAGE, default_timeout=300)
    at.run()
    assert not at.exception
    at.radio[0].set_value("NMOS (implanted)")
    at.text_area[0].set_value("Make the gate oxide 4 nm")
    _button(at, "Draft with the model").click().run()
    assert not at.exception
    assert any("1 value(s) were not in your request" in w.value for w in at.warning)
    assert "thickness_um: 0.004" in at.text_area[1].value
    _button(at, "Run").click().run()
    assert not at.exception and not at.error
    assert [t.label for t in at.tabs] == ["Structure", "Doping", "Results"]
    assert len(at.get("plotly_chart")) == 6        # + the inversion field map


def test_editor_reports_problems():
    at = st_testing.AppTest.from_file(PAGE, default_timeout=60)
    at.run()
    at.text_area[1].set_value("structure: {width_um: 1, layers: "
                              "[{name: a, thickness_um: 0.5, material: Silcon}]}")
    at.run()
    assert any("unknown material 'Silcon'" in e.value for e in at.error)
    assert not [b for b in at.button if b.label == "Run"]
