"""Focused, simulator-free guardrails for the bounded coupled experiment."""

import re

import numpy as np
import pytest

from examples.microrobot import tcad_controller as tc


def test_dd_table_configuration_and_no_extrapolation():
    table = tc.load_table()
    assert len(table.voltage_V) == 29
    assert table.current(0.425, 1000, 1080) * 1.7 == pytest.approx(186.8925e-9, rel=1e-5)
    with pytest.raises(ValueError, match="outside characterized"):
        table.current(0.701, 1000, 1080)


def test_sources_verify_every_knot_midpoint_and_scaling():
    table = tc.load_table()
    deck, voltage, expected = tc.source_preflight(table)
    assert len(voltage) == 57
    assert all(any(abs(v - x) < 1e-14 for x in voltage) for v in table.voltage_V)
    assert len(expected) == 6
    assert "dc Vcell 0 .7 .0125" in deck
    for fraction in [0, 0.5, 1]:
        assert expected[f"i(Vn2f{int(fraction * 10)})"] == pytest.approx(
            expected[f"i(Vn4f{int(fraction * 10)})"]
        )


def test_coupled_deck_preserves_native_clock_and_no_phase_power_sources():
    deck = tc.build_deck(tc.load_table())
    body = re.search(
        r"(?ms)^\.subckt microrobot_clock\b.*?^\.ends[^\n]*", tc.CLOCK.read_text()
    ).group()
    assert body in deck
    assert "dfrtp_1" in deck
    assert "Aff1" in deck and "Aff2" not in deck
    assert "Bpa pa_source" not in deck and "Vpa " not in deck
    assert "Vphase logic phase_supply 0" in deck
    assert "Bpahi phase_supply pa I=" in deck
    assert "Bpvlogic 0 logic_raw" in deck and "v(logic_raw,0)/4" in deck
    assert "Bpvhi mid cellhi" in deck and "v(cellhi,mid)/2" in deck
    assert "Xreturn er sr tr micro_electrode cdl=400p qmax=2600p rf=1g" in deck
    assert "Xda pa driver_ready ea_driver drivers_logic drivers_act drivers_mid 0" in deck
    assert "UIC" not in deck and ".ic " not in deck


def test_fine_deck_only_changes_timestep():
    table = tc.load_table()
    coarse, fine = tc.build_deck(table), tc.build_deck(table, 12.5e-9)
    assert re.sub(r"^tran .*$", "", coarse, flags=re.M) == re.sub(
        r"^tran .*$", "", fine, flags=re.M
    )


def test_mechanics_constant_coverage_matches_analytic_relaxation():
    t = np.linspace(0, 0.008, 101)
    theta = np.full(len(t), 0.6)
    assert tc.mechanics(t, theta) == pytest.approx(1e4 * (1 - np.exp(-t / 0.05)), abs=1e-9)


def test_runner_refuses_nonfresh_outputs_before_execution(tmp_path):
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    with pytest.raises(FileExistsError, match="fresh"):
        tc.run(evidence=evidence, local=tmp_path / "local")


def test_full_stop_with_zero_exit_is_rejected_when_simulator_reports_abort():
    deck = tc.build_deck(tc.load_table())
    columns = ["time"] + re.search(r"^save (.*)$", deck, flags=re.M).group(1).split()
    data = np.zeros((2, len(columns)))
    data[:, 0] = [0, tc.STOP]
    for name in ["v(ta)", "v(tb)", "v(tr)"]:
        data[:, columns.index(name)] = 0.5
    result = tc.analyze(columns, data, {"aborted": True, "returncode": 0}, tc.load_table())
    assert result["actual_stop_s"] == tc.STOP
    assert result["complete"] is False
    assert result["all_gates_pass"] is False
    assert "abort" in result["failure"]
