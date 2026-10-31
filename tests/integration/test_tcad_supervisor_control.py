"""Simulator-free contract and deck checks for the provisional supervisor."""

import re

from examples.microrobot import tcad_controller as tc
from examples.microrobot import tcad_supervisor_control as control


def test_global_latch_restarts_only_after_both_ON_not_stale_qualifiers():
    # Actuator OFF must discard previously qualified logic, too.
    logic = [1.7, 1.7, 1.55, 1.55, 1.7, 1.4, 1.55, 1.7]
    actuator = [1.7, 1.7, 1.39, 1.7, 1.7, 1.7, 1.7, 1.7]
    time = [0, 0.0002, 0.0003, 0.0004, 0.0005, 0.0006, 0.0007, 0.0008]
    assert control.supervisor_state(logic, actuator, time).tolist() == [
        False,
        True,
        False,
        False,
        True,
        False,
        False,
        True,
    ]


def test_hysteresis_band_holds_previous_state_and_fixed_hold_is_enforced():
    assert control.supervisor_state([1.7] * 3, [1.7] * 3, [0, 0.000199, 0.0002]).tolist() == [
        False,
        False,
        True,
    ]
    assert control.supervisor_state(
        [1.7, 1.5, 1.45], [1.7, 1.45, 1.7], [0.0002, 0.0003, 0.0004]
    ).tolist() == [True, True, False]


def test_deck_removes_native_supervisor_keeps_identical_DD_and_measured_bridges():
    table = tc.load_table()
    original = tc.build_deck(table)
    deck = control.build_deck(table)
    assert re.findall(r"^Bpv.*$", deck, re.M) == re.findall(r"^Bpv.*$", original, re.M)
    for name in [
        "Xready",
        "Xmonitor",
        "Xdriverbuffer",
        "Vresetlogic",
        "Vresetact",
        "Vmonitor",
        "Vdriverbuffer",
    ]:
        assert re.search(r"^" + name + r" ", deck, re.M) is None
    assert "Vsupervisor_reset logic supervisor_reset_supply 0" in deck
    assert "Vsupervisor_driver act supervisor_driver_supply 0" in deck
    assert "Vt=0.5 Vh=0.5" in deck
    assert "time<200u ? -1 : min((v(logic)-1.45)/0.15,(v(act)-1.40)/0.10)" in deck
    assert "v(ready)" not in deck
    assert "Xff clk feedback reset_n" in deck
