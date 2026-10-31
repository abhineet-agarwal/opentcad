"""Held-input assembly guards, without simulator execution."""

import re
from examples.microrobot import tcad_controller as tc
from examples.microrobot import tcad_actuator_startup as startup


def test_all_verified_DD_sources_and_actuator_network_restored():
    table = tc.load_table()
    deck = startup.build_deck(table)
    original = tc.build_deck(table)
    assert re.findall(r"^Bpv.*$", deck, re.M) == re.findall(r"^Bpv.*$", original, re.M)
    for line in [
        "Cstorelo mid 0 1p",
        "Cstorehi act_raw mid 1p",
        "Xda pa driver_ready",
        "Xdb pb driver_ready",
        "Xreturn er sr tr micro_electrode cdl=400p qmax=2600p rf=1g",
        "Rsa sa bulk 10meg",
        "Rsr sr bulk 1meg",
    ]:
        assert line in deck


def test_only_fixed_signal_controls_rail_powered_bridges_no_event_supervisor():
    deck = startup.build_deck(tc.load_table())
    for line in [
        "Vreset_control supervisor_state 0 0",
        "Vphase_command_A pan 0 0",
        "Vphase_command_B pbn 0 0",
        "Vsupervisor_reset logic supervisor_reset_supply 0",
        "Vsupervisor_driver act supervisor_driver_supply 0",
        "Vphase logic phase_supply 0",
    ]:
        assert line in deck
    for text in [
        "Xphases",
        "Aff0",
        "microrobot_event_phases",
        "Bsupervisor_input",
        "Ssupervisor",
        "supervisor_hysteresis",
        "Xmonitor ",
        "Xready ",
        "Xdriverbuffer ",
    ]:
        assert text not in deck
    assert (
        "Bsupervisor_driver_lo driver_ready 0 I={v(driver_ready)*(1-v(supervisor_state))/10000}"
        in deck
    )
    assert "Bpalo pa 0 I={v(pa)*(1-min(max(v(pan),0),1))/10000}" in deck
