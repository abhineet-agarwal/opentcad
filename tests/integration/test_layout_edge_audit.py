"""Divider audit must reject missed events despite a plausible mean frequency."""

import numpy as np
from examples.microrobot.layout import divider_edge_audit


def waveforms(missing=False):
    t = np.linspace(0, 20, 40001)
    rail = 1.7 + 0.05 * np.sin(t)
    clock = rail * (np.sin(2 * np.pi * (t - 0.2)) > 0)
    q = np.zeros_like(t)
    for j, rise in enumerate(np.arange(0.2, 20, 2)):
        # Some Q threshold crossings slightly precede clock's 50% crossing.
        offset = 0.002 if j % 2 else -0.002
        if missing and j == 5:
            rise += 1
        q[(t >= rise + offset) & (t < rise + 0.6)] = 1
    return t, rail, clock, q * rail


def test_threshold_alignment_does_not_invent_missed_edges():
    assert divider_edge_audit(*waveforms(), start_s=1)["edge_audit_passed"]


def test_one_missed_event_fails_edge_audit():
    result = divider_edge_audit(*waveforms(missing=True), start_s=1)
    assert not result["edge_audit_passed"]
    assert 3 in result["clock_edges_per_divided_period"]
