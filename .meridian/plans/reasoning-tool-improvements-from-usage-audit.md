# Plan — aismartbuddy reasoning-tool improvements, driven by real clear-thought/sequential-thinking usage

## Verbatim Requirements

### Original Request
> analyze your full claude code history on sequential thinking tool and clear-thought tool use in C:\Users\michiele\.claude\  and validate that against this MCP server. Find any improvements where this MCP server can improve

### Follow-up from user (injected mid-run)
> include also this information in this plan: Batch nodes - not available yet based on what I see (still one call per node)
> think_summarize - still returns minimal info, but now shows diagrams - slight improvement

---

## Context

aismartbuddy is the user's own MCP server providing ~50 tools, of which ~30 are reasoning tools (`think_*`, `holon_*`, `score_*`, `iterate`, `brainstorm`, `refs`). It is positioned as a richer superset of the public **clear-thought** + **sequential-thinking** MCP servers. We want to validate that positioning against **actual usage data** from the user's `C:\Users\michiele\.claude\` conversation logs — not assumptions — and surface improvements where aismartbuddy either (a) solves a real user need worse than clear-thought does, or (b) ships capability the user never reaches.

**Why now:** the aismartbuddy working tree has a ~2,700-line in-flight rewrite of thinking_engine/think.py/graph.py. Shaping that rewrite with evidence — what the user actually calls, with what shape of arguments, in what sequence — costs less than fixing it after ship.

**Intended outcome:** a prioritised, scoped list of concrete changes to the reasoning-tool surface, grounded in file:line citations on both sides (history + code).

---

## Current State — what the usage data says

Source: audit of 1,670 JSONL transcript files under `C:\Users\michiele\.claude\projects\`. Window: 2026-03-29 → 2026-04-12. Total reasoning-tool invocations found: **837**.

| Tool                     | Count | % of total | Notes                                       |
| ------------------------ | ----- | ---------- | ------------------------------------------- |
| `sequentialthinking`     | 758   | 90.6 %     | Overwhelmingly the default reasoning tool   |
| `structuredargumentation`| 23    | 2.7 %      | Concentrated in TP-IPM                      |
| `scientificmethod`       | 20    | 2.4 %      | Concentrated in ODI                         |
| `decisionframework`      | 18    | 2.2 %      | Spread across projects                      |
| `mentalmodel`            | 11    | 1.3 %      | **Only `first_principles` ever used**       |
| `metacognitivemonitoring`| 4     | 0.5 %      | Rare                                        |
| `collaborativereasoning` | 2     | 0.2 %      | Near-zero                                   |
| `visualreasoning`        | 1     | 0.1 %      | Near-zero                                   |
| `debuggingapproach`      | 0     | 0 %        | **Never used — zero invocations**           |

**Shape of the 758 sequentialthinking calls:**

- Average `thought` length: ~9,000–9,500 characters (near the hard ceiling).
- `totalThoughts` is pre-declared, usually 3 or 8, and rarely changed mid-chain.
- `isRevision`, `revisesThought`, `branchId`, `branchFromThought`, `needsMoreThoughts`: **0 uses across the full corpus.** The branching infrastructure exists in the tool schema and is never engaged.
- Chains are strictly linear; no back-references between chains.
- Typical task: architectural analysis, storage-backend decisions, pipeline design, concurrency review — not debugging, not ideation.

**Composition patterns:** tools are invoked independently. No observed case of tool A's output being fed as structured input to tool B. `think_refs_query`-style cross-record composition would have no analogue in the history even if clear-thought offered it.

---

## Current State — what aismartbuddy actually offers

aismartbuddy ships near-one-to-one equivalents for every clear-thought tool the user actually uses, plus extensive additions (holons, evidence provenance, constraints, topologies, interference protocol, rubric-based scoring). Parallel map:

| clear-thought            | aismartbuddy                         | Status                                              |
| ------------------------ | ------------------------------------ | --------------------------------------------------- |
| `sequentialthinking`     | `think_graph`                        | Superset (branch/revise/synthesize + batch)         |
| `mentalmodel`            | `think_model` (13 models in CLAUDE.md; **16 in code** — `kuba`, `systems_dynamics`, `inversion` undocumented) | Superset |
| `debuggingapproach`      | `think_debug` (6 approaches)         | Parity                                              |
| `decisionframework`      | `think_decide` (5 analysis types)    | Superset (staged workflow + items[])                |
| `scientificmethod`       | `think_science` (7 stages)           | Parity                                              |
| `structuredargumentation`| `think_argue` (5 types, chain mode)  | Parity                                              |
| `metacognitivemonitoring`| `think_monitor`                      | Parity                                              |
| `collaborativereasoning` | ❌ removed                           | Intentional                                         |
| `visualreasoning`        | ❌ removed                           | Intentional; `think_summarize` now includes diagrams|

The batch/forcing-function pattern (`items=[...]` with fail-fast validation + `auto_graph=True` materialising KnowledgeNode+DerivedFrom edges) is the single biggest value-add over clear-thought.

---

## User's in-flight observations (from the follow-up message)

**1. "Batch nodes — not available yet based on what I see (still one call per node)."**

This is perception, not fact. `think_graph` DOES accept a `thoughts[]` batch parameter (`think.py:700`, implementation `think.py:823–890`). Each item supports `parent_ref` as either an integer index into the same batch OR an existing node id, which covers linear chains, hierarchical trees, and mixed shapes.

The feature is invisible because the docstring teaches against it. The first example block (`think.py:729–739`) shows "For simple sequential thinking" and "For hierarchical decomposition" as three-and-four **separate calls**. The `thoughts:` parameter is documented on line 775 — after `children:`, after the `Actions:` block, and after the example code the agent has already learned from. Agents do what the example shows.

**2. "think_summarize — still returns minimal info, but now shows diagrams — slight improvement."**

Confirmed from `thinking_engine.py:2273` (`get_summary`). The output is terse one-liners per tree (`- Tree {tid}: "preview" — N nodes, depth D`) plus a recent diagrams addition. For a user running 8-thought chains at ~9 KB per thought, that summary collapses the actual reasoning content too aggressively to be useful for resuming or reviewing a session. It's a recall-oriented index, not a working summary.

---

## Gap Analysis — where aismartbuddy can improve

Ranked by how well each gap is supported by the usage data. High-signal gaps first.

### G1. `think_graph` batch mode is invisible — **highest priority**
- **Evidence:** user says "still one call per node"; history shows 100 % of sequentialthinking calls are single-call linear chains.
- **Root cause:** docstring examples (`think.py:729–739`) show single calls; `thoughts:` parameter is buried.
- **Why it matters:** this is the feature that would most improve the user's actual dominant workflow. The 758 sequentialthinking chains are exactly what `thoughts=[{thought, parent_ref: i-1}, ...]` was built for, and the agent never reaches for it.
- **Fix scope:** documentation + surfacing, not new code. Rewrite the `think_graph` docstring so the FIRST example is a `thoughts=[...]` linear chain. Keep single-call examples but demote them to "for incremental / mid-analysis use." Add a `prefer_batch` hint in the tool description. Consider a thin alias tool `think_chain(thoughts=[...])` that wraps `think_graph(thoughts=...)` with a narrower signature — discoverability through a second named entry point.

### G2. `think_summarize` is under-built for 8-thought × 9 KB sessions — **high priority**
- **Evidence:** direct user feedback; `get_summary` inspection.
- **Why it matters:** if the user's primary chain shape is ~72 KB of analysis, a summary that returns ~500 characters isn't reducing; it's hiding.
- **Fix scope:**
  - Add a `detail_level` parameter to `think_summarize` (tool wrapper) and to `get_summary` (engine side): `"index"` (current behaviour), `"synopsis"` (per-tree extractive summary from synthesize nodes + leaves, ~400-char cap per node), `"full"` (tree outline with preserved node content capped per-node).
  - **Default remains `"index"`** — preserves backward compatibility for agents already parsing the terse format. `"synopsis"` is the recommended value and documented as such. Agents migrate opt-in.
  - **Engine threading of the parameter:** `get_summary(max_items_per_category, detail_level)` switches the `_preview` char limit (60 → 400) and the number of branches shown per tree. Section structure (thought graphs / models / decisions / etc.) stays intact; only per-item verbosity changes.
  - When synthesis nodes exist, promote them — they are the user's own distilled output and the best summary material already in the graph.
  - Include the Mermaid-diagram-era additions but also add a simple ASCII tree fallback for hosts that don't render Mermaid inline.

### G3. Long single thoughts are pathological — **high priority, cheap**
- **Evidence:** ~9,000 character average per `thought`. The CLAUDE.md and `think_graph` docstring both explicitly warn against this ("If a thought is becoming an essay, use action='branch'"), and the agent ignores the warning.
- **Why it matters:** long thoughts defeat the whole point of a thought graph — nothing is queryable, refs can't target sub-claims, synthesis is impossible.
- **Fix scope:** server-side soft warning. When a single `thought` or any `thoughts[].thought` exceeds a threshold (suggest 1,500 chars), prepend a one-line advisory to the returned text: `Note: thought N is 9,200 chars — consider action='branch' with children=[...] to keep nodes queryable.` Do NOT reject — the agent's judgment sometimes requires a long node, and hard rejection would break existing clients. Soft signal is enough to shift behaviour over time.

### G4. Mental-model catalogue is documented and undiscovered — **medium priority**
- **Evidence:** only `first_principles` used across 11 mentalmodel calls. 12+ other models sit idle. CLAUDE.md claims 13 models; code actually defines 16. **Correction from plan review:** the `think_model` docstring at `think.py:1383-1399` ALREADY documents all 16 models with one-line descriptions. The gap is in CLAUDE.md only.
- **Why it matters:** the richest part of `think_model` — the shape of the model forces different reasoning — isn't happening. The agent defaults to the first item in the enum.
- **Fix scope:**
  - Update CLAUDE.md to document all 16 models (the docstring already does this; sync CLAUDE.md to match).
  - Optionally add a compact "when to pick which model" selection table to the `think_model` docstring — one row per model, trigger + ideal phase. Supplemental to the existing descriptions, not a rewrite.
  - Optionally: a `think_model(action="suggest", problem="...")` entry that returns the 2–3 best-fit model names given the problem shape. Low priority; only if the docstring table proves insufficient.

### G5. `think_debug` has zero uptake — **medium priority, investigate first**
- **Evidence:** 0 calls to clear-thought `debuggingapproach`, and (to confirm) we should check how often `think_debug` is called in aismartbuddy-local sessions. If it's also near-zero, this is a real discoverability gap, not a tool-quality gap.
- **Why it matters:** debugging is a large share of software work. If a dev-focused user does 0 debugging-tool calls, either the tool is invisible or its framing doesn't match how debugging actually unfolds (which tends to be hypothesis-driven, not method-driven — so `think_hypothesis` + `think_evidence` might be the natural fit instead).
- **Fix scope:** investigate before acting. Read the `think_debug` docstring with fresh eyes, compare with `think_hypothesis`. If the 6 named "approaches" feel academic, consider either (a) renaming to verbs actually used in bug triage ("isolate", "bisect", "retrace", "invert"), or (b) explicitly directing users toward `think_hypothesis` for debugging, and narrowing `think_debug` to structured post-mortem write-up.

### G6. Cross-tool composition is unexercised — **low priority, don't over-engineer**
- **Evidence:** zero observed cases of one tool's output feeding another's input, across the full history.
- **Why it matters:** the `refs[]` + `think_refs_query` + `think_bridge` + `auto_graph` infrastructure is sophisticated and the data shows the user (and Claude-on-behalf-of-the-user) never composes. Either the composition model is correct but invisible, or it's correct but unnecessary for the dominant workload.
- **Fix scope:** resist the urge to build more composition machinery. Instead:
  - When an `items[]` call completes, include in the return text one concrete compose-next suggestion based on what just ran (e.g. `Next: score_evaluate(analysis_refs=["m_id1","m_id2"]) to grade these models against a rubric.`).
  - Do one pattern per tool, chosen empirically (think_model → score_evaluate; think_science → think_evidence; think_graph synthesize → think_monitor). Small nudges > new subsystems.
- **Non-goal:** do not build a "workflow" or "pipeline" tool. CLAUDE.md explicitly lists `workflow` as removed — honor that.

### G7. Branching / revision UI is documented but unused — **low priority, status quo OK**
- **Evidence:** 0 uses of `isRevision` / `branchId` in the full corpus. `think_graph` exposes the same capability via `action="revise"` and `action="branch"`.
- **Why it matters:** probably doesn't. If users never revise in clear-thought either, aismartbuddy shouldn't spend budget trying to make revision happen. Log the finding; no change.

---

## Proposed Changes — concrete and scoped

Ordered by ROI. Each item names the file it lives in and what it looks like when done.

1. **Rewrite `think_graph` docstring to lead with `thoughts=[...]` (`src/aismartbuddy/tools/think.py:707–790`).** New first example is a 4-step linear chain built in one call with `parent_ref` indices. Single-call examples remain but marked "for incremental use." Adds a one-line `PREFERRED: batch via thoughts=[...] for new chains` near the top.

2. **Add thought-length soft warning (`src/aismartbuddy/tools/think.py`, three code paths in `think_graph`).** Threshold: 1,500 chars. Applies to:
   - the single-node path (`thought` arg),
   - the `thoughts[]` batch loop (around `think.py:829`),
   - the `children[]` batch path — even though children are meant to be short decomposition units, a long child is the exact anti-pattern the warning addresses.
   Output: prepend advisory line to the returned status string. Zero behavioural change beyond the text of the return.

3. **`think_summarize` detail levels (`src/aismartbuddy/tools/think.py:3438`, engine side `src/aismartbuddy/engines/thinking_engine.py:2273 get_summary`).** Add `detail_level` parameter, default `"synopsis"`. Implement synopsis by prioritising synthesize nodes + leaf nodes in the tree output, with a ~400-char cap per node content rather than the current 60-char preview. Keep `"index"` as the opt-in terse mode for dashboards.

4. **CLAUDE.md + `think_model` docstring — document all 16 models (`CLAUDE.md`, think-tools section; `src/aismartbuddy/tools/think.py:1346 think_model`).** Add one-line descriptions for `kuba`, `systems_dynamics`, `inversion`. Add a compact "model → when to use" table.

5. **Compose-next hints on `items[]` / chain completion (additions in `think_model`, `think_science`, `think_monitor`, `think_decide`, `think_argue` chain mode, plus `think_graph` synthesize action).** Each returns one line: `Suggested next: <tool_name>(<key_arg>=[<ids>])`. No coupling, no new state — just a string append. Suggested pairings: think_model → score_evaluate; think_science → think_evidence; think_monitor → think_validate; think_decide → score_evaluate; think_argue → think_monitor; think_graph synthesize → think_monitor.

6. **Investigate `think_debug`.** Phase-1 task: grep aismartbuddy-local project transcripts for `think_debug` invocation count. If <5 in the same window, treat as confirmed discoverability failure and follow up with a docstring rewrite that reframes approaches as verbs, or narrow the tool scope. If >20, drop this item.

---

## Non-Goals

- **Not** adding back `think_collaborate`, `think_visualize`, `workflow`, `bridge`, or `session_export`. All were removed intentionally per CLAUDE.md.
- **Not** building a pipeline/workflow tool to compose reasoning tools. Usage data does not support it.
- **Not** touching SQL / graph / YouTube tool surfaces. Out of scope.
- **Not** changing the `items[]` forcing-function pattern — it's the biggest validated win aismartbuddy has over clear-thought.
- **Not** hard-enforcing thought-length limits. Soft warning only.

---

## Verification

Each change has a cheap, local check:

1. **Docstring change (G1):** launch aismartbuddy over stdio, call `think_graph` with no args, read the tool description that MCP exposes back. The first example should be a `thoughts=[...]` chain.
2. **Soft warning (G3):** `uv run pytest -k think_graph` plus a new test `tests/test_think_extensions.py::test_long_thought_triggers_warning` that submits a 3,000-char thought and asserts the returned string contains `"consider action='branch'"`.
3. **`think_summarize` detail levels (G2):** existing tests in `tests/test_think_extensions.py` extended with a parametrized case over `detail_level ∈ {"index","synopsis","full"}`. Assert synopsis length > index length for a fixed fixture.
4. **CLAUDE.md model list (G4):** grep `CLAUDE.md` for all 16 model names. `rtk grep -n 'kuba\|systems_dynamics\|inversion' CLAUDE.md` should return three hits.
5. **Compose-next hints (G5):** extend `tests/test_score_tools.py` and `tests/test_think_extensions.py` with one assertion per tool checking the suggestion line is present on items[] completion.
6. **End-to-end:** `uv run pytest -v`, `uv run pyright`, `uv run ruff check src/ tests/`. Return-shape impact is bounded: `think_summarize`'s default stays `"index"` (no change); `think_graph` appends an advisory line when thoughts exceed 1,500 chars (additive, no schema change); items[] completions append a `Suggested next:` line (additive). No existing assertions on exact string content are expected to break, but regressions here would surface in the existing test suite.

---

## Critical Files

- `src/aismartbuddy/tools/think.py` (primary — think_graph, think_model, think_summarize docstrings + soft warning, compose-next hints)
- `src/aismartbuddy/engines/thinking_engine.py` (get_summary rework for detail levels)
- `CLAUDE.md` (mental-model catalogue; cross-refs)
- `tests/test_think_extensions.py` (new tests for warning + detail levels + compose hints)
- `tests/test_score_tools.py` (compose-next hint on score_evaluate)

---

## TLDR

The user's own history shows one dominant reality: `sequentialthinking` accounts for 91 % of all reasoning-tool calls, always in linear chains of ~9 KB single thoughts, with zero use of branching or revision features. aismartbuddy already has a superset of every clear-thought capability the user actually touches, but the batch mode that would collapse 8 round-trips into 1 is invisible because the `think_graph` docstring teaches single-call chaining, and `think_summarize` under-summarises ~72 KB sessions into ~500 chars. The plan is tight: rewrite the `think_graph` docstring to lead with `thoughts=[...]`, add a soft warning for essay-length thoughts, give `think_summarize` a synopsis mode that uses the synthesize nodes the user already wrote, and document the three undocumented mental models. Low code churn, high leverage — the improvements shift the defaults toward capabilities that already exist.
