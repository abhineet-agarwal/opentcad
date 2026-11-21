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
    """draft_deck returns the NMOS template with a 4 nm oxide, and records
    what it was given."""
    import opentcad.assist as assist
    from opentcad.assist import Draft, Flag
    from opentcad.io import load_deck
    calls = []

    def fake_draft(request, *, client, current=None, **kw):
        calls.append({"request": request, "current": current, **kw})
        d = load_deck(ROOT / "examples" / "decks" / "nmos_implanted.yaml")
        data = d.to_dict()
        data["structure"]["layers"][1]["thickness_um"] = 0.004
        for r in data["structure"]["regions"]:
            r["y_um"][1] = 0.504
        from opentcad.io import deck_from_dict
        return Draft(deck=deck_from_dict(data), data=data, attempts=1,
                     questions=["Which drain bias?"] if len(calls) == 1 else [],
                     flags=[Flag("structure.regions[0].y_um[1]", 0.504,
                                 "windows reach the new top", True)])

    monkeypatch.setattr(assist, "draft_deck", fake_draft)
    return calls


def _button(at, label):
    return next(b for b in at.button if b.label == label)


def _chat(at):
    return [(m.name, m.markdown[0].value) for m in at.chat_message]


@pytest.mark.requires_devsim
def test_conversation_draft_answer_run(fake_model):
    at = st_testing.AppTest.from_file(PAGE, default_timeout=300)
    at.run()
    assert not at.exception
    at.radio[0].set_value("NMOS (implanted)")
    at.chat_input[0].set_value("Make the gate oxide 4 nm").run()
    assert not at.exception
    assert any("1 value(s) were not in your request" in w.value for w in at.warning)
    assert "thickness_um: 0.004" in at.text_area[0].value
    chat = _chat(at)
    assert chat[0] == ("user", "Make the gate oxide 4 nm")
    assert chat[1][0] == "assistant" and "checks clean" in chat[1][1]
    assert "thickness_um`: 0.005 → 0.004" in chat[1][1]
    assert "1. Which drain bias?" in chat[1][1]
    assert not at.radio                       # the conversation edits the file below

    # The answer goes back with the conversation and the current file.
    at.chat_input[0].set_value("50 mV").run()
    second = fake_model[1]
    assert second["request"] == "50 mV"
    assert [t["role"] for t in second["history"]] == ["user", "assistant"]
    assert "Which drain bias?" in second["history"][1]["content"]
    assert second["current"]["structure"]["layers"][1]["thickness_um"] == 0.004

    _button(at, "Run").click().run()
    assert not at.exception and not at.error
    assert [t.label for t in at.tabs] == ["Structure", "Doping", "Results", "Sources"]
    assert len(at.get("plotly_chart")) == 6        # + the inversion field map
    assert _chat(at)[-1][1].startswith("Ran the file:")
    assert "idvg (iv): 16 points from 0 to 1.5 V" in _chat(at)[-1][1]
    reply = _chat(at)[-1][1]
    assert "are OpenTCAD's own values, not from a publication. The Sources tab" in reply
    values = next(d.value for d in at.dataframe if "Where" in d.value.columns)  # Sources tab
    assert {"Silicon", "Physical constants"} <= set(values["Where"])
    assert "recombination.tau_n_s" in set(values["Value"])


def test_editor_reports_problems():
    at = st_testing.AppTest.from_file(PAGE, default_timeout=60)
    at.run()
    at.text_area[0].set_value("structure: {width_um: 1, layers: "
                              "[{name: a, thickness_um: 0.5, material: Silcon}]}")
    at.run()
    assert any("unknown material 'Silcon'" in e.value for e in at.error)
    assert not [b for b in at.button if b.label == "Run"]
