"""Exact retained-line and reduced feedback assembly guards."""

import re
from examples.microrobot import tcad_actuator_feedback_replay as feedback


def test_retained_lines_namespaced_only_no_metal_replay_or_logic_dynamics():
    source = feedback.SOURCE.read_text()
    deck = feedback.build_deck()
    for tag in ["rc", "stable"]:
        for label in feedback.KEEP:
            line = re.search(r"^" + re.escape(label) + r" .*$", source, re.M).group()
            assert (
                feedback.copy_line(line, tag).replace(" micro_electrode", " electrode_" + tag)
                in deck
            )
    for text in [
        "Xclock",
        "Xff ",
        "Xfeedback",
        "Xproxy",
        "Bpvlogic",
        "metal_history",
        "uic",
        ".ic ",
    ]:
        assert text not in deck
    assert "Xlogic_rc rc_logic logic_history" in deck
    assert "option > options_effective.txt" in deck
    assert ".options method=gear maxord=2 reltol=1e-6 abstol=1e-15" in deck
