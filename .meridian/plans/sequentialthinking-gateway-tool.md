# Plan: `sequentialthinking` gateway tool + mcp SDK floor bump

## Context

An AI assistant reflexively reaches for clear-thought's `sequentialthinking` over
aismartbuddy's `think_*` family. Root cause (confirmed against the code): FastMCP
exposes each tool's **docstring** as the MCP `description` the model reads at
selection time, and aismartbuddy's think docstrings are long, jargon-heavy, and
lead with `[SCAFFOLD] ... STRICT batch ... Server REJECTS lazy items`. clear-thought
offers one loose `thought` string that never rejects. The model recoils from the
forcing functions at selection time and never gets onto the quality path.

Fix: add a low-friction entry tool named to mirror the competitor's token, that
writes into `think_graph` underneath and **nudges toward the structured tools once
the model is already invested** (gateway, not pure mirror). This wins the first
call without sacrificing the forcing functions — they are deferred, not gated.

Bundled hygiene task: raise the stale `mcp>=1.9.4` floor.

## Task 1 — `sequentialthinking` tool (gateway)

**Name:** `sequentialthinking` (namespaced `mcp__aismartbuddy__sequentialthinking`).

**Where:** implement in `src/aismartbuddy/tools/think.py` alongside `think_graph`
(think.py:780), reusing its node-append / batch / revise path. Register in
`src/aismartbuddy/server.py` `_build_tool_specs()` (think-family block, ~server.py:333)
with the `_DEFAULT` annotation preset.

**Schema (loose — must NOT read like the [SCAFFOLD] docstrings):**
- `thought: str` — one thought (one move).
- `thoughts: list[str]` — optional batch; **each entry = one separate node**.
- `thought` XOR `thoughts` — mutual exclusion (raise `ValueError` if both/neither),
  matching the existing items[] convention.
- `next_thought_needed: bool`
- `thought_number: int | None`, `total_thoughts: int | None` — auto-tracked from
  session node count if omitted.
- `is_revision: bool`, `revises_thought: int | None` — map to think_graph revise.
- `session_id: str | None` — omit → auto-create unified think+graph session
  (reuse existing auto-create helper used by think_graph), so structure/auto_graph
  is available later.

**Behavior:** delegates to the existing `think_graph` implementation —
single `thought` → one node appended to the sequential chain; `thoughts=[...]` →
N separate sequential nodes (one per entry, NOT one blob); revision → think_graph
revise action. No new engine methods.

**Docstring (the deliberate inversion):** short, imperative, frictionless. No
`[SCAFFOLD]`, no `STRICT`, no `REJECTS`. e.g.:
> "Think step by step. One thought at a time, or pass thoughts=[...] to log
> several at once (each is a separate node). No setup, no required structure —
> a session is created automatically."

**Gateway nudge (option B):** append a non-blocking tip to the compact return text:
- once when the session crosses ~5 nodes, and
- whenever a call sets `next_thought_needed=false` (model is concluding):
> "N thoughts recorded. To harden this: `think_model` (scaffold the analysis)
> or `think_monitor` (assess confidence + limits)."

Reuse the existing compose-next-hint / `think_monitor(action="density")`
recommendation pattern. Track a per-session "nudged" flag to avoid repeating on
every call.

## Task 2 — bump `mcp` SDK floor (hygiene, not a CVE fix)

Honest framing: the project uses the official `mcp` SDK (`mcp.server.fastmcp`),
NOT standalone `fastmcp`. The headline CVEs (CVE-2026-27124/32871/32211, "fastmcp
3.2.0") are against the standalone package and do **not** apply. The one official
SDK advisory (CVE-2025-53366, DoS) affects `mcp < 1.9.4` and is already covered.
The bump's value is closing the stale floor so a fresh resolve can't pull a
vulnerable old version, plus two patch releases.

- `pyproject.toml:9`: `mcp>=1.9.4` → `mcp>=1.27.2` (latest, 2026-05-29).
- Refresh lock: `uv lock --upgrade-package mcp` then `uv sync`.

## Critical files

- `src/aismartbuddy/tools/think.py` — new tool fn (next to `think_graph`, ~line 780).
- `src/aismartbuddy/server.py` — register in `_build_tool_specs()` (~line 333).
- `tests/test_think_extensions.py` — new tests (patterns already there).
- `pyproject.toml` — floor bump.
- `CLAUDE.md` — document the new entry-point tool + gateway behavior.

## Verification

- `uv run pytest tests/test_think_extensions.py -v` — new tests:
  1. single `thought` → one node in session.
  2. `thoughts=[a,b,c]` → three separate nodes (not one).
  3. both `thought` and `thoughts` set → `ValueError`; neither → `ValueError`.
  4. `session_id` omitted → unified think+graph session auto-created.
  5. revision path maps to think_graph revise.
  6. gateway nudge text present after 5 nodes and when `next_thought_needed=false`;
     absent before threshold.
- `uv run pytest -v` — full suite green.
- `uv run pyright` and `uv run ruff check src/ tests/` — clean.
- Manual: call `mcp__aismartbuddy__sequentialthinking` with a single thought,
  confirm compact return; call again to cross threshold, confirm nudge appears;
  confirm `think_refs_query` / `think_graph` can see the created nodes.
- `uv sync` resolves `mcp` to >=1.27.2; full suite still green after bump.

## Docs

Update `CLAUDE.md`: add `sequentialthinking` to the tool list as the low-friction
ELABORATE entry point that delegates to `think_graph` and nudges toward
`think_model`/`think_monitor`. Note the gateway rationale (win the first call,
defer the forcing functions).
