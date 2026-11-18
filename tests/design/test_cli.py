"""Command dispatch, plain-plan review and actual candidate evidence persistence."""
import json
from pathlib import Path

import numpy as np
import pytest

from opentcad.cli import main
from opentcad.design import load_design

EXAMPLE = Path(__file__).resolve().parents[2] / "examples/design/pn_current.yaml"
BASE = EXAMPLE.parent.parent / "decks/pn_diode.yaml"


def plan_file(tmp_path, **changes):
    data = load_design(EXAMPLE).to_dict()
    data.update(changes)
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(data))
    return path


def test_check_reports_unresolved_without_output_directory(tmp_path, capsys):
    path = plan_file(tmp_path, unresolved=["Which target current?"])
    assert main(["design", "check", str(path)]) == 1
    assert "Which target current?" in capsys.readouterr().err
    assert not (tmp_path / "run").exists()
    assert main(["design", "run", str(path), "-o", str(tmp_path / "run")]) == 2
    assert not (tmp_path / "run").exists()


def test_cli_run_writes_real_search_evidence_using_fake_solver(tmp_path, monkeypatch):
    data = load_design(EXAMPLE).to_dict()
    data["targets"][0].update(lower=0.29, upper=0.33, scale=1.0)
    path = plan_file(tmp_path, targets=data["targets"])

    class Result:
        def __init__(self, deck):
            grid = np.arange(0, 0.65, 0.1)
            value = deck.structure.layers[0].doping_Na / 1e18
            self.analyses = {"forward": (grid, np.full(len(grid), value))}
        def analyses_to_dict(self):
            return {key: [x.tolist(), y.tolist()] for key, (x, y) in self.analyses.items()}

    monkeypatch.setattr("opentcad.io.deck.run_deck", Result)
    out = tmp_path / "search"
    assert main(["design", "run", str(path), "-o", str(out)]) == 0
    evidence = json.loads((out / "design.json").read_text())
    assert evidence["stop_reason"] == "target_met"
    assert len(evidence["attempts"]) == 2
    for row in evidence["attempts"]:
        assert (out / row["deck"]).is_file() and (out / row["result"]).is_file()
        assert row["completion"]["forward"]["observed_points"] == 7
    assert (out / "best.yaml").is_file()
    assert main(["design", "run", str(path), "-o", str(out)]) == 2


@pytest.mark.parametrize("stop,expected", [("budget_exhausted", 1), ("search_stalled", 1),
                                          ("no_valid_candidates", 2)])
def test_exit_status_distinguishes_unmet_targets_from_failed_search(tmp_path, monkeypatch, stop, expected):
    from opentcad.design import DesignResult
    path = plan_file(tmp_path)
    monkeypatch.setattr("opentcad.design.run_design", lambda *a, **kw:
                        DesignResult(tmp_path / "out", stop, [], None))
    assert main(["design", "run", str(path), "-o", str(tmp_path / "out")]) == expected


def test_cli_prompt_writes_review_and_explicit_plain_plan_without_running(tmp_path, monkeypatch):
    from opentcad.assist.design import DesignDraft, DesignProposal, REVIEW_NOTE
    plan = load_design(EXAMPLE).to_dict()
    plan["limitations"].append(REVIEW_NOTE)
    result = DesignDraft(proposal=DesignProposal(questions=["Confirm current target"]),
                         design=plan, attempts=1)
    monkeypatch.setattr("opentcad.assist.design.draft_design", lambda *a, **kw: result)
    monkeypatch.setattr("opentcad.design.run_design", lambda *a, **kw: pytest.fail("draft ran"))
    review, output = tmp_path / "draft.json", tmp_path / "plan.json"
    args = ["design", "draft", "Tune PN doping", "--base", str(BASE),
            "-o", str(review), "--plan-out", str(output)]
    assert main(args) == 0
    assert json.loads(review.read_text())["status"] == "unaccepted"
    assert REVIEW_NOTE in json.loads(output.read_text())["limitations"]
    assert main(args) == 1  # existing files are never silently overwritten


def test_wrong_units_and_draft_envelope_fail_actionably(tmp_path, capsys):
    data = load_design(EXAMPLE).to_dict()
    data["targets"][0]["unit"] = "A"
    path = plan_file(tmp_path, targets=data["targets"])
    assert main(["design", "check", str(path)]) == 1
    assert "A/cm" in capsys.readouterr().err
    path.write_text(json.dumps({"draft_schema": "opentcad.design-draft/v1", "design": data}))
    assert main(["design", "check", str(path)]) == 1
    assert "unknown fields" in capsys.readouterr().err
