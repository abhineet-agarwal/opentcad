"""Re-audit the saved partial waveform without invoking a simulator."""

from pathlib import Path
import json
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))
from examples.microrobot import tcad_controller as tc  # noqa: E402


def main():
    evidence = Path(__file__).resolve().parent
    raw = tc.LOCAL / "nominal_25ns/controller.dat"
    columns, data = tc.read_data(raw)
    values = dict(zip(columns, data.T, strict=True))
    execution = json.loads((evidence / "nominal_25ns_execution.json").read_text())
    result = tc.analyze(columns, data, execution, tc.load_table())
    result.update(
        raw_sha256=tc.sha(raw),
        raw_local_path=str(raw),
        scope="All numeric energy, clamp and KCL passes are prefix-only; failed completion prevents functional acceptance",
    )
    tc.write_json(evidence / "metrics.json", {"nominal_25ns": result})
    bounds = {
        name: {
            "minimum_V": float(values[f"v({name})"].min()),
            "maximum_V": float(values[f"v({name})"].max()),
            "final_V": float(values[f"v({name})"][-1]),
        }
        for name in ["logic", "act", "mid", "ready", "reset_n", "driver_ready"]
    }
    early = (
        (values["v(act)"] >= 0.5)
        & (values["v(driver_ready)"] > 0.5 * values["v(act)"])
        & (values["v(logic)"] < 1.4)
    )
    starts = np.flatnonzero(np.diff(np.r_[False, early, False].astype(int)) == 1)
    stops = np.flatnonzero(np.diff(np.r_[False, early, False].astype(int)) == -1) - 1
    intervals = [
        {
            "first_saved_s": float(values["time"][a]),
            "last_saved_s": float(values["time"][b]),
            "samples": int(b - a + 1),
            "logic_min_V": float(values["v(logic)"][a : b + 1].min()),
            "logic_max_V": float(values["v(logic)"][a : b + 1].max()),
        }
        for a, b in zip(starts, stops, strict=True)
    ]
    observations = {
        "scope": "Saved prefix only; no physical root cause or sustained behavior inferred",
        "trouble_equation": "vreturn#branch",
        "last_time_s": float(values["time"][-1]),
        "finite": bool(np.isfinite(data).all()),
        "shape": list(data.shape),
        "rail_reset_ranges": bounds,
        "early_release_definition": "act >= 0.5 V AND driver_ready > act/2 AND logic < 1.4 V; sampled interval bounds",
        "early_release_intervals": intervals,
        "supply_energy_relative_residual": result["energy_J"]["supply_balance_residual"]
        / result["energy_J"]["PV_delivered"],
    }
    tc.write_json(evidence / "prefix_observations.json", observations)
    print(json.dumps(observations, indent=2))


if __name__ == "__main__":
    main()
