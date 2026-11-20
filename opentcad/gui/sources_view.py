"""
opentcad/gui/sources_view.py — show a run's provenance record in Streamlit.

``show_sources(prov, key=...)`` renders a ``Record.to_dict()``: every value
the run read with the source it cites, the models and their references,
the sources (with DOI links), the files read and the code version.
"""
from __future__ import annotations

import json

import streamlit as st

from opentcad.provenance import KINDS, summarize


def _short(value) -> str:
    if isinstance(value, dict):
        return ", ".join(f"{k} {_short(v)}" for k, v in value.items())
    if isinstance(value, float):
        return f"{value:.6g}"
    return str(value)


def show_sources(prov: dict, *, key: str) -> None:
    """Render a provenance dict. ``key`` keeps widget keys unique per page."""
    if not prov:
        st.caption("No provenance was recorded for this run.")
        return
    gaps = prov.get("without_source", 0)
    st.caption(summarize(prov) + (". Values marked “none recorded” have no source "
                                  "in their file or code yet." if gaps else "."))
    only = st.toggle("Only values without a source", value=False, key=f"{key}_missing",
                     disabled=not gaps)
    rows = [{"Where": v["group"], "Value": v["name"], "Number": _short(v["value"]),
             "Source": ", ".join(v["sources"]) or "none recorded",
             "Note": v.get("note", ""), "File": v.get("file", "")}
            for v in prov.get("values", []) if not (only and v["sources"])]
    st.dataframe(rows, hide_index=True, width="stretch")

    if prov.get("models"):
        st.markdown("**Models**")
        st.dataframe([{"Kind": m["category"], "Model": json.dumps(m["model"]),
                       "Source": ", ".join(m["sources"]) or "none recorded"}
                      for m in prov["models"]], hide_index=True, width="stretch")

    if prov.get("sources"):
        st.markdown("**Sources**")
        st.dataframe(
            [{"ID": sid, "Kind": KINDS.get(s.get("kind", "literature"), s.get("kind")),
              "Reference": s["cite"],
              "Link": (f"https://doi.org/{s['doi']}" if s.get("doi") else s.get("url")),
              "Note": s.get("note", "")}
             for sid, s in prov["sources"].items()],
            hide_index=True, width="stretch",
            column_config={"Link": st.column_config.LinkColumn("Link")})

    with st.expander("Files, inputs and code version"):
        code = prov.get("code", {})
        line = f"OpenTCAD {code.get('opentcad', '?')}, Python {code.get('python', '?')}"
        if code.get("git_commit"):
            line += f", commit {code['git_commit'][:12]}"
            if code.get("git_modified"):
                line += " (with uncommitted changes)"
        st.caption(line)
        if code.get("packages"):
            st.caption(", ".join(f"{k} {v}" for k, v in code["packages"].items()))
        for i in prov.get("inputs", []):
            st.caption("Input: " + ", ".join(f"{k} {v}" for k, v in i.items()))
        st.dataframe([{"File": f["path"], "Kind": f.get("kind", ""),
                       "SHA-256": (f.get("sha256") or "")[:16]}
                      for f in prov.get("files", [])], hide_index=True, width="stretch")
    st.download_button("Download provenance (JSON)", json.dumps(prov, indent=2),
                       file_name="provenance.json", mime="application/json",
                       key=f"{key}_download")
