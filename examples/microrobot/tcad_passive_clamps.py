"""One passive-equivalent held-input startup diagnostic; no released operation."""

import difflib
import json
from pathlib import Path
import re
import shutil

import numpy as np

from . import tcad_controller as tc
from . import tcad_actuator_startup as startup

EVIDENCE = tc.HERE / "results/tcad_passive_clamps"
LOCAL = tc.HERE / "local_runs/tcad_passive_clamps"
SOURCE = startup.EVIDENCE / "actuator_startup.spice"
REMOVED_PORTS = ["Vsupervisor_reset", "Vsupervisor_driver", "Vphase"]
CLAMPS = {
    "reset": ("Bsupervisor_reset_hi", "Bsupervisor_reset_lo", "reset_n"),
    "ready": ("Bsupervisor_driver_hi", "Bsupervisor_driver_lo", "driver_ready"),
    "phase_A": ("Bpahi", "Bpalo", "pa"),
    "phase_B": ("Bpbhi", "Bpblo", "pb"),
}


def build_deck():
    deck = SOURCE.read_text()
    for port in REMOVED_PORTS:
        deck, count = re.subn(r"^" + port + r" .*\n", "", deck, flags=re.M)
        if count != 1:
            raise ValueError("Unexpected supply probe count: " + port)
        deck = deck.replace(f"i({port}) ", "")
    for name, (high, low, node) in CLAMPS.items():
        deck, count = re.subn(r"^" + high + r" .*\n", "", deck, flags=re.M)
        if count != 1:
            raise ValueError("Unexpected high branch count: " + high)
        deck, count = re.subn(r"^" + low + r" .*$", f"Rfixed_{name} {node} 0 10k", deck, flags=re.M)
        if count != 1:
            raise ValueError("Unexpected low branch count: " + low)
    return deck


def analyze(columns, data, execution, table):
    # Compatibility inputs to the existing audit are algebraic zeros, not new
    # measurements. Every associated high-side terminal branch was identically
    # open under fixed-zero control. Remove these entries from measured results.
    augmented_columns = columns + [f"i({port})" for port in REMOVED_PORTS]
    augmented = np.column_stack([data, np.zeros((len(data), len(REMOVED_PORTS)))])
    result = startup.analyze(augmented_columns, augmented, execution, table)
    result["shape"] = list(data.shape)
    if not np.isfinite(data).all():
        return result
    v = dict(zip(columns, data.T, strict=True))
    removed_names = ["reset_bridge", "driver_ready_bridge", "phase_bridges"]
    loads = result["energy_J"]["measured_load_ports"]
    for name in removed_names:
        if loads.pop(name) != 0:
            raise ValueError("Removed open port must be analytically zero")
    result["analytical_zero_removed_port_energy_J"] = {port: 0.0 for port in REMOVED_PORTS}
    resistor_loss = {
        name: float(np.trapezoid(v[f"v({node})"] ** 2 / 10000, v["time"]))
        for name, (_, _, node) in CLAMPS.items()
    }
    result["energy_J"]["passive_clamp_resistor_losses"] = resistor_loss
    result["resistor_loss_scope"] = (
        "Component dissipation already supplied through measured native circuit rail ports; reported separately, not added a second time to supply-load accounting"
    )
    result["measurement_change"] = (
        "Three unloaded open-high-side probes removed; expected zero deliveries are analytical zeros, not measured port energies"
    )
    result["scope"] = (
        "Passive 10k held-input startup diagnostic only; no released-controller, phase, bending or autonomous validation"
    )
    return result


