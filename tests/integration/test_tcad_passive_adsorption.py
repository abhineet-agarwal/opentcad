"""Small-signal RC derivation and exact bounded deck transformation."""

import re
import numpy as np
import pytest
from examples.microrobot import tcad_passive_adsorption as rc


def test_RC_orientation_time_constant_and_energy_identity():
    assert rc.CADS == pytest.approx([812.5e-12, 812.5e-12, 8.125e-9])
    assert rc.RADS == pytest.approx([24.6153846153846e6, 24.6153846153846e6, 2.46153846153846e6])
    assert rc.CADS * rc.RADS == pytest.approx(np.full(3, 0.02))
    eta = 0.0004
    time = 0.00025
    decay = np.exp(-time / rc.TAU)
    capacitor_voltage = eta * (1 - decay)
    assert 0.5 + capacitor_voltage / (4 * rc.WIDTH) > 0.5
    work = rc.CADS * eta**2 * (1 - decay)
    storage = 0.5 * rc.CADS * capacitor_voltage**2
    heat = 0.5 * rc.CADS * eta**2 * (1 - decay**2)
    assert storage + heat == pytest.approx(work, rel=1e-12, abs=0)


def test_only_electrode_state_block_changes_no_source_probe_changes():
    source = rc.SOURCE.read_text()
    original = rc.verified_parameters(source)
    deck = rc.build_deck()
    replacement = re.search(
        r"(?ms)^\* Linearized at eta=.*?^\.ends micro_electrode[^\n]*", deck
    ).group()
    assert deck.replace(replacement, original, 1) == source
    assert "Rads metal adsnode {tau*4*width/qmax}" in deck
    assert "Cads adsnode solution {qmax/(4*width)}" in deck
    assert not re.search(r"^(Cstate|Bstate|Bads) ", deck, re.M)
    assert re.findall(r"^(save|wrdata).*$", source, re.M) == re.findall(
        r"^(save|wrdata).*$", deck, re.M
    )
