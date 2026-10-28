"""SKY130 clock candidate: electrical validation before physical layout.

Uses installed ngspice/PDK only; transistor parameters come from SKY130.
PV data, geometry choices and circuit corner tests retain separate provenance.
"""
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

import numpy as np

from opentcad.device.compact import SingleDiodePV

HERE = Path(__file__).parent


def clock_case(destination, *, corner="tt", voltage_V=1.8, temperature_C=26.85,
               ramp_s=100e-6, stop_s=0.004, timestep_s=50e-9, pv_model=None,
               output_load_F=0.0, pv_storage_F=2e-12, load_standard_cell=True,
               circuit_path=None, relative_tolerance=1e-4):
    """Simulate cold startup without initial-condition/UIC or electrical kick.

    The source starts at zero, then ramps; intentional 10/12 fF asymmetry is
    part of the design. Pass ``pv_model`` for an illuminated three-cell supply,
    using 150 um²/cell under an explicitly assumed identical-current-density
    scaling from the measured large cell. PV capacitance is not inferred;
    a chosen 2 pF storage capacitor is external to this clock macro. A real
    SKY130 DFF plus feedback inverter loads the clock by default; its supply
    current is measured separately from the analog clock.
    """
    if corner not in {"tt", "ss", "ff", "sf", "fs"}:
        raise ValueError("Unknown process corner")
    if not 0 < relative_tolerance <= 1e-3:
        raise ValueError("Relative tolerance must be positive and at most 1e-3")
    if not 1.4 <= voltage_V <= 1.94 or not -40 <= temperature_C <= 125:
        raise ValueError("Outside this candidate's experiment envelope")
    executable = shutil.which("ngspice")
    if not executable:
        raise FileNotFoundError("ngspice is required for this optional experiment")
    pdk = Path(os.environ.get("PDK_ROOT", "/usr/local/share/pdk")) / "sky130A"
    library = pdk / "libs.tech/ngspice/sky130.lib.spice"
    if not library.is_file():
        raise FileNotFoundError(f"Missing installed PDK library: {library}")
    dest = Path(destination).resolve()
    dest.mkdir(parents=True, exist_ok=True)
    (dest / ".spiceinit").write_text("set ngbehavior=hsa\nset num_threads=1\n")
    circuit = Path(circuit_path or HERE / "circuits/starved_clock.spice").read_text()
    if pv_model is None:
        supply = f"VDD supply 0 PWL(0 0 1u 0 {ramp_s+1e-6:.12g} {voltage_V})\n"
        supply_kind = "ideal voltage ramp"
    else:
        cell = replace(pv_model, series_cells=1).scaled_current(150 / 540)
        a = cell.photocurrent_A
        n = cell.ideality
        supply = (f"Vlight illumination 0 PWL(0 0 1u 0 {ramp_s+1e-6:.12g} 1000)\n"
                  f".model fitted_pv D(IS={cell.saturation_A:.12g} N={n:.12g} "
                  f"TNOM={cell.temperature_K-273.15:.12g} EG=0 XTI=0)\n"
                  f"Bph1 0 pv1 I={{{a:.12g}*v(illumination)/1000}}\n"
                  f"Bph2 pv1 pv2 I={{{a:.12g}*v(illumination)/1000}}\n"
                  f"Bph3 pv2 supply I={{{a:.12g}*v(illumination)/1000}}\n"
                  "Dp1 pv1 0 fitted_pv\nDp2 pv2 pv1 fitted_pv\n"
                  f"Dp3 supply pv2 fitted_pv\nCstore supply 0 {pv_storage_F:.12g}\n")
        supply_kind = "three scaled S2E-fit cells, optical ramp, chosen storage capacitor"
    digital = "Vlogic supply digital_supply 0\n"
    source_cell_hash = None
    if load_standard_cell:
        cell_library = pdk / "libs.ref/sky130_fd_sc_hd/spice/sky130_fd_sc_hd.spice"
        cells = cell_library.read_text()
        selected = []
        for name in ("sky130_fd_sc_hd__dfxtp_1", "sky130_fd_sc_hd__inv_1"):
            match = re.search(r"(?ms)^\.subckt " + name + r"\b.*?^\.ends[^\n]*", cells)
            if match is None:
                raise ValueError(f"Installed standard-cell library lacks {name}")
            selected.append(match.group())
        imported = ("* Unmodified cells imported from the installed SKY130 HD library.\n"
                    "* Copyright SkyWater PDK Authors; Apache-2.0; see source PDK.\n"
                    + "\n".join(selected) + "\n")
        (dest / "receiver_cells.spice").write_text(imported)
        source_cell_hash = hashlib.sha256(imported.encode()).hexdigest()
        digital += ('.include "receiver_cells.spice"\n'
                    "Xff clk feedback 0 0 digital_supply digital_supply div2 sky130_fd_sc_hd__dfxtp_1\n"
                    "Xfeedback div2 0 0 digital_supply digital_supply feedback sky130_fd_sc_hd__inv_1\n")
    else:
        digital += "Runused digital_supply 0 1e20\nRprobe div2 0 1e20\n"
    deck = (f"* Our low-power clock candidate; {supply_kind}\n"
            f'.lib "{library}" {corner}\n.temp {temperature_C:.12g}\n'
            + circuit + "\n" + supply
            + "Vsense supply vdd 0\nXclock clk vdd 0 bn bp microrobot_clock\n"
            + digital
            + f"Coutput clk 0 {output_load_F:.12g}\n"
            + f".options method=gear maxord=2 reltol={relative_tolerance:.12g} abstol=1e-15\n"
            + ".control\nset wr_vecnames\nset wr_singlescale\n"
            + f"tran {timestep_s:.12g} {stop_s:.12g} 0 {timestep_s:.12g}\n"
            + "wrdata clock.dat v(vdd) v(clk) v(bn) v(bp) i(Vsense) i(Vlogic) v(div2) i(v.xclock.vbias)\n"
            + "quit\n.endc\n.end\n")
    (dest / "clock.spice").write_text(deck)
    try:
        result = subprocess.run([executable, "-b", "clock.spice"], cwd=dest,
                                capture_output=True, text=True, timeout=180)
    except subprocess.TimeoutExpired as exc:
        (dest / "ngspice.log").write_text(str(exc))
        return {"passed": False, "failure": "simulation timeout", "corner": corner}, None
    (dest / "ngspice.log").write_text(result.stdout + result.stderr)
    if result.returncode or not (dest / "clock.dat").is_file():
        return {"passed": False, "failure": "simulator error", "corner": corner}, None
    data = np.loadtxt(dest / "clock.dat", skiprows=1)
    preview_step = max(1, len(data)//1200)
    np.savetxt(dest / "waveform.csv", data[::preview_step], delimiter=",", fmt="%.9e",
        header="time_s,supply_V,clock_V,bias_n_V,bias_p_V,analog_current_A,"
        "first_ff_current_A,divide2_V,reference_current_A", comments="")
    t, vdd, clk, bn, bp, analog_current, digital_current, div2, bias_current = data.T
    current = analog_current + digital_current
    select = t > max(0.6 * stop_s, ramp_s * 1.2)
    rail = float(np.mean(vdd[select]))
    threshold = vdd / 2
    crossings = np.flatnonzero((clk[:-1] < threshold[:-1]) & (clk[1:] >= threshold[1:]))
    crossings = crossings[t[crossings] > t[select][0]]
    times = t[crossings] + (threshold[crossings]-clk[crossings]) * (
        t[crossings+1]-t[crossings]) / (clk[crossings+1]-clk[crossings])
    frequency = float(1 / np.mean(np.diff(times))) if len(times) >= 5 else None
    divided_crossings = np.flatnonzero((div2[:-1] < threshold[:-1])
        & (div2[1:] >= threshold[1:]) & select[1:])
    divided_frequency = float(1 / np.mean(np.diff(t[divided_crossings]))) \
        if len(divided_crossings) >= 3 else None
    power = float(np.trapezoid((vdd * current)[select], t[select]) / np.ptp(t[select]))
    startup = np.flatnonzero((clk[:-1] < threshold[:-1]) & (clk[1:] >= threshold[1:])
                            & (vdd[1:] > rail*0.8))
    passed = bool(frequency and np.min(clk[select]) < 0.1*rail
                  and np.max(clk[select]) > 0.9*rail and power > 0)
    if load_standard_cell:
        passed = bool(passed and divided_frequency
                      and abs(divided_frequency/frequency - 0.5) < 0.025)
    info = {"passed": passed, "corner": corner, "voltage_V": voltage_V,
            "passed_meaning": "sustained clock, full output swing and first DFF divide-by-two; not a PV power-budget pass",
            "temperature_C": temperature_C, "ramp_s": ramp_s, "stop_s": stop_s,
            "max_timestep_s": timestep_s, "relative_tolerance": relative_tolerance,
            "output_load_F": output_load_F,
            "supply": supply_kind, "steady_supply_V": rail, "frequency_Hz": frequency,
            "mean_power_W": power,
            "analog_clock_power_W": float(np.trapezoid((vdd*analog_current)[select],
                                                        t[select]) / np.ptp(t[select])),
            "bias_reference_power_W": float(np.trapezoid((vdd*bias_current)[select],
                                                          t[select]) / np.ptp(t[select])),
            "first_divider_stage_power_W": float(np.trapezoid((vdd*digital_current)[select],
                                                               t[select]) / np.ptp(t[select])),
            "mean_current_A": float(np.trapezoid(current[select], t[select]) / np.ptp(t[select])),
            "pv_storage_F": pv_storage_F if pv_model else None,
            "standard_cell_receiver": load_standard_cell,
            "standard_cells_sha256": source_cell_hash,
            "first_divider_output_Hz": divided_frequency,
            "clock_min_V": float(np.min(clk[select])),
            "clock_max_V": float(np.max(clk[select])),
            "first_high_crossing_s": float(t[startup[0]]) if len(startup) else None,
            "bias_n_mean_V": float(np.mean(bn[select])),
            "bias_p_mean_V": float(np.mean(bp[select])),
            "netlist_sha256": hashlib.sha256(circuit.encode()).hexdigest(),
            "library_sha256": hashlib.sha256(library.read_bytes()).hexdigest(),
            "startup": "zero supply operating point, then ramp; no UIC or seeded node voltage",
            "waveform_csv": "Decimated for plots only; metrics use the full transient",
            "limitations": ["Supply/temperature dependent bias, not a PTAT reference",
                "PDK MIM timing/bias capacitors; routing parasitics not extracted",
                "No statistical mismatch; remaining divider and drivers not in this bench"]}
    if not passed:
        info["failure"] = "clock swing, power or first-DFF divide-by-two check failed"
    (dest / "metrics.json").write_text(json.dumps(info, indent=2) + "\n")
    return info, data


def run_clock_matrix(destination, model: SingleDiodePV):
    dest = Path(destination)
    cases = [("tt", v, 26.85, 100e-6) for v in (1.6, 1.7, 1.8, 1.9, 1.94)]
    cases += [(corner, 1.8, 26.85, 100e-6) for corner in ("ss", "ff", "sf", "fs")]
    cases += [("tt", 1.8, temp, 100e-6) for temp in (0, 85)]
    cases += [("tt", 1.8, 26.85, 2e-3)]
    results = []
    for corner, v, temp, ramp in cases:
        name = f"{corner}_{v}_{temp}_{ramp}"
        result, _ = clock_case(dest / name, corner=corner, voltage_V=v,
                               temperature_C=temp, ramp_s=ramp,
                               stop_s=max(0.004, ramp*3), output_load_F=2e-15)
        results.append(result)
        print(name, result.get("frequency_Hz"), result.get("mean_power_W"),
              "PASS" if result["passed"] else "FAIL", flush=True)
    pv, data = clock_case(dest / "pv_startup", pv_model=model,
                          stop_s=0.004, timestep_s=50e-9, output_load_F=2e-15)
    results.append(pv)
    for corner in ("sf", "fs"):
        loaded, _ = clock_case(dest / f"pv_startup_{corner}", pv_model=model,
            corner=corner, stop_s=0.004, timestep_s=50e-9, output_load_F=2e-15)
        results.append(loaded)
    smaller_storage, _ = clock_case(dest / "pv_storage_1pf", pv_model=model,
        stop_s=0.004, timestep_s=50e-9, output_load_F=2e-15, pv_storage_F=1e-12)
    held_out, _ = clock_case(dest / "withheld_1v75", voltage_V=1.75,
                             output_load_F=2e-15)
    # Halve timestep at the nominal operating point and compare electrical metrics.
    finer, _ = clock_case(dest / "timestep_half", timestep_s=25e-9, output_load_F=2e-15)
    nominal = next(r for r in results if r.get("corner") == "tt"
                   and r.get("voltage_V") == 1.8 and r.get("temperature_C") == 26.85)
    convergence = {name: abs(finer[name]/nominal[name]-1)
                   for name in ("frequency_Hz", "mean_power_W")
                   if finer.get(name) and nominal.get(name)}
    array_max_W = model.maximum_power_point()[2]/2 * 3 * 150/540
    for record in results:
        record["logic_PV_array_max_W_at_1sun"] = array_max_W
        if record.get("mean_power_W"):
            record["within_nominal_PV_maximum_power"] = record["mean_power_W"] <= array_max_W
    summary = {"cases": results, "timestep_half": finer,
               "pv_storage_1pf": smaller_storage,
               "withheld_1v75": held_out,
               "timestep_relative_changes": convergence,
               "scope": "deterministic cases, not a complete combined PVT or mismatch signoff"}
    pdk = Path(os.environ.get("PDK_ROOT", "/usr/local/share/pdk")) / "sky130A"
    nodeinfo = pdk / ".config/nodeinfo.json"
    if nodeinfo.is_file():
        summary["pdk_nodeinfo"] = json.loads(nodeinfo.read_text())
    summary["ngspice_version"] = subprocess.run(["ngspice", "--version"],
                                                capture_output=True, text=True).stdout.strip()
    (dest / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    return summary, data


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=HERE / "results/clock_final")
    args = parser.parse_args()
    fit = json.loads((HERE / "results/published/pv_fit.json").read_text())
    run_clock_matrix(args.output, SingleDiodePV(**fit["fitted_terminal_model"]))
