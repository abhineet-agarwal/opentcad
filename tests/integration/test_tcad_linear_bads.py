"""Exact one-line control and positive-conductance terminal equivalence."""

import numpy as np
import pytest
from examples.microrobot import tcad_linear_bads as linear
from examples.microrobot import tcad_passive_adsorption as rc


def test_exact_single_line_substitution():
    prior = linear.SOURCE.read_text()
    deck = linear.build_deck()
    assert deck.replace(linear.NEW, linear.OLD) == prior
    assert deck.count(linear.NEW) == 1
    assert "v(metal,adsnode)" in linear.NEW
    assert "tanh" not in linear.NEW and "v(metal,solution)" not in linear.NEW


def test_equivalent_terminal_current_and_nonnegative_branch_work():
    voltage = np.linspace(-2, 2, 41)
    current = rc.CADS[:, None] / rc.TAU * voltage
    assert current == pytest.approx(voltage / rc.RADS[:, None], rel=1e-14, abs=0)
    assert np.all(current * voltage >= 0)
