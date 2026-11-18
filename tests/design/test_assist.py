"""Drafting uses a fake chat server and never executes a candidate."""
import copy
import json
from pathlib import Path

import pytest

from opentcad.assist.client import LLMError
from opentcad.assist.design import draft_design
from opentcad.design import load_design

EXAMPLE = Path(__file__).resolve().parents[2] / "examples/design/pn_current.yaml"
BASE = EXAMPLE.parent.parent / "decks/pn_diode.yaml"


class ScriptedClient:
    def __init__(self, *replies):
        self.replies = iter(replies)
        self.calls = []

    def chat(self, messages, **kwargs):
        self.calls.append((copy.deepcopy(messages), kwargs))
        return next(self.replies)


def response(**changes):
    data = load_design(EXAMPLE).to_dict()
    for field in ("version", "base", "unresolved"):
        data.pop(field)
    data["questions"] = []
    data.update(changes)
    return json.dumps(data)


def test_typed_unverified_plan_keeps_selected_base_and_never_runs(monkeypatch):
    monkeypatch.setattr("opentcad.design.run_design", lambda *a, **kw: pytest.fail("draft ran"))
    client = ScriptedClient(response())
    result = draft_design("Reduce current at 0.5 V by varying p-body doping", base=BASE, client=client)
    artifact = result.to_dict()
    assert result.ok and result.attempts == 1
    assert artifact["status"] == "unaccepted"
    assert artifact["generated_values"] == "unverified_require_review"
    assert result.design["base"] == load_design(EXAMPLE).base
    assert any("unverified" in note for note in result.design["limitations"])
    assert "json_schema" in client.calls[0][1]
    assert "registered_metrics" in client.calls[0][0][1]["content"]


def test_schema_and_semantic_failures_get_bounded_repair():
    client = ScriptedClient(response(base={"physics": "changed"}), response())
    result = draft_design("Tune doping", base=BASE, client=client)
    assert result.ok and result.attempts == 2
    assert "Validation failed" in client.calls[1][0][-1]["content"]
    client = ScriptedClient(response(variables=[{"path": "device.temperature_K", "lower": 250,
                                               "upper": 350, "initial": 300, "scale": "linear"}]))
    result = draft_design("Tune temperature", base=BASE, client=client, max_repairs=0)
    assert not result.ok and result.design is None and result.problems


def test_unsupported_request_produces_questions_without_inventing_device():
    client = ScriptedClient(response(variables=[], targets=[],
                                     questions=["Supply a supported IV/CV base deck and numerical targets."]))
    result = draft_design("Synthesize an arbitrary new material topology", base=BASE, client=client)
    assert result.ok and result.design is None
    assert result.to_dict()["questions"]


def test_iterative_prompt_uses_explicit_evidence_and_preserves_unresolved():
    current = load_design(EXAMPLE).to_dict()
    current["unresolved"] = ["Confirm target specification"]
    current["limitations"].append("Prior mesh assumption")
    evidence = {"stop_reason": "budget_exhausted", "best": {"score": 0.2}}
    client = ScriptedClient(response())
    result = draft_design("Increase the budget", current=current, evidence=evidence, client=client)
    assert result.ok
    assert result.design["base"] == current["base"]
    assert result.design["unresolved"] == current["unresolved"]
    assert "Prior mesh assumption" in result.design["limitations"]
    assert "budget_exhausted" in client.calls[0][0][1]["content"]


def test_strict_values_and_context_limits_before_network():
    data = json.loads(response())
    data["variables"][0]["initial"] = True
    client = ScriptedClient(json.dumps(data))
    assert not draft_design("Tune", base=BASE, client=client, max_repairs=0).ok
    client = ScriptedClient()
    with pytest.raises(ValueError, match="80000"):
        draft_design("Tune", base=BASE, evidence={"blob": "x" * 80001}, client=client)
    assert not client.calls
    with pytest.raises(ValueError, match="exactly one"):
        draft_design("Tune", base=BASE, current={}, client=client)


def test_unavailable_server_is_reported_without_fallback():
    class Unavailable:
        def chat(self, *args, **kwargs):
            raise LLMError("server unavailable")
    with pytest.raises(LLMError, match="unavailable"):
        draft_design("Tune", base=BASE, client=Unavailable())


def test_schema_is_narrowed_to_the_base_for_grammar_constrained_servers():
    from opentcad.assist.design import _response_schema
    from opentcad.design import variable_paths
    from opentcad.io.deck import load_deck
    base = load_deck(BASE.parent / "nmos_implanted.yaml").to_dict()
    schema = _response_schema(base)
    assert set(schema["required"]) >= {"variables", "targets", "search", "questions"}
    path = schema["$defs"]["VariableProposal"]["properties"]["path"]
    assert path["enum"] == list(variable_paths(base))
    variants = {v["properties"]["metric"]["const"]: v
                for v in schema["$defs"]["TargetProposal"]["anyOf"]}
    assert set(variants) == {"value_at", "max_abs", "vth_max_gm", "vth_constant_current"}
    vth = variants["vth_max_gm"]
    assert vth["properties"]["unit"] == {"const": "V", "type": "string"}
    assert vth["properties"]["options"]["required"] == ["vds"]
    assert vth["properties"]["analysis"]["enum"] == ["idvg"]   # IV only; never `fields`
    assert variants["value_at"]["properties"]["options"]["required"] == ["x"]
    assert variants["max_abs"]["properties"]["options"]["properties"] == {}
    assert list(vth["properties"])[0] == "metric"
    assert {"lower", "upper", "options"} <= set(vth["required"])


def test_context_lists_paths_and_analyses():
    client = ScriptedClient(response())
    draft_design("Tune doping", base=BASE, client=client)
    context = json.loads(client.calls[0][0][1]["content"])["context"]
    assert "structure.layers[0].doping_Na" in context["variable_paths"]
    assert context["target_analyses"] == [{"name": "forward", "type": "iv", "v_start": 0.0,
                                           "v_end": 0.6, "v_step": 0.1}]
    schema = client.calls[0][1]["json_schema"]
    assert schema["$defs"]["VariableProposal"]["properties"]["path"]["enum"]
