"""Bounded offline precision and exact deck-transformation checks."""

from examples.microrobot import tcad_stable_adsorption as stable


def test_current_partials_crossover_bounds_and_nonzero_offset_grid():
    audit = stable.offline_audit()
    assert audit["passed"]
    assert audit["boundary_signs_pass"]
    assert audit["max_current_error_A"] < 5e-21
    assert audit["max_voltage_offset_partial_error_A_per_V"] < 5e-21
    assert audit["max_tau_partial_error_A_per_s"] < 5e-19
    assert audit["offsets_V"] == [-0.1, 0, 0.05]
    assert audit["precision_decimal_digits"] == 80


def test_only_current_expression_and_function_change():
    prior = stable.SOURCE.read_text()
    deck = stable.build_deck()
    assert deck.replace(stable.FUNCTION + "\n", "").replace(stable.NEW, stable.OLD) == prior
    assert stable.correction(0) == 0
    assert stable.correction_derivative(0) == 0
