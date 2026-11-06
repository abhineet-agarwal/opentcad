# The simulation assistant (local open-weights model)

Describe a device, or a change to one, in plain language. A model running
on your own machine drafts the [simulation file](simulation_files.md), and
OpenTCAD checks it. You then review every value the model chose, edit,
and run it. Nothing leaves your machine.

## Start a model server

Any server with the OpenAI-compatible chat API works. With llama.cpp
(`brew install llama.cpp`) and a GGUF model file:

```bash
llama-server -m ~/models/qwen2.5-3b-instruct-q4_k_m.gguf --port 8080 -c 16384 -ngl 99
```

With Ollama, set the URL to `http://127.0.0.1:11434/v1` and the model to
the name you pulled (e.g. `qwen2.5:7b`). LM Studio and vLLM work the same
way. Configure it in the GUI sidebar, or with environment variables:

```bash
export OPENTCAD_LLM_URL=http://127.0.0.1:8080/v1   # default (llama-server)
export OPENTCAD_LLM_MODEL=local                    # the name the server expects
export OPENTCAD_LLM_API_KEY=...                    # only if the server wants one
```

## Use it

```bash
streamlit run opentcad/gui/app.py      # then "assistant" in the sidebar
```

1. **Start from** a template (pn diode, implanted NMOS), the file in the
   editor, or nothing.
2. **Describe** the device or the change, e.g. *"Make the gate oxide 4 nm
   and sweep Vgs to 1.8 V"*.
3. **Review.**
   - The page lists every value in the file that wasn't in your request,
     with the model's reason where it gave one.
   - When you started from a file, it also lists every change from that
     file.
   - Questions the model asks are shown, as are any problems left after
     the automatic repair rounds.
4. **Edit** the YAML if needed. It's re-checked as you go, and you can
   download it or load your own.
5. **Run.** You get the structure, a net-doping map with the p-n junction,
   a doping profile at any x, and the analysis results. A `fields`
   analysis adds maps of the potential, electron and hole densities and
   |E| at its bias.

From Python:

```python
from opentcad.assist import ChatClient, draft_deck
draft = draft_deck("Make the gate oxide 4 nm", client=ChatClient(),
                   current=load_deck("examples/decks/nmos_implanted.yaml").to_dict())
draft.deck, draft.flags, draft.questions, draft.problems
```

## How a draft is kept honest

- **Constrained output.** The server is given a JSON Schema built from the
  same registries the checker uses: the fields, step names, materials,
  species, physics models and analysis arguments that exist. The model
  can't write a key OpenTCAD doesn't know. Plugin steps and models are
  included automatically. If a server doesn't support schemas, the client
  falls back to plain JSON mode.
- **Checked and repaired.** The draft goes through the same checker as
  `opentcad check`. Any problems are sent back to the model, for up to two
  repair rounds. Whatever remains is shown to you, never hidden.
- **Two independent sources of flags.** The model is told to list every
  value it chose, with a reason. Separately, every number in the file is
  compared with the numbers in your request after unit conversion (4 nm =
  0.004 µm, 50 mV = 0.05 V, 30 min = 1800 s). So is every physics or
  process-model name, against the words in your request. Anything not
  found is flagged, whether or not the model admitted to it. When editing,
  values unchanged from the starting file aren't flagged again.

## Which model

On an M4 with 16 GB, Qwen2.5-3B-Instruct (Q4_K_M, about 2 GB) does well at
**editing a template**:

| Request | Result | Time |
|---|---|---|
| "Make the gate oxide 4 nm and sweep Vgs to 1.8 V", from the NMOS template | Clean on attempt 2: the first left the S/D windows above the new stack top, the checker flagged it, and the model fixed it | 42–49 s |
| A pn diode written from scratch, with every value given | Clean on attempt 1 | 18 s |
| An NMOS from scratch | Failed after 3 attempts: no gate oxide, contacts on the wrong surface | 95 s |

Writing a whole MOSFET from scratch needs a larger model (7B or more,
e.g. Qwen2.5-7B-Instruct, about 5 GB at Q4). Or start from a template.
