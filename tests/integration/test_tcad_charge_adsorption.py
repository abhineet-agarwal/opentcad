"""Nonlinear series-branch algebra, orientation and bounded transformation."""

from examples.microrobot import tcad_charge_adsorption as charge


def test_full_nonlinear_coverage_dynamics_and_boundary_signs():
    result = charge.algebra_audit()
    assert result["passed"]
    assert result["grid_points"] == 451
    assert result["eta_range_V"] == [-2, 2]
    assert result["maximum_abs_dtheta_error_per_s"] < 1e-12
    assert result["theta0_boundary_derivative_nonnegative"]
    assert result["theta1_boundary_derivative_nonpositive"]


def test_only_resistor_and_explanatory_comment_change_no_duplicate_adsorption():
    prior = charge.SOURCE.read_text()
    deck = charge.build_deck()
    restored = deck.replace(charge.NEW, charge.OLD).replace(
        "* Nonlinear series adsorption; u=V(adsnode,solution)=4width*(theta-0.5).",
        "* Linearized at eta=offset=0, theta0=0.5; third pin is now physical Cads node.",
    )
    assert restored == prior
    assert deck.count("Bads_series metal adsnode I=") == 1
    assert deck.count("Cads adsnode solution {qmax/(4*width)}") == 1
    assert "Cstate " not in deck and "Bstate " not in deck
    assert "Bads metal solution " not in deck
