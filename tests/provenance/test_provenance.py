"""Provenance: sources in data files, recording what a run reads, run records."""
from __future__ import annotations

import ast
import contextlib
import io
import json
from pathlib import Path

import pytest
import yaml

from opentcad.materials.database import (DEFAULT_SOURCE, MaterialFileError, load_material,
                                         params_from_dict)
from opentcad.provenance import (CODATA_2018, Record, Source, format_table, parse_sources,
                                 recording, sources_for)

ROOT = Path(__file__).resolve().parents[2]
DECKS = ROOT / "examples" / "decks"
PARAMS = ROOT / "opentcad" / "materials" / "params"
DOPANTS = ROOT / "opentcad" / "process" / "doping" / "data"

# The shipped values that cite no source. Citing one means removing it here;
# a new uncited value fails the test. Phase 3 asks for this list to be empty.
UNCITED = {
    "Si": {"bandgap.varshni_alpha", "bandgap.varshni_beta_K", "Nc_cm3_300K",
           "mobility_constant.electron_cm2_Vs", "mobility_constant.hole_cm2_Vs",
           "recombination.tau_n_s", "recombination.tau_p_s", "recombination.Et_eV",
           "recombination.B_rad_cm3_per_s", "velocity_saturation.vsat_h_cm_s",
           "velocity_saturation.beta_e", "velocity_saturation.beta_h"},
    "SiO2": {"electron_affinity_eV"},
}


# ---- sources in files --------------------------------------------------------
def test_source_is_checked():
    with pytest.raises(ValueError, match="non-empty"):
        Source("")
    with pytest.raises(ValueError, match="kind"):
        Source("x", kind="hearsay")
    with pytest.raises(ValueError, match="unknown source key"):
        Source.from_dict({"cite": "x", "page": 3})
    assert Source("x", doi="10.1/abc").link == "https://doi.org/10.1/abc"


def test_cite_entries_resolve_most_specific_first():
    raw = {"a": {"x": 1, "y": 2}, "b": 3,
           "sources": {"s1": {"cite": "one"}, "s2": {"cite": "two"}},
           "cite": {"a": "s1", "a.y": ["s1", "s2"]}}
    cited = parse_sources(raw)
    assert [s.cite for s in sources_for(cited, "a.x")] == ["one"]
    assert [s.cite for s in sources_for(cited, "a.y")] == ["one", "two"]
    assert sources_for(cited, "b") == ()


@pytest.mark.parametrize("cite, match", [
    ({"a.z": "s1"}, "isn't a value or block"),
    ({"a": "nope"}, "not in 'sources'"),
    ({"a": []}, "source key or a list"),
])
def test_bad_cite_entries_are_errors(cite, match):
    raw = {"a": {"x": 1}, "sources": {"s1": {"cite": "one"}}, "cite": cite}
    with pytest.raises(ValueError, match=match):
        parse_sources(raw, "f.yaml")


def test_material_file_with_a_bad_citation_does_not_load():
    raw = yaml.safe_load((PARAMS / "Si.yaml").read_text())
    raw["cite"]["recombination.tau_x"] = "green1990"
    with pytest.raises(MaterialFileError, match="recombination.tau_x"):
        params_from_dict(raw, "Si")


@pytest.mark.parametrize("symbol", sorted(UNCITED))
def test_shipped_material_values_cite_a_source_or_are_listed(symbol):
    assert set(load_material(symbol).uncited()) == UNCITED[symbol]


def test_shipped_dopant_tables_cite_their_values():
    for path in sorted(DOPANTS.glob("*.yaml")):
        raw = yaml.safe_load(path.read_text())
        cited = parse_sources(raw, path.name)
        blocks = ["moments"] if "moments" in raw else ["intrinsic", "fair"]
        for b in blocks:
            if b in raw:
                assert sources_for(cited, b), f"{path.name}: {b} cites nothing"


def test_n_i_cites_the_paper_that_gives_its_value():
    (src,) = load_material("Si").sources_of("ni_cm3_300K")
    assert src.doi == "10.1063/1.1529297" and "9.65e9" in src.note


def test_code_references_have_dois():
    from opentcad.device.models import references
    tree = ast.parse(Path(references.__file__).read_text())
    names = [t.id for n in tree.body if isinstance(n, ast.Assign) for t in n.targets]
    assert names and all(getattr(references, n).doi.startswith("10.") for n in names)


# ---- recording reads ---------------------------------------------------------
def test_reading_a_material_value_records_it_with_its_source():
    si = load_material("Si")
    with recording() as rec:
        si.band_structure.ni_cm3_300K
        si.recombination.tau_n_s
    ni = rec.values[("Silicon", "ni_cm3_300K")]
    assert ni.value == pytest.approx(9.65e9) and ni.sources[0].doi == "10.1063/1.1529297"
    assert ni.file == "opentcad/materials/params/Si.yaml"
    assert rec.values[("Silicon", "recombination.tau_n_s")].sources == ()
    si.band_structure.Nc_cm3_300K               # outside a recording: nothing
    assert ("Silicon", "Nc_cm3_300K") not in rec.values


def test_block_items_record_every_value():
    si = load_material("Si")
    with recording() as rec:
        dict(si.mobility_klaassen.items())
    names = {n for g, n in rec.values if g == "Silicon"}
    assert "mobility_klaassen.mu_max_e" in names and len(names) == 31


