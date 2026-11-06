"""
OpenTCAD assistant — describe a device or a change in plain language; a
local open-weights model drafts the simulation file; you review every
value it assumed, edit, check, and run it.

    streamlit run opentcad/gui/app.py     → "assistant" in the sidebar

The model is any OpenAI-compatible server (llama-server, Ollama, LM Studio,
vLLM). Without one, the page still loads, edits, checks and runs files.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import numpy as np
import streamlit as st
import yaml

from opentcad.assist import ChatClient, LLMError, draft_deck
from opentcad.assist.client import DEFAULT_URL
from opentcad.io.deck import DeckError, _Loader, deck_from_dict, dumps_deck, run_deck
from opentcad.viz import interactive as figs

st.set_page_config(page_title="OpenTCAD assistant", layout="wide")

EXAMPLES = Path(__file__).resolve().parents[3] / "examples" / "decks"
TEMPLATES = {"pn diode": "pn_diode.yaml", "NMOS (implanted)": "nmos_implanted.yaml"}

ss = st.session_state
ss.setdefault("deck_yaml", "")       # the file text (mirrors the editor)
ss.setdefault("editor", "")          # the editor widget's own state
ss.setdefault("draft", None)
ss.setdefault("result", None)
ss.setdefault("result_key", None)
ss.deck_yaml = ss.editor or ""       # pick up edits before anything uses them


def theme() -> str:
    try:
        return st.context.theme.type or "light"
    except Exception:
        return "light"


def leaves(node, path=""):
    if isinstance(node, dict):
        for k, v in node.items():
            yield from leaves(v, f"{path}.{k}" if path else str(k))
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from leaves(v, f"{path}[{i}]")
    else:
        yield path, node


def parse_yaml(text: str):
    """(deck, problems) for the editor text."""
    try:
        data = yaml.load(text, Loader=_Loader) if text.strip() else None
    except yaml.YAMLError as exc:
        return None, [("", f"not valid YAML: {exc}")]
    if data is None:
        return None, [("", "the file is empty")]
    try:
        return deck_from_dict(data), []
    except DeckError as exc:
        return None, exc.problems


# =============================================================================
# Sidebar: model server
# =============================================================================
with st.sidebar:
    st.subheader("Model server")
    url = st.text_input("URL", value=ss.get("llm_url", DEFAULT_URL),
                        help="Any OpenAI-compatible server. llama-server: "
                             "http://127.0.0.1:8080/v1 · Ollama: "
                             "http://127.0.0.1:11434/v1")
    model = st.text_input("Model", value=ss.get("llm_model", "local"),
                          help="The name the server expects (llama-server "
                               "ignores it).")
    ss.llm_url, ss.llm_model = url, model
    if st.button("Test connection"):
        try:
            names = ChatClient(base_url=url, model=model, api_key=None).models()
            st.success(f"Connected: {', '.join(names) or 'no models listed'}")
        except LLMError as exc:
            st.error(str(exc))
    st.caption("Small models (3B) do best editing a template; describing a "
               "whole device from scratch needs a larger one (7B+).")

st.title("Simulation assistant")

# =============================================================================
# 1. Ask
# =============================================================================
left, right = st.columns([2, 1])
with right:
    start = st.radio("Start from", ["the file below", *TEMPLATES, "nothing"],
                     help="The model edits this file; 'nothing' asks it to "
                          "write one from scratch.")
with left:
    request = st.text_area(
        "Describe the device, or the change",
        placeholder="e.g. Make the gate oxide 4 nm and sweep Vgs to 1.8 V",
        height=100)
    go_draft = st.button("Draft with the model", type="primary",
                         disabled=not request.strip())

if go_draft:
    current = None
    if start in TEMPLATES:
        current = deck_from_dict(yaml.load((EXAMPLES / TEMPLATES[start]).read_text(),
                                           Loader=_Loader)).to_dict()
    elif start == "the file below" and ss.deck_yaml.strip():
        deck, probs = parse_yaml(ss.deck_yaml)
        current = deck.to_dict() if deck else None
    client = ChatClient(base_url=url, model=model, api_key=None)
    with st.spinner("The model is drafting (checked and repaired automatically)…"):
        try:
            d = draft_deck(request, client=client, current=current)
        except LLMError as exc:
            st.error(str(exc))
            d = None
    if d is not None:
        ss.draft = {"flags": [(f.path, f.value, f.reason, f.declared) for f in d.flags],
                    "questions": d.questions, "problems": d.problems,
                    "attempts": d.attempts, "before": current}
        source = d.deck.to_dict() if d.deck is not None else d.data
        if source is not None:
            ss.deck_yaml = (dumps_deck(d.deck) if d.deck is not None else
                            yaml.safe_dump(source, sort_keys=False, allow_unicode=True))
            ss.editor = ss.deck_yaml

# =============================================================================
# 2. Review what the model did
# =============================================================================
dr = ss.draft
if dr:
    st.subheader("Review")
    if dr["problems"]:
        st.error(f"The draft still has {len(dr['problems'])} problem(s) after "
                 f"{dr['attempts']} attempt(s). Fix them in the file below:\n\n"
                 + "\n".join(f"- `{p}`: {m}" for p, m in dr["problems"]))
    else:
        st.success(f"Draft checks clean ({dr['attempts']} attempt(s)).")
    for q in dr["questions"]:
        st.info(f"The model asks: {q}")
    if dr["flags"]:
        st.warning(f"{len(dr['flags'])} value(s) were not in your request. "
                   "Check each before running.")
        st.dataframe(
            [{"path": p, "value": json.dumps(v) if not isinstance(v, str) else v,
              "model's reason": r or "(none given)",
              "declared by model": "yes" if dcl else "no"}
             for p, v, r, dcl in dr["flags"]],
            width="stretch", hide_index=True)
    else:
        st.caption("Every value in the file came from your request or the "
                   "file you started from.")
    if dr["before"] is not None:
        deck, _ = parse_yaml(ss.deck_yaml)
        if deck is not None:
            a, b = dict(leaves(dr["before"])), dict(leaves(deck.to_dict()))
            changes = [(k, a.get(k), b.get(k)) for k in sorted(set(a) | set(b))
                       if a.get(k) != b.get(k)]
            with st.expander(f"Changes from the starting file ({len(changes)})",
                             expanded=bool(changes)):
                for k, old, new in changes:
                    st.markdown(f"- `{k}`: {old!r} → **{new!r}**")

# =============================================================================
# 3. The file
# =============================================================================
st.subheader("Simulation file")
up_col, dl_col = st.columns([3, 1])
with up_col:
    uploaded = st.file_uploader("Load a .yaml file", type=["yaml", "yml"],
                                label_visibility="collapsed")
    if uploaded is not None and ss.get("uploaded_name") != uploaded.name:
        ss.uploaded_name = uploaded.name
        ss.deck_yaml = ss.editor = uploaded.read().decode()
        ss.draft = None
st.text_area("YAML", key="editor", height=360, label_visibility="collapsed")
ss.deck_yaml = ss.editor or ""
deck, problems = parse_yaml(ss.deck_yaml) if ss.deck_yaml.strip() else (None, [])
with dl_col:
    st.download_button("Download .yaml", data=ss.deck_yaml or "",
                       file_name=f"{deck.name if deck else 'simulation'}.yaml",
                       disabled=not ss.deck_yaml.strip())
if ss.deck_yaml.strip():
    if problems:
        st.error("\n".join(f"- `{p}`: {m}" if p else f"- {m}" for p, m in problems))
    else:
        st.success(f"Checks clean: {deck.name}, {len(deck.structure.layers)} "
                   f"layer(s), {len(deck.recipe)} step(s), "
                   f"{len(deck.analyses)} analysis/es.")

# =============================================================================
# 4. Run and show
# =============================================================================
if deck is not None and st.button("Run", type="primary"):
    with st.spinner("Running: process, mesh, device…"):
        try:
            res = run_deck(copy.deepcopy(deck))
            ss.result = {"mf": res.meshfield, "analyses": res.analyses,
                         "specs": [(a.name, a.type, a.args) for a in deck.analyses]}
            ss.result_key = hashlib.sha1(ss.deck_yaml.encode()).hexdigest()
        except Exception as exc:
            st.error(f"Run failed: {type(exc).__name__}: {exc}")

r = ss.result
if r:
    stale = ss.result_key != hashlib.sha1(ss.deck_yaml.encode()).hexdigest()
    if stale:
        st.caption("These results are from an earlier version of the file.")
    t = theme()
    mf = r["mf"]
    tab_s, tab_d, tab_r = st.tabs(["Structure", "Doping", "Results"])
    with tab_s:
        mesh = st.toggle("Show mesh", value=False)
        st.plotly_chart(figs.structure_map(mf, theme=t, show_mesh=mesh),
                        width="stretch", theme=None)
    with tab_d:
        st.plotly_chart(figs.doping_map(mf, theme=t), width="stretch",
                        theme=None)
        xmin, xmax = float(mf.bounds[0]), float(mf.bounds[1])
        x = st.slider("Cut at x [µm]", xmin, xmax, (xmin + xmax) / 2,
                      step=(xmax - xmin) / 200)
        try:
            st.plotly_chart(figs.doping_profile(mf, x, theme=t),
                            width="stretch", theme=None)
        except ValueError as exc:
            st.caption(str(exc))
    with tab_r:
        if not r["specs"]:
            st.caption("The file has no analyses.")
        for name, atype, args in r["specs"]:
            out = r["analyses"].get(name)
            st.markdown(f"**{name}** ({atype})")
            if atype == "iv" and out is not None:
                ylab = "I [A/cm]"
                xlab = f"V({args.get('anode_contact', '')}) [V]"
                lin, log = figs.iv_figures(out[0], out[1], theme=t,
                                           x_label=xlab, y_label=ylab)
                c1, c2 = st.columns(2)
                c1.plotly_chart(lin, width="stretch", theme=None)
                c2.plotly_chart(log, width="stretch", theme=None)
            elif atype == "cv" and out is not None:
                lin, _ = figs.iv_figures(out[0], out[1], theme=t,
                                         x_label="V [V]", y_label="C [F/cm²]")
                st.plotly_chart(lin, width="stretch", theme=None)
            else:
                st.json(json.loads(json.dumps(out, default=lambda v: [v.real, v.imag]
                                              if isinstance(v, complex) else str(v))),
                        expanded=False)
