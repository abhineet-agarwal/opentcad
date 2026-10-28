"""Generic example: recover terminal parameters, predict MPP and export SPICE.

Run: python examples/08_pv_compact.py
Synthetic data are explicitly generated from a known model; no foundry or
paper calibration is implied. See the microrobot application for plotted-data fits.
"""
from pathlib import Path

import numpy as np

from opentcad.device.compact import SingleDiodePV, fit_single_diode


def main():
    reference = SingleDiodePV(2e-16, 1.3, 100e-9, series_cells=2)
    v = np.tile(np.linspace(0, 1.4, 101), 2)
    light = np.repeat([0, 1000], 101)
    fitted, diagnostics = fit_single_diode(v, reference.current_A(v, light), light,
                                          series_cells=2, uncertainty_A=1e-9)
    print("Recovered model:", fitted)
    print("MPP (V, A, W):", fitted.maximum_power_point())
    print("Diagnostics:", diagnostics)
    path = Path(__file__).with_suffix(".spice")
    path.write_text(fitted.spice_subcircuit())
    print("SPICE subcircuit:", path)


if __name__ == "__main__":
    main()
