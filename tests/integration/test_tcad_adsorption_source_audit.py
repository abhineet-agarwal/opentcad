"""Source-audit sign/scaling, parser and independent excitation guards."""

import numpy as np
import pytest
from examples.microrobot import tcad_adsorption_source_audit as audit


def test_oracle_sign_and_excitation_matrix_no_transient():
    case = {"name": "test", "m": 0.2, "x": 0.1, "s": 0.0, "qmax": "260p"}
    value, partials = audit.reference(case, "resistor")
    assert value == pytest.approx(0.1 / (0.02 / (260e-12 / 0.32)))
    assert partials[0] > 0 and partials[1] == -partials[0] and partials[2] == 0
    deck, records = audit.build_deck([case])
    assert len(records) == 9
    assert "tran " not in deck
    assert "ac lin 1 1 1" in deck
    assert "Vpk000 dk000 mk000 0" in deck
    for node in ["m", "x", "s"]:
        assert f"V{node}k000" in deck


def test_native_parser_complex_sign_and_scaling(tmp_path):
    path = tmp_path / "ac.dat"
    row = np.r_[
        1.0,
        np.array(
            [[-2.0, 0.0], [1.0, 0.0], [0.0, 0.0], [0.0, 0.0], [2.0, 0.0], [-2.0, 0.0], [0.0, 0.0]]
        ).ravel(),
    ]
    np.savetxt(path, row[None, :], header="frequency values", comments="")
    parsed = audit.parse_native(path, True)
    assert parsed[0] == -2 and parsed[1] == 1
    assert parsed[4] + parsed[0] == 0 and parsed[5] - parsed[0] == 0
    assert audit.within(1e-23, 0.0, 1e-22, 1e-10)
    assert isinstance(audit.within(np.float64(0), 0.0, 1e-22, 1e-10), bool)
    assert not audit.within(2e-22, 0.0, 1e-22, 1e-10)
