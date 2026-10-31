"""Deletion-only retained-copy proof, with unchanged names and options."""

from examples.microrobot import tcad_feedback_fix as fix


def test_retained_active_lines_identical_and_other_copy_removed():
    source = fix.SOURCE.read_text()
    for tag, other in [("rc", "stable"), ("stable", "rc")]:
        deck = fix.build_deck(tag)
        assert f"Xlogic_{tag} {tag}_logic logic_history" in deck
        assert f"Xlogic_{other} " not in deck
        assert f"Vp_{other}_r " not in deck
        for line in source.splitlines():
            if line.startswith(("Xlogic_" + tag + " ", "Vp_" + tag + "_")) or (
                line.split() and line.split()[0].endswith("_" + tag)
            ):
                assert line in deck
        assert "tran 25n .00025 0 25n" in deck
        assert ".options method=gear maxord=2 reltol=1e-6 abstol=1e-15" in deck
