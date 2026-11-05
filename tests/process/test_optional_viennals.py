"""
ViennaLS is optional: without it, recipes, doping-only flows and the plugin
registry still work, and only topography steps fail, with an error that
names ViennaLS. Run in a subprocess with `import viennals` blocked.
"""
import subprocess
import sys
import textwrap

_SCRIPT = textwrap.dedent("""
    import sys
    sys.modules["viennals"] = None          # any `import viennals` now fails

    from opentcad.geometry.formats import Material
    from opentcad.geometry.structure import Structure
    from opentcad.plugins import registered_steps
    from opentcad.process import run_recipe
    from opentcad.process.topography import Recipe

    assert "Deposit" in registered_steps()
    s = (Structure(width_um=1.0, name="noviennals")
         .add_substrate("body", 0.5, Material.SI, doping_Na=1e15)
         .add_contact("top", 0.0, 1.0, "body", surface="top"))
    out = run_recipe(s, Recipe().implant("As", 30, 1e14).anneal(1000, 10),
                     mesh_size_um=0.1)
    assert out.meshfield.Nd.max() > 0
    Recipe().deposit(Material.SIO2, 0.01).summary()

    try:
        run_recipe(s, Recipe().deposit(Material.SIO2, 0.01), mesh_size_um=0.1)
    except ImportError as exc:
        assert "ViennaLS" in str(exc), exc
        print("OK")
    else:
        raise SystemExit("topography ran without ViennaLS")
""")


def test_doping_and_registry_work_without_viennals():
    res = subprocess.run([sys.executable, "-c", _SCRIPT],
                         capture_output=True, text=True, timeout=300)
    assert res.returncode == 0, res.stderr[-2000:]
    assert res.stdout.strip().endswith("OK")
