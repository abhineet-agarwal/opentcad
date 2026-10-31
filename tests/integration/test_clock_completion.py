"""Clock adapter tests use synthetic output; they do not rerun a PDK matrix."""
import gzip
from types import SimpleNamespace
from pathlib import Path

import numpy as np
import pytest

from examples.microrobot import clock


@pytest.fixture
def bench(tmp_path, monkeypatch):
    pdk = tmp_path/'pdk/sky130A'
    library = pdk/'libs.tech/ngspice/sky130.lib.spice'
    library.parent.mkdir(parents=True)
    library.write_text('* installed model placeholder\n')
    cells = pdk/'libs.ref/sky130_fd_sc_hd/spice/sky130_fd_sc_hd.spice'
    cells.parent.mkdir(parents=True)
    preamble = ('* Copyright 2020 The SkyWater PDK Authors\n*\n'
                '* Licensed under the Apache License, Version 2.0 (the "License");\n'
                '* you may not use this file except in compliance with the License.\n'
                '* You may obtain a copy of the License at\n*\n'
                '*     https://www.apache.org/licenses/LICENSE-2.0\n*\n'
                '* Unless required by applicable law or agreed to in writing, software\n'
                '* distributed under the License is distributed on an "AS IS" BASIS,\n'
                '* WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.\n'
                '* See the License for the specific language governing permissions and\n'
                '* limitations under the License.\n*\n'
                '* SPDX-License-Identifier: Apache-2.0\n\n\n')
    cells.write_text(preamble+'.subckt sky130_fd_sc_hd__dfxtp_1 a b\n.ends\n'
                     '.subckt sky130_fd_sc_hd__inv_1 a b\n.ends\n')
    macro = tmp_path/'physical.spice'
    macro.write_text('* Physical macro has no internal voltage probe\n'
                     '.subckt microrobot_clock clk vdd vss bn bp\n.ends\n')
    monkeypatch.setenv('PDK_ROOT', str(tmp_path/'pdk'))
    monkeypatch.setattr(clock.shutil, 'which', lambda _: '/fake/ngspice')
    return macro, preamble


def waveform(with_bias=True):
    t = np.linspace(0., .004, 4001)
    rail = 1.8*np.minimum(t/100e-6, 1.)
    clk = rail*(np.sin(2*np.pi*10000*t) > 0)
    div = rail*(np.sin(2*np.pi*5000*t) > 0)
    data = np.column_stack([t, rail, clk, .49*rail/1.8, .9*rail/1.8,
                            np.full(len(t), 30e-9), np.full(len(t), 1e-9), div])
    return np.column_stack([data, np.full(len(t), 5e-9)]) if with_bias else data


def fake_simulator(monkeypatch, data, *, stdout='', returncode=0):
    def run(*args, cwd, **kwargs):
        np.savetxt(Path(cwd)/'clock.dat', data, header='synthetic adaptive columns', comments='')
        return SimpleNamespace(returncode=returncode, stdout=stdout, stderr='')
    monkeypatch.setattr(clock.subprocess, 'run', run)


@pytest.mark.parametrize('problem', [
    'abort', 'abort_complete', 'incomplete', 'overshoot', 'nonfinite', 'shape',
    'one_row', 'backward', 'late_start', 'negative_start',
])
def test_clock_rejects_partial_or_invalid_before_preview(tmp_path, monkeypatch, bench, problem):
    data = waveform()
    log = ''
    if problem == 'abort':
        data = data[:2000]
        log = 'tran simulation(s) aborted'
    elif problem == 'abort_complete':
        log = 'tran simulation(s) aborted'
    elif problem == 'incomplete':
        data = data[:-1]
    elif problem == 'overshoot':
        data[-1, 0] += 1e-6
    elif problem == 'nonfinite':
        data[100, 2] = np.nan
    elif problem == 'shape':
        data = data[:, :-1]
    elif problem == 'one_row':
        data = data[-1:]
    elif problem == 'late_start':
        data = data[1:]
    elif problem == 'negative_start':
        data[0, 0] = -1e-15
    else:
        data[100, 0] = data[99, 0]-1e-8
    fake_simulator(monkeypatch, data, stdout=log)
    dest = tmp_path/problem
    info, returned = clock.clock_case(dest)
    assert not info['passed'] and returned is None
    assert info['actual_stop_s'] == pytest.approx(data[-1, 0])
    assert (dest/'clock.spice').is_file() and (dest/'ngspice.log').is_file()
    assert (dest/'clock.dat').is_file() and (dest/'failure.json').is_file()
    assert not (dest/'metrics.json').exists() and not (dest/'waveform.csv.gz').exists()
    expected = {'abort': 'aborted', 'abort_complete': 'aborted', 'incomplete': 'stop',
                'overshoot': 'stop', 'nonfinite': 'nonfinite', 'shape': 'shape',
                'one_row': 'shape', 'backward': 'decreases',
                'late_start': 'start at zero', 'negative_start': 'start at zero'}
    assert expected[problem] in info['failure']


@pytest.mark.parametrize('rounding_s', [-4e-12, 4e-12])
def test_clock_accepts_wrdata_endpoint_rounding(tmp_path, monkeypatch, bench, rounding_s):
    data = waveform()
    data[-1, 0] += rounding_s
    fake_simulator(monkeypatch, data)
    info, returned = clock.clock_case(tmp_path/'rounded')
    assert info['passed'] and info['simulation_completed']
    assert info['actual_stop_s'] == data[-1, 0]
    assert returned is not None


def test_default_bias_measurement_and_exact_installed_notice(tmp_path, monkeypatch, bench):
    fake_simulator(monkeypatch, waveform())
    dest = tmp_path/'with_bias'
    info, data = clock.clock_case(dest)
    assert info['passed'] and info['simulation_completed']
    assert info['actual_stop_s'] == .004 and data.shape[1] == 9
    assert info['mean_power_W'] == pytest.approx(1.8*31e-9)
    assert info['bias_reference_power_W'] == pytest.approx(1.8*5e-9)
    assert info['bias_reference_power_available'] is True
    assert any('canonical schematic' in item and 'not extracted' in item
               for item in info['limitations'])
    assert 'i(v.xclock.vbias)' in (dest/'clock.spice').read_text()
    assert (dest/'receiver_cells.spice').read_text().startswith(bench[1])


def test_physical_macro_without_bias_probe_reports_unavailable(tmp_path, monkeypatch, bench):
    fake_simulator(monkeypatch, waveform(with_bias=False))
    dest = tmp_path/'without_bias'
    info, data = clock.clock_case(dest, circuit_path=bench[0], measure_bias_current=False)
    assert info['passed'] and info['actual_stop_s'] == .004 and data.shape[1] == 8
    assert info['mean_power_W'] == pytest.approx(1.8*31e-9)
    assert info['analog_clock_power_W'] == pytest.approx(1.8*30e-9)
    assert info['first_divider_stage_power_W'] == pytest.approx(1.8*1e-9)
    assert info['bias_reference_power_W'] is None
    assert info['bias_reference_power_available'] is False
    assert any('supplied-netlist provenance' in item for item in info['limitations'])
    assert not any('routing is not extracted' in item for item in info['limitations'])
    assert 'i(v.xclock.vbias)' not in (dest/'clock.spice').read_text()
    with gzip.open(dest/'waveform.csv.gz', 'rt') as source:
        assert 'reference_current_A' not in source.readline()