def test_defaulted_values_say_so():
    raw = {"is_insulator": True, "permittivity_relative": 7.5, "material": "Ox"}
    ox = params_from_dict(raw, "Ox")
    with recording() as rec:
        ox.mobility_klaassen.mu_max_e
    assert rec.values[("Ox", "mobility_klaassen.mu_max_e")].sources == (DEFAULT_SOURCE,)


def test_overrides_and_fits_cite_themselves(tmp_path):
    from opentcad.calibrate import apply_overrides, write_material_variant
    si = load_material("Si")
    tried = apply_overrides(si, {"mobility_lombardi.C_e": 2e4})
    assert tried.sources_of("mobility_lombardi.C_e")[0].kind == "override"
    assert tried.sources_of("mobility_lombardi.B_e")[0].doi == "10.1109/16.622611"
    path = write_material_variant(tmp_path / "lab" / "Si.yaml", si,
                                  {"mobility_lombardi.C_e": 2e4},
                                  calibration={"calibrated_against": "my wafer"})
    fit = params_from_dict(yaml.safe_load(path.read_text()), "Si")
    (src,) = fit.sources_of("mobility_lombardi.C_e")
    assert src.kind == "fit" and src.cite == "Fitted to my wafer"
    assert fit.uncited() == si.uncited()


def test_sky130_variant_cites_the_fit_for_fitted_values_only():
    raw = yaml.safe_load((ROOT / "validation/sky130/materials/sky130/Si.yaml").read_text())
    v = params_from_dict(raw, "Si")
    for name in raw["calibration"]["fitted"]:
        assert v.sources_of(name)[0].kind == "fit"
    assert v.sources_of("mobility_lombardi.tau_e")[0].doi == "10.1109/16.622611"


def test_process_tables_record_what_they_give():
    from opentcad.process.doping.anneal import diffusivity_intrinsic
    from opentcad.process.doping.pearson_iv import moments_for
    from opentcad.process.topography.oxidation import coefficients
    with recording() as rec:
        moments_for("boron", 20.0)
        diffusivity_intrinsic("B", 1273.0)
        coefficients("dry")
    m = rec.values[("Implant: boron in Si", "moments at 20 keV")]
    assert "interpolated between the 10 and 30 keV" in m.note and m.sources
    assert rec.values[("Diffusion: boron in Si", "intrinsic (D0, Ea)")].value == {
        "D0_cm2s": 0.76, "Ea_eV": 3.46}
    assert rec.models["oxidation"]["sources"][0].doi == "10.1063/1.1713945"
    assert rec.values[("Physical constants", "k_B [eV/K]")].sources == (CODATA_2018,)


# ---- records -----------------------------------------------------------------
def test_record_numbers_sources_and_counts_gaps():
    rec = Record()
    a = Source("A", doi="10.1/a")
    rec.add_value("G", "x", 1.0, (a,))
    rec.add_value("G", "y", 2.0, (a,))
    rec.add_value("G", "z", 3.0)
    rec.add_value("G", "x", 1.5, (a,))
    d = rec.to_dict()
    assert d["sources"] == {"S1": {"cite": "A", "kind": "literature", "doi": "10.1/a"}}
    assert d["without_source"] == 1
    x = next(v for v in d["values"] if v["name"] == "x")
    assert x["value"] == 1.5 and "changed during the run" in x["note"]
    assert d["code"]["opentcad"]
    table = format_table(d)
    assert "NO SOURCE" in table and "https://doi.org/10.1/a" in table
    assert "x = 1.5" not in format_table(d, only_missing=True)
    json.dumps(d)


def test_recordings_nest():
    with recording() as outer:
        with recording() as inner:
            from opentcad.provenance import note_value
            note_value("G", "inner", 1)
        note_value("G", "outer", 2)
    assert set(inner.values) == {("G", "inner")} and set(outer.values) == {("G", "outer")}


# ---- runs --------------------------------------------------------------------
@pytest.mark.requires_devsim
def test_a_run_records_values_models_and_inputs(tmp_path, capsys):
    from opentcad.cli import main as cli_main
    from opentcad.io.deck import load_deck, run_deck
    with contextlib.redirect_stdout(io.StringIO()):
        res = run_deck(load_deck(DECKS / "nmos_implanted.yaml"))
    d = res.provenance.to_dict()
    groups = {v["group"] for v in d["values"]}
    assert {"Silicon", "SiO2", "Physical constants", "Implant: arsenic in Si",
            "Diffusion: boron in Si"} <= groups
    assert {m["category"] for m in d["models"]} == {"mobility", "recombination", "bgn",
                                                    "statistics"}
    assert d["inputs"][0]["what"] == "simulation" and len(d["inputs"][0]["content_sha256"]) == 64
    assert any(f["path"].endswith("Si.yaml") and len(f["sha256"]) == 64 for f in d["files"])
    gaps = {(v["group"], v["name"]) for v in d["values"] if not v["sources"]}
    assert ("Silicon", "recombination.tau_n_s") in gaps
    assert d["without_source"] == len(gaps)

    out = tmp_path / "r.json"
    with contextlib.redirect_stdout(io.StringIO()):
        assert cli_main(["run", str(DECKS / "pn_diode.yaml"), "-o", str(out)]) == 0
    prov = json.loads(out.read_text())["provenance"]
    assert prov["inputs"][-1]["what"] == "simulation file"
    capsys.readouterr()
    assert cli_main(["sources", str(out), "--missing"]) == 0
    listing = capsys.readouterr().out
    assert "recombination.tau_n_s" in listing and "permittivity_relative" not in listing
    stale = tmp_path / "old.json"
    stale.write_text(json.dumps({"analyses": {}}))
    assert cli_main(["sources", str(stale)]) == 1
