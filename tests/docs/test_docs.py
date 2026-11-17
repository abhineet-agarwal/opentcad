"""The documentation stays true: links resolve, every page is in the GitBook
sidebar, the tutorial code runs, and the API reference matches the code."""
from __future__ import annotations

import re
import sys
import warnings
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DOCS_DIR = ROOT / "docs"
GITHUB = re.compile(r"https://(?:github\.com/abhineet-agarwal/opentcad/(?:blob|tree)/main|"
                    r"raw\.githubusercontent\.com/abhineet-agarwal/opentcad/main)/([^#?]*)")
PAGES = sorted(DOCS_DIR.rglob("*.md"))
OTHER = [ROOT / "README.md", ROOT / "CONTRIBUTING.md", ROOT / "CHANGELOG.md",
         ROOT / "PHASES.md", ROOT / "validation/sky130/README.md",
         ROOT / "examples/catalog/README.md"]

# The docs link to examples, tools and root files that an sdist doesn't ship.
pytestmark = pytest.mark.skipif(not (ROOT / ".git").exists() or not (ROOT / "tools").is_dir(),
                                reason="documentation checks need a repository checkout")

_FENCE = re.compile(r"^```.*?^```", re.S | re.M)
_LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")
_HEADING = re.compile(r"^#{1,6}\s+(.+?)\s*$", re.M)


def _rel(p: Path) -> str:
    return str(p.relative_to(ROOT))


def _anchors(md: Path) -> set[str]:
    """GitHub/GitBook-style heading anchors."""
    out = set()
    for h in _HEADING.findall(_FENCE.sub("", md.read_text())):
        h = re.sub(r"`|\*\*?|\[([^\]]*)\]\([^)]*\)", r"\1", h)
        out.add(re.sub(r"[^\w\- ]", "", h.lower()).replace(" ", "-"))
    return out


def _check(md: Path, target: str) -> str | None:
    """None if ``target`` (a link in ``md``) resolves, else why not."""
    m = GITHUB.match(target)
    if m:                                     # this repository on GitHub → a local file
        dest = ROOT / m.group(1)
    elif re.match(r"[a-z]+:", target):        # any other URL
        return None
    else:
        path = target.partition("#")[0]
        dest = (md.parent / path).resolve() if path else md
        if md.is_relative_to(DOCS_DIR) and not dest.is_relative_to(DOCS_DIR):
            return "leaves docs/; GitBook can't follow it, use the GitHub URL"
    if not dest.exists():
        return "no such file"
    anchor = target.partition("#")[2]
    if anchor and dest.suffix == ".md" and anchor not in _anchors(dest):
        return f"no heading #{anchor}"
    return None


@pytest.mark.parametrize("md", PAGES + OTHER, ids=_rel)
def test_links_resolve(md):
    broken = [f"{t} ({why})" for t in _LINK.findall(_FENCE.sub("", md.read_text()))
              if (why := _check(md, t))]
    assert not broken, f"{_rel(md)}: " + "; ".join(broken)


def test_every_page_is_in_the_sidebar():
    summary = DOCS_DIR / "SUMMARY.md"
    listed = {(DOCS_DIR / t).resolve() for t in _LINK.findall(summary.read_text())
              if not re.match(r"[a-z]+:", t)}
    missing = [_rel(p) for p in PAGES if p != summary and p.resolve() not in listed]
    assert not missing, f"add these pages to docs/SUMMARY.md: {missing}"


def test_gitbook_config_points_at_docs():
    config = (ROOT / ".gitbook.yaml").read_text()
    assert "root: ./docs/" in config and "summary: SUMMARY.md" in config


RUNNABLE = [DOCS_DIR / "getting_started.md", *sorted((DOCS_DIR / "tutorials").glob("0*.md")),
            DOCS_DIR / "visualization.md"]


@pytest.mark.requires_devsim
@pytest.mark.parametrize("md", RUNNABLE, ids=_rel)
def test_page_code_runs(md):
    """Every Python block on the page, in order, in one namespace."""
    import devsim as ds

    text = md.read_text()
    if "simulate" in text or "run_recipe(struct" in text or "oxidize(" in text:
        pytest.importorskip("viennals")
    if "viz import interactive" in text:
        pytest.importorskip("plotly")
        import plotly.graph_objects as go
        show, go.Figure.show = go.Figure.show, lambda self, *a, **k: None
    import matplotlib
    matplotlib.use("Agg")
    blocks = re.findall(r"```python\n(.*?)```", text, re.S)
    assert blocks, f"{_rel(md)} has no Python code"
    ns: dict = {}
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            for i, block in enumerate(blocks, 1):
                exec(compile(block, f"{_rel(md)} block {i}", "exec"), ns)
    finally:
        for device in list(ds.get_device_list()):
            ds.delete_device(device=device)
        if "viz import interactive" in text:
            go.Figure.show = show


@pytest.mark.skipif(sys.version_info < (3, 14),
                    reason="the API pages are generated with Python 3.14's annotation strings")
def test_api_reference_is_current():
    sys.path.insert(0, str(ROOT / "tools"))
    try:
        import gen_api_docs
    finally:
        sys.path.pop(0)
    files = gen_api_docs.build()
    stale = [n for n, text in files.items()
             if not (DOCS_DIR / "api" / n).exists() or (DOCS_DIR / "api" / n).read_text() != text]
    assert not stale, f"docs/api is out of date ({stale}); run: python tools/gen_api_docs.py"
