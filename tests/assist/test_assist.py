"""
opentcad.assist — drafting simulation files with a local model. A scripted
fake client stands in for the model; a stub HTTP server for the client.
"""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from opentcad import plugins
from opentcad.assist import (ChatClient, LLMError, draft_deck, request_numbers,
                             unstated_values)
from opentcad.assist.prompt import (deck_json_schema, reference_sheet,
                                    response_schema, system_prompt)
from opentcad.io import load_deck

DECKS = Path(__file__).resolve().parents[2] / "examples" / "decks"


@pytest.fixture(autouse=True)
def _clean_registry(monkeypatch):
    monkeypatch.setattr(plugins, "_iter_entry_points", lambda: [])
    plugins._reset_for_tests()
    yield
    plugins._reset_for_tests()


class FakeClient:
    """Replies with scripted strings; records what it was sent."""
    def __init__(self, *replies):
        self.replies = list(replies)
        self.calls = []

    def chat(self, messages, *, json_schema=None, **kw):
        self.calls.append({"messages": [dict(m) for m in messages],
                           "schema": json_schema})
        return self.replies.pop(0)


def _diode():
    return load_deck(DECKS / "pn_diode.yaml").to_dict()


def _reply(deck, assumptions=(), questions=()):
    return json.dumps({"deck": deck, "assumptions": list(assumptions),
                       "questions": list(questions)})


# ---- numbers and flags -----------------------------------------------------------
def test_request_numbers_convert_units():
    nums = request_numbers("4 nm oxide, 1 µm gate, 50 mV, 30 min, 2x10^15, 1e17 cm-3")
    for v in (0.004, 1.0, 0.05, 1800.0, 2e15, 1e17):
        assert any(abs(n - v) <= 1e-12 * max(v, 1) for n in nums), v


def test_unstated_values():
    deck = _diode()
    req = "p-n diode 1 µm wide, 0.5 µm layers, 1e17 both sides, IV 0 to 0.6 V step 0.1"
    flagged = dict(unstated_values(req, deck))
    assert "structure.layers[0].doping_Na" not in flagged       # stated
    assert flagged["mesh.size_um"] == 0.05                      # chosen
    assert flagged["device.physics.mobility"] == "klaassen"     # a modelling choice
    assert "device.physics.mobility" not in dict(
        unstated_values(req + " with Klaassen mobility", deck))
    # Editing: values unchanged from the reviewed file aren't flagged again.
    assert unstated_values("anything", deck, previous=deck) == []


# ---- drafting --------------------------------------------------------------------
def test_draft_success_with_reasons():
    deck = _diode()
    client = FakeClient(_reply(deck, [{"path": "mesh.size_um", "value": 0.05,
                                       "reason": "fine enough for 1 µm"}]))
    d = draft_deck("pn diode 1 µm wide, 0.5 µm layers, 1e17, IV to 0.6 V step 0.1",
                   client=client)
    assert d.ok and d.attempts == 1 and d.problems == []
    flags = {f.path: f for f in d.flags}
    assert flags["mesh.size_um"].declared
    assert flags["mesh.size_um"].reason == "fine enough for 1 µm"
    assert not flags["device.physics.mobility"].declared        # flagged anyway
    sent = client.calls[0]
    assert sent["messages"][0]["role"] == "system"
    assert sent["schema"]["properties"]["deck"]["properties"]["recipe"]


def test_repair_loop_feeds_problems_back():
    bad = _diode()
    bad["structure"]["layers"][0]["thickness"] = 0.5          # unknown key
    good = _diode()
    client = FakeClient("this is not json", _reply(bad), _reply(good))
    d = draft_deck("pn diode", client=client, max_repairs=2)
    assert d.ok and d.attempts == 3
    second_feedback = client.calls[2]["messages"][-1]["content"]
    assert "structure.layers[0].thickness" in second_feedback
    assert "not valid JSON" in client.calls[1]["messages"][-1]["content"]


