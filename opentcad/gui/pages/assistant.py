"""
OpenTCAD assistant — a conversation with a local open-weights model about
one simulation file. Describe a device or a change; the model drafts the
file, the checker repairs it with the model, and the reply lists what
changed, every value it assumed and its questions. Answer in the next
message; run results come back into the conversation too.

    streamlit run opentcad/gui/app.py     → "assistant" in the sidebar

The model is any OpenAI-compatible server (llama-server, Ollama, LM Studio,
vLLM). Without one, the page still loads, edits, checks and runs files.
"""
from __future__ import annotations

import copy
import hashlib
import json

import numpy as np
import streamlit as st
import yaml

from opentcad.assist import ChatClient, LLMError, draft_deck
from opentcad.assist.client import DEFAULT_URL
from opentcad.io.deck import (DeckError, _Loader, deck_from_dict, dumps_deck,
                              example_decks_dir, run_deck)
from opentcad.gui.sources_view import show_sources
from opentcad.viz import interactive as figs

st.set_page_config(page_title="OpenTCAD assistant", layout="wide")

EXAMPLES = example_decks_dir()
TEMPLATES = {"pn diode": "pn_diode.yaml", "NMOS (implanted)": "nmos_implanted.yaml"}

ss = st.session_state
ss.setdefault("deck_yaml", "")       # the file text (mirrors the editor)
ss.setdefault("editor", "")          # the editor widget's own state
ss.setdefault("draft", None)
ss.setdefault("chat", [])            # the conversation: {"role", "content"}
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


def draft_reply(d, before: dict | None) -> str:
    """The assistant's chat turn after a draft, built from what was checked
    (not from the model's prose), so it can be trusted as a summary."""
    lines = []
    if d.problems:
        lines.append(f"The file still has {len(d.problems)} problem(s) after "
                     f"{d.attempts} attempt(s):")
        lines += [f"- `{p}`: {m}" if p else f"- {m}" for p, m in d.problems[:6]]
    else:
        lines.append(f"Updated the file below; it checks clean ({d.attempts} attempt(s)).")
    if before is not None and d.deck is not None:
        a, b = dict(leaves(before)), dict(leaves(d.deck.to_dict()))
        changes = [(k, a.get(k), b.get(k)) for k in sorted(set(a) | set(b))
                   if a.get(k) != b.get(k)]
        if changes:
            lines.append("Changed:")
            lines += [f"- `{k}`: {old!r} → {new!r}" for k, old, new in changes[:8]]
            if len(changes) > 8:
                lines.append(f"- … and {len(changes) - 8} more (see Review)")
    if d.flags:
        lines.append(f"{len(d.flags)} value(s) weren't in your messages; they're "
                     "listed under Review. Check each, or tell me the right values.")
    if d.questions:
        lines.append("Questions for you:")
        lines += [f"{i}. {q}" for i, q in enumerate(d.questions, 1)]
    if not d.problems and not d.questions:
        lines.append("Run it, or tell me what to change.")
    return "\n".join(lines)


def run_reply(analyses: dict, specs, prov: dict | None = None) -> str:
    """The assistant's chat turn after a run: what came out, in numbers, and
    how many of the values it used have a recorded source."""
    lines = ["Ran the file:"]
    for name, atype, args in specs:
        out = analyses.get(name)
        if atype in ("iv", "cv") and out is not None and len(out[0]):
            x, y = np.asarray(out[0], float), np.abs(np.asarray(out[1], float))
            unit = "A/cm" if atype == "iv" else "F/cm"
            lines.append(f"- {name} ({atype}): {len(x)} points from {x[0]:g} to {x[-1]:g} V; "
                         f"|{'I' if atype == 'iv' else 'C'}| at the end {y[-1]:.3g} {unit}, "
                         f"largest {y.max():.3g} {unit}")
        else:
            lines.append(f"- {name} ({atype}): done")
    if prov:
        gaps, own = prov.get("without_source", 0), prov.get("opentcad_defaults", 0)
        lines.append(f"- It used {len(prov.get('values', []))} values from data files "
                     f"and code, citing {len(prov.get('sources', {}))} sources"
                     + (f"; {gaps} have no recorded source" if gaps else "")
                     + (f"; {own} are OpenTCAD's own values, not from a publication"
                        if own else "")
                     + ". The Sources tab lists each one.")
    lines.append("Tell me what to change, e.g. a higher current or another sweep range.")
    return "\n".join(lines)


