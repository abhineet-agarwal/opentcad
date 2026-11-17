import json

from opentcad.assist.catalog import draft_catalog
from opentcad.assist.client import LLMError
import pytest


class ScriptedClient:
    def __init__(self, *replies):
        self.replies = iter(replies)
        self.calls = []

    def chat(self, messages, **kwargs):
        self.calls.append((list(messages), kwargs))
        return next(self.replies)


def response(**changes):
    data = {"records": [{"id": "local:resist", "title": "User resist",
                         "kind": "material_product", "payload": {"product": "PR-1"}}],
            "assumptions": [], "questions": ["What is the datasheet revision?"]}
    data.update(changes)
    return json.dumps(data)


def test_model_draft_is_typed_private_and_unverified():
    client = ScriptedClient(response(assumptions=[{"path": "records[0].id",
                                                  "value": "local:resist",
                                                  "basis": "proposed local identifier"}]))
    result = draft_catalog("Add my PR-1 resist", client=client)
    artifact = result.to_dict()
    assert result.ok and result.attempts == 1
    assert artifact["generated_values"] == "unverified_require_review"
    assert artifact["status"] == "unaccepted"
    assert artifact["assumptions"][0]["basis"] == "proposed local identifier"
    assert artifact["assessments"][0]["simulation"] == "unsupported"
    assert "json_schema" in client.calls[0][1]


def test_invalid_reply_repairs_once_and_reports_failure():
    client = ScriptedClient("not json", response(records=[{"kind": "invented"}]))
    result = draft_catalog("Add a tool", client=client, max_repairs=1)
    assert not result.ok and result.attempts == 2
    assert result.problems and result.to_dict()["bundle"]["records"] == []
    assert "failed validation" in client.calls[1][0][-1]["content"]


def test_private_boundary_is_validated_and_empty_questions_allowed():
    bad = json.loads(response())
    bad["records"][0]["visibility"] = "public"
    client = ScriptedClient(json.dumps(bad), response(records=[]))
    result = draft_catalog("What information do you need?", client=client)
    assert result.ok and result.proposal.questions
    assert not result.proposal.records


def test_unreachable_model_does_not_generate_local_replacement():
    class Unavailable:
        def chat(self, *args, **kwargs):
            raise LLMError("model unavailable")

    with pytest.raises(LLMError, match="unavailable"):
        draft_catalog("Add a tool", client=Unavailable())
