"""Replay knot/event preservation and isolated network assembly."""

import numpy as np
import pytest
from examples.microrobot import tcad_electrode_replay as replay


def test_duplicate_policy_preserves_events_and_roundtrip_knots():
    time = np.array([0.0, 1e-9, 1e-9, 2e-9])
    voltage = np.array([[0.0, 0.1, 0.1, 0.2]] * 3)
    t, v, dropped = replay.prepare_history(time, voltage)
    assert dropped == 1 and len(t) == 3
    assert f"{t[1]:.17g} {v[0, 1]:.17g}" in replay.stimulus(t, v)
    voltage[0, 2] = 0.11
    with pytest.raises(ValueError, match="duplicate time"):
        replay.prepare_history(time, voltage)


def test_full_isolated_network_and_no_controller_seed():
    deck = replay.build_deck()
    assert deck.count(" metal_history") == 2
    assert "electrode_rc cdl=400p qmax=2600p rf=1g" in deck
    assert "electrode_stable cdl=400p qmax=2600p rf=1g" in deck
    for tag in ["rc", "stable"]:
        assert f"Rs_{tag}_a {tag}_sa {tag}_bulk 10meg" in deck
        assert f"Rs_{tag}_r {tag}_sr {tag}_bulk 1meg" in deck
    for text in ["Xclock", "Bpvlogic", "Xdriver", "uic", ".ic ", ".nodeset"]:
        assert text not in deck