# =============================================================================
# 1. Conversation
# =============================================================================
left, right = st.columns([2, 1])
with right:
    if ss.chat:
        start = "the file below"
        st.caption("The conversation edits the file below. Start a new one to "
                   "pick a template.")
        if st.button("New conversation"):
            ss.chat, ss.draft = [], None
            st.rerun()
    else:
        start = st.radio("Start from", ["the file below", *TEMPLATES, "nothing"],
                         help="The model edits this file; 'nothing' asks it to "
                              "write one from scratch.")
with left:
    for turn in ss.chat:
        with st.chat_message(turn["role"]):
            st.markdown(turn["content"])
    request = st.chat_input("Describe the device or the change, or answer the "
                            "model's questions")

if request:
    current = None
    if start in TEMPLATES:
        current = deck_from_dict(yaml.load((EXAMPLES / TEMPLATES[start]).read_text(),
                                           Loader=_Loader)).to_dict()
    elif start == "the file below" and ss.deck_yaml.strip():
        deck, probs = parse_yaml(ss.deck_yaml)
        current = deck.to_dict() if deck else None
    client = ChatClient(base_url=url, model=model, api_key=None)
    history = list(ss.chat)
    ss.chat.append({"role": "user", "content": request})
    with st.spinner("The model is drafting (checked and repaired automatically)…"):
        try:
            d = draft_deck(request, client=client, current=current, history=history)
        except LLMError as exc:
            ss.chat.append({"role": "assistant", "content": f"I couldn't reach the model: {exc}"})
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
        ss.chat.append({"role": "assistant", "content": draft_reply(d, current)})
    st.rerun()

# =============================================================================
# 2. Review what the model did
# =============================================================================
dr = ss.draft
if dr:
    st.subheader("Review")
    if dr["problems"]:
        st.error(f"The draft still has {len(dr['problems'])} problem(s) after "
                 f"{dr['attempts']} attempt(s). Fix them in the file below, or "
                 "describe the fix in the conversation:\n\n"
                 + "\n".join(f"- `{p}`: {m}" for p, m in dr["problems"]))
    else:
        st.success(f"Draft checks clean ({dr['attempts']} attempt(s)).")
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
        st.caption("Every value in the file came from your messages or the "
                   "file you started from.")
    if dr["before"] is not None:
        deck, _ = parse_yaml(ss.deck_yaml)
        if deck is not None:
            a, b = dict(leaves(dr["before"])), dict(leaves(deck.to_dict()))
            changes = [(k, a.get(k), b.get(k)) for k in sorted(set(a) | set(b))
                       if a.get(k) != b.get(k)]
            with st.expander(f"Changes from the starting file ({len(changes)})",
                             expanded=False):
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
                         "specs": [(a.name, a.type, a.args) for a in deck.analyses],
                         "provenance": res.provenance.to_dict()}
            ss.result_key = hashlib.sha1(ss.deck_yaml.encode()).hexdigest()
            ss.chat.append({"role": "assistant",
                            "content": run_reply(res.analyses, ss.result["specs"],
                                                 ss.result["provenance"])})
            ss.run_error = None
        except Exception as exc:
            ss.run_error = f"Run failed: {type(exc).__name__}: {exc}"
            ss.chat.append({"role": "assistant", "content":
                            f"The run failed: {type(exc).__name__}: {exc}\n"
                            "Tell me what to change, or fix the file below."})
    st.rerun()                       # show the run's reply in the conversation
if ss.get("run_error"):
    st.error(ss.run_error)

r = ss.result
if r:
    stale = ss.result_key != hashlib.sha1(ss.deck_yaml.encode()).hexdigest()
    if stale:
        st.caption("These results are from an earlier version of the file.")
    t = theme()
    mf = r["mf"]
    tab_s, tab_d, tab_r, tab_p = st.tabs(["Structure", "Doping", "Results", "Sources"])
    with tab_p:
        show_sources(r.get("provenance"), key="assistant_sources")
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
            elif atype == "fields" and out is not None:
                labels = {"Potential": "Potential ψ", "Electrons": "Electrons n",
                          "Holes": "Holes p", "ElectricField": "Electric field |E|"}
                q = st.radio("Quantity", list(labels), format_func=labels.get,
                             horizontal=True, key=f"field_{name}")
                st.plotly_chart(figs.field_map(out, q, theme=t), width="stretch",
                                theme=None)
            elif atype == "cv" and out is not None:
                lin, _ = figs.iv_figures(out[0], out[1], theme=t,
                                         x_label="V [V]", y_label="C [F/cm]")
                st.plotly_chart(lin, width="stretch", theme=None)
            else:
                st.json(json.loads(json.dumps(out, default=lambda v: [v.real, v.imag]
                                              if isinstance(v, complex) else str(v))),
                        expanded=False)
