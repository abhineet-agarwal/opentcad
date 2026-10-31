"""Relevant assembly and completion checks; no simulator invocation."""

import re
import numpy as np
from examples.microrobot import tcad_controller as tc
from examples.microrobot import tcad_logic_isolation as isolation


def test_logic_source_clock_and_held_reset_preserved_actuator_absent():
    table = tc.load_table()
    deck = isolation.build_deck(table)
    original = tc.build_deck(table)
    assert (
        re.search(r"^Bpvlogic .*$", deck, re.M).group()
        == re.search(r"^Bpvlogic .*$", original, re.M).group()
    )
    assert re.search(r"(?ms)^\.subckt microrobot_clock\b.*?^\.ends[^\n]*", deck).group() in original
    for text in [
        "Bpvlo ",
        "Bpvhi ",
        "Xda ",
        "Xdb ",
        "Xreturn ",
        "Rsa ",
        "Vsupervisor_driver",
        "Xphases",
        "Xmonitor",
        "Xready",
    ]:
        assert text not in deck
    assert "Vreset_control supervisor_state 0 0" in deck
    assert "Xff clk feedback reset_n" in deck
    assert "Clogic logic_raw 0 2p" in deck


def test_abort_marker_rejects_even_full_length_zero_exit():
    columns = [
        "time",
        "v(light)",
        "v(logic_raw)",
        "v(logic)",
        "v(clk)",
        "v(q0)",
        "v(reset_n)",
        "v(bn)",
        "v(bp)",
        "v(supervisor_state)",
    ]
    data = np.zeros((2, len(columns)))
    data[:, 0] = [0, isolation.STOP]
    result = isolation.analyze(columns, data, {"aborted": True, "returncode": 0}, tc.load_table())
    assert result["complete"] is False
    assert "abort" in result["failure"]


def test_partial_transient_rejected():
    columns = [
        "time",
        "v(light)",
        "v(logic_raw)",
        "v(logic)",
        "v(clk)",
        "v(q0)",
        "v(reset_n)",
        "v(bn)",
        "v(bp)",
        "v(supervisor_state)",
    ]
    data = np.zeros((2, len(columns)))
    data[:, 0] = [0, 80e-6]
    result = isolation.analyze(columns, data, {"aborted": False, "returncode": 0}, tc.load_table())
    assert result["complete"] is False
    assert "stop" in result["failure"]