def test_gives_up_after_max_repairs():
    bad = _diode()
    bad["structure"]["contacts"][0]["layer"] = "oxide"
    client = FakeClient(_reply(bad), _reply(bad))
    d = draft_deck("pn diode", client=client, max_repairs=1)
    assert not d.ok and d.attempts == 2
    assert any("no layer named 'oxide'" in m for _, m in d.problems)
    assert d.data is not None                                  # shown for editing


def test_region_outside_the_stack_is_a_problem():
    nmos = load_deck(DECKS / "nmos_implanted.yaml").to_dict()
    nmos["structure"]["layers"][1]["thickness_um"] = 0.004     # top now 0.504
    client = FakeClient(_reply(nmos), _reply(nmos))
    d = draft_deck("4 nm oxide", client=client, max_repairs=1)
    assert any("outside the layer stack" in m for _, m in d.problems)


def test_edit_mode_sends_the_current_file():
    current = _diode()
    edited = json.loads(json.dumps(current))
    edited["analyses"][0]["v_end"] = 0.8
    client = FakeClient(_reply(edited))
    d = draft_deck("sweep to 0.8 V", client=client, current=current)
    assert d.ok
    assert "Current simulation file" in client.calls[0]["messages"][1]["content"]
    assert [f.path for f in d.flags] == []                     # 0.8 was asked for


def test_wrapperless_reply_is_accepted():
    client = FakeClient(json.dumps(_diode()))
    assert draft_deck("pn diode", client=client).ok


# ---- prompt and schema --------------------------------------------------------------
def test_prompt_matches_registries():
    sheet = reference_sheet()
    assert "implant (doping)" in sheet and "energy_keV: number" in sheet
    assert "As (arsenic) 10–200 keV" in sheet
    assert "iv(anode_contact, cathode_contact" in sheet
    prompt = system_prompt()
    assert "EXAMPLE FILE (nmos_implanted.yaml)" in prompt


def test_schema_accepts_examples_and_rejects_unknown_keys():
    jsonschema = pytest.importorskip("jsonschema")
    schema = deck_json_schema()
    v = jsonschema.Draft202012Validator(schema)
    for name in ("pn_diode.yaml", "nmos_implanted.yaml"):
        assert list(v.iter_errors(load_deck(DECKS / name).to_dict())) == []
    bad = _diode()
    bad["structure"]["layers"][0]["colour"] = "red"
    assert list(v.iter_errors(bad))
    bad = _diode()
    bad["device"]["physics"]["mobility"] = "magic"
    assert list(v.iter_errors(bad))
    jsonschema.Draft202012Validator.check_schema(response_schema(schema))


# ---- HTTP client -----------------------------------------------------------------
class _Stub(BaseHTTPRequestHandler):
    reject_schema = True
    seen: list = []

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        type(self).seen.append(body)
        fmt = (body.get("response_format") or {}).get("type")
        if fmt == "json_schema" and type(self).reject_schema:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b'{"error": "json_schema not supported"}')
            return
        out = {"choices": [{"message": {"content": f'{{"format": "{fmt}"}}'}}]}
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(out).encode())

    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'{"data": [{"id": "tiny-model"}]}')

    def log_message(self, *a):
        pass


@pytest.fixture
def stub_server():
    _Stub.seen = []
    srv = HTTPServer(("127.0.0.1", 0), _Stub)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}/v1"
    srv.shutdown()


def test_client_falls_back_when_schema_is_rejected(stub_server):
    c = ChatClient(base_url=stub_server, model="m", api_key=None)
    assert c.models() == ["tiny-model"]
    reply = c.chat([{"role": "user", "content": "hi"}], json_schema={"type": "object"})
    assert json.loads(reply) == {"format": "json_object"}
    assert [b.get("response_format", {}).get("type") for b in _Stub.seen] == [
        "json_schema", "json_object"]
    assert _Stub.seen[0]["model"] == "m"


def test_client_reports_an_unreachable_server():
    c = ChatClient(base_url="http://127.0.0.1:9/v1", model="m", api_key=None,
                   timeout_s=2)
    with pytest.raises(LLMError, match="cannot reach the model server"):
        c.chat([{"role": "user", "content": "hi"}])