def run():
    if EVIDENCE.exists() or LOCAL.exists():
        raise FileExistsError("Passive-clamp destinations must be fresh")
    EVIDENCE.mkdir(parents=True)
    deck = build_deck()
    prior = SOURCE.read_text()
    if re.findall(r"^Bpv.*$", deck, re.M) != re.findall(r"^Bpv.*$", prior, re.M):
        raise RuntimeError("DD source expressions changed")
    equivalence = {
        name: {
            "removed_high": high,
            "replaced_low": low,
            "new_resistor": f"Rfixed_{name} {node} 0 10k",
            "reason": "Fixed zero control: high current identically0, low current V(output)/10000",
        }
        for name, (high, low, node) in CLAMPS.items()
    }
    tc.write_json(
        EVIDENCE / "configuration.json",
        {
            "scope": __doc__,
            "source_deck_sha256": tc.sha(SOURCE),
            "equivalence_per_branch": equivalence,
            "removed_probes": REMOVED_PORTS,
            "unchanged": "All TCAD expressions, geometry, clock, DFF, proxy, driver/electrode/Pt-return, storage, ramp, solver and duration",
            "duration_s": 250e-6,
            "max_step_s": 25e-9,
            "caveat": "Equivalent terminal equations do not imply identical numerical conditioning or establish an abort root cause",
        },
    )
    tc.write_json(
        EVIDENCE / "execution_counts.json",
        {"transients": 1, "fine": 0, "rescue": 0, "DC": 0, "DD": 0, "layout": 0},
    )
    shutil.copy2(Path(__file__), EVIDENCE / "runner_as_executed.py")
    (EVIDENCE / "deck.diff").write_text(
        "".join(
            difflib.unified_diff(
                prior.splitlines(True),
                deck.splitlines(True),
                fromfile="held_actuator_addback",
                tofile="passive_clamps",
            )
        )
    )
    execution = tc.execute(LOCAL, deck)
    for source, target in [
        ("bench.spice", "passive_clamps.spice"),
        ("ngspice.log", "ngspice.log"),
        ("execution.json", "execution.json"),
    ]:
        shutil.copy2(LOCAL / source, EVIDENCE / target)
    if (LOCAL / "controller.dat").exists():
        columns, data = tc.read_data(LOCAL / "controller.dat")
        result = analyze(columns, data, execution, tc.load_table())
        result["raw_sha256"] = tc.sha(LOCAL / "controller.dat")
        result["raw_local_path"] = str(LOCAL / "controller.dat")
    else:
        result = {"complete": False, "failure": "No transient output"}
    tc.write_json(EVIDENCE / "metrics.json", result)
    tc.write_json(
        EVIDENCE / "status.json",
        {
            "status": "Complete passive held-input startup"
            if result["complete"]
            else "Incomplete passive held-input startup",
            "acceptance": "Pending Astra review",
            "scope": "Held inputs only; no phase, bending or autonomous-controller validation",
        },
    )
    (EVIDENCE / "README.md").write_text(f"""# Passive-equivalent held-input startup

Exactly one **250 µs / 25 ns** diagnostic. Complete: **{result["complete"]}**. No fine, rescue, DC, DD or layout run was added.

The frozen actuator add-back deck changes only four fixed-zero input bridges: their high-side current branches, which are identically open, and three unused high-side rail probes are removed; each low branch becomes an explicit10 kΩ resistor to ground. Configuration.json records the equivalence per branch and deck.diff records every edit. Existing numerical zero controls remain signal-only instrumentation. All TCAD source expressions, extracted clock, native DFF/feedback, proxy, transistor drivers, working/Pt-return electrodes, storage, ramp and solver remain unchanged.

Removed probe deliveries are expected algebraic zeros, not measured native power removals. The saved-data audit supplies these zeros only as compatibility inputs, removes them from measured-load results, and labels them separately. Each clamp resistor's V²/R dissipation is retained as component bookkeeping; it is already supplied through measured native circuit ports and is not counted again in total load energy. All power, clamp and KCL checks on an incomplete trace are prefix-only.

Equivalent held-input terminal equations may have different numerical conditioning; a changed outcome does not identify a unique cause. Completion would establish only this held-input startup diagnostic, with no released phase, bending or autonomous operation. Raw waveforms stay local. Previous frozen evidence and defaults are unchanged.

```text
MPLCONFIGDIR=/tmp/opentcad-mpl .venv/bin/python -m examples.microrobot.tcad_passive_clamps
```

The runner refuses existing destinations. No submission, publication, push or fabrication occurred.
""")
    tc.write_json(
        EVIDENCE / "sha256.json",
        {
            p.name: tc.sha(p)
            for p in sorted(EVIDENCE.iterdir())
            if p.is_file() and p.name != "sha256.json"
        },
    )
    print(
        json.dumps(
            {
                k: result.get(k)
                for k in ["complete", "actual_stop_s", "failure", "diagnostic_checks"]
            },
            indent=2,
        )
    )
    return result


if __name__ == "__main__":
    run()
