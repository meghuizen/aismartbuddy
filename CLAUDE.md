# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

AISmartBuddy is a Python MCP server providing AI assistants with temporary SQL (DuckDB) and graph (LadybugDB/Cypher) database sessions. Output is token-optimized (CSV for bulk data). Designed as a foundation for additional AI-extending tools.

## Tech Stack

- **Language:** Python 3.12+
- **MCP SDK:** `mcp` (FastMCP) — official Python SDK
- **SQL Engine:** DuckDB via `duckdb` package
- **Graph Engine:** LadybugDB via `real-ladybug` package
- **Data Pipeline:** Arrow (`pyarrow`) → Polars (`polars`) for query results. 10-100x faster than csv.writer.
- **Transport:** stdio (default), SSE for remote
- **Package manager:** `uv` (preferred)
- **Build backend:** hatchling

## Build & Run Commands

```bash
uv sync                                  # Install dependencies
uv run python -m aismartbuddy            # Run server (stdio)
uv run python -m aismartbuddy --transport sse --port 8000  # Run server (SSE)
uv run pytest -v                         # Run all tests
uv run pytest tests/test_sql_tools.py::test_name -v  # Single test
uv run pyright                           # Type check
uv run ruff check src/ tests/            # Lint
uv run ruff format src/ tests/           # Format
```

## Architecture

```
__main__.py (Click CLI) → server.py (FastMCP + lifespan + optional Entra auth)
  ├── identity.py (resolve_identity from ctx/params/env)
  ├── auth.py (optional EntraTokenVerifier — activated via env vars)
  ├── youtube_client.py (shared YoutubeDL + http session)
  ├── tools/sql.py        → engines/duckdb_engine.py    ─┐
  ├── tools/graph.py      → engines/ladybug_engine.py    ├── session.py (SessionManager)
  ├── tools/think.py      → engines/thinking_engine.py   │
  ├── tools/holon.py      → engines/thinking_engine.py   │
  ├── tools/score.py      → engines/thinking_engine.py   │
  ├── tools/iterate.py    → engines/thinking_engine.py   │   (ITERATE mode)
  ├── tools/brainstorm.py → engines/thinking_engine.py   │   (DIVERGE mode)
  ├── tools/refs.py       → engines/thinking_engine.py   │   (cross-record query)
  ├── tools/infra.py      → session.py (parent-session facade for unified backends)
  ├── tools/youtube.py    → youtube_client.py + lxml XML cache
  ├── tools/meta.py       → suggest_database
  └── tools/__init__.py   → validate_items, materialize_auto_graph (shared helpers)
      formatting.py (Arrow/Polars CSV + legacy csv.writer) ─┘
```

- **server.py** — FastMCP instance with ~55 tools, 5 prompts, 2 resources. Lifespan manages SessionManager + YouTubeClient init/cleanup.
- **identity.py** — Multi-tenant identity resolution. `resolve_identity(ctx, user_id, project_id)` returns validated `(user_id, project_id)` tuple using priority: ctx.client_id (Bearer auth) → tool parameter → RuntimeConfig default → literal "default". Path-component validation prevents filesystem traversal.
- **youtube_client.py** — Shared `YouTubeClient` dataclass (requests.Session + YoutubeDL) plus `parse_video_id()` helper that accepts raw 11-char IDs, `watch?v=`, `youtu.be/`, `embed/`, and `shorts/` URLs. Module-level singleton initialized in `app_lifespan` (best-effort — failure does not block server startup; the tool checks for `None` at call time). YoutubeDL uses a no-op logger (to bypass `no_warnings` being overridden by custom loggers) and skips dash/hls format manifests for 2-3× faster metadata-only extraction.
- **session.py** — Thread-safe SessionManager singleton (uses `threading.Lock`). Maps session_id → engine. Supports "sql", "graph", and "think" session types. Auto-cleans expired sessions and stale pagination cursors.
- **tools/** — Async tool functions. Access SessionManager via `tools.get_session_manager()`. Wrap blocking engine calls with `anyio.to_thread.run_sync()`.
- **engines/** — `BaseEngine` ABC with shared temp file handling, Arrow query path (`execute_arrow`), and cursor-based pagination (`execute_paged`, `fetch_next_page`). DuckDB and LadybugDB subclasses use `_require_conn()`. ThinkingEngine is in-memory (does not extend BaseEngine).
- **formatting.py** — Token-optimized output. Primary path: Arrow Table → Polars DataFrame → `write_csv()`. Legacy path: tuple-based csv.writer (fallback for thinking tools). CSV default for SQL/graph (2-3x fewer tokens than JSON).

### Key patterns

- Tools are named `sql_*`, `graph_*`, `think_*`, `holon_*`, `score_*`, plus a few standalone (`suggest_database`, `get_youtube_information`, `iterate`, `brainstorm`, `session_create`/`destroy`, `knowledge_batch`, `data_profile`/`anomalies`, `rubric_templates`, `think_refs_query`). ~55 tools total.

### SCAFFOLD → ELABORATE → ASSESS framework

A tool's value depends on **schema-structure × sequence-position**:

- **SCAFFOLD** — call FIRST (reasoning not yet done). Schema FORCES structure. Tools: `think_model`, `think_science`, `think_decide`, `think_interfere`. Use the strict `items=[...]` form for a forcing function: each item must include id + per-tool required fields, server REJECTS lazy items.
- **ELABORATE** — call MIDDLE. Flexible thinking, branching, navigation. Tools: `think_graph` (with `children=[...]`), `holon_*`, `think_argue` (with `chain=[...]`), `think_debug`, `brainstorm`, `iterate`, `think_refs_query`.
- **ASSESS** — call LAST. Forcing function for honest self-critique. Tools: `score_rubric`, `score_evaluate` (+ `finding_batch`), `think_monitor` (with `items=[...]` for self-assessment, or `action="density"` for session load stats).

### The items[] forcing-function pattern

For SCAFFOLD/ASSESS family, calling with `items=[{id, ...required_fields}, ...]` is the highest-quality form:

- One round-trip → N validated outputs.
- Each item passes the SAME per-item schema (e.g., `think_model` items require id/problem/steps/reasoning/conclusion).
- Server REJECTS the whole batch on the first violation (fail-fast, no partial state) with the failing item index + missing field name.
- Each item gets an addressable id you can later reference via `connects_to:` in another item or via `refs:` in any record. `think_refs_query(entity_id)` finds all records that reference an id.
- The single-item form (no items[]) is preserved for backward-compat / mid-analysis use, but the description explicitly notes that's log-style ceremony — prefer items[] at analysis START.

### Auto-graph pipeline (items[] + auto_graph=True)

When a SCAFFOLD/ASSESS items[] call sets `auto_graph=True` AND the session has a graph backend (created via `session_create(backends=["think","graph"])`), the server materialises each item as a `KnowledgeNode` row in the graph backend. Each `connects_to: ["other_id"]` becomes a `DerivedFrom` edge. One round trip = N structured records + N KG nodes + all declared edges. Eliminates the manual KG construction phase. **Auto-materialised nodes carry `authority="inferred"` automatically** — distinguishable from user-supplied ground-truth nodes.

**auto_graph-capable batch tools and their edge labels:**

- `think_model(items=[...], auto_graph=True)` — `connects_to` → `DerivedFrom` edge
- `think_science(items=[...], auto_graph=True)` — `connects_to` → `DerivedFrom` edge
- `think_monitor(items=[...], auto_graph=True)` — `connects_to` → `DerivedFrom` edge
- `think_graph(thoughts=[...], auto_graph=True)` — `parent_ref` → `BranchOf` edge
- `think_decide(items=[...], auto_graph=True)` — `connects_to` → `DerivedFrom` edge
- `think_argue(chain=[...], auto_graph=True)` — `responds_to_index` → `RespondsTo` edge
- `think_validate(items=[...], auto_graph=True)` — `subject_id` → `Validates` edge. **Caveat**: the subject must already be a KnowledgeNode — chain auto_graph from your scaffold/decision tools earlier in the session, or expect the edge to be skipped.
- `holon_create(holons=[...], auto_graph=True)` — `parent_ref` → `PartOf` edge. `parent_ref` may be a batch ref-string (resolved against the just-created holons) OR an existing holon id (passes through unchanged).

### Single-record-action tools with items[] retrofit

The 4 single-record-action tools (`think_hypothesis`, `think_constraint`, `think_evidence`, `think_topology`) now accept `items=[...]` (or `*_ids=[...]` for invalidate/remove actions) on their existing actions — no new action names. Single-record args remain supported for backward-compat. Passing BOTH `items=[...]` AND single-record args in the same call raises a mutual-exclusion `ValueError`. PREFER items[] even for N=1 — it scales without added round-trips.

### score_evaluate auto_finalize

`score_evaluate(action="batch_findings", auto_finalize=True, summary=..., dimensions_reviewed=...)` collapses the 3-call `start_with_rubric → batch_findings → finalize` sequence into a single round-trip. Requires `summary` to be non-empty when `auto_finalize=True`.

### Legacy tools (registered but superseded)

`scaffold`, `hypothesize`, `self_assess` are still registered but are thin wrappers around `think_model`/`think_science`/`think_monitor`. Prefer the items[] forms of those tools — they are richer and more efficient.

### Removed tools (not registered)

`think_collaborate`, `think_visualize`, `think_graph_validate`, `workflow`, `bridge`, `session_export`, `session_snapshot` (ceremony / out-of-scope features).
- **`get_youtube_information(url_or_id, language="en", include_transcript=True, include_timestamps=True)`** — single-call tool returning title, description, available transcript languages, and the full timed transcript as Markdown. Accepts full URLs or raw 11-char video IDs. Results cached as lxml-built XML at `{OS_temp}/yt_{video_id}_{langcode}.xml` (OS handles cleanup). Cache version-stamped (`<video version="1">`); corrupt, vanished (TOCTOU), or older-version caches trigger silent refetch. `include_transcript=False` returns metadata only; `include_timestamps=False` strips `[MM:SS]` prefixes. Timestamps use `[MM:SS]` under 1 hour, `[H:MM:SS]` for longer videos.
- **YouTube graceful degradation**: when transcript fetch fails (transcripts disabled, language not available, video still processing, rate limit, network blip) the tool returns a degraded response — full metadata + a structured `## Transcript` block containing a stable category code (`TRANSCRIPTS_DISABLED`, `TRANSCRIPT_LANGUAGE_NOT_AVAILABLE`, `TRANSCRIPT_TEMPORARILY_UNAVAILABLE`, `TRANSCRIPT_RATE_LIMITED`, `TRANSCRIPT_NETWORK_ERROR`, `TRANSCRIPT_UNKNOWN_ERROR`), the upstream reason, and an actionable hint. Header reads `cache=miss-degraded`. **Caching policy: only fully successful fetches are persisted** — degraded responses are never cached, so a subsequent call always re-attempts. Only metadata-fetch failure (yt-dlp itself failing) is terminal and raises `ValueError`.
- **Annotation preset `_READONLY_OPEN`** (in `server.py`): for read-only tools that interact with EXTERNAL services (network calls). Sets `openWorldHint: True` per MCP spec so hosts know not to silently auto-approve. Used for `get_youtube_information`. The four presets are: `_DEFAULT` (closed-world, mutating), `_READONLY` (closed-world, idempotent), `_READONLY_OPEN` (open-world, idempotent — net calls), `_DESTRUCTIVE` (closed-world, destructive).
- `think_graph` is the primary ELABORATE tool — sequential chains, hierarchical decomposition (with `children=[...]` batch + optional `min_children`), revision, synthesis, delegation. Encourage SHORT thoughts (1-3 sentences) — branch instead of writing essays. Description says: "If a thought is becoming an essay, use action='branch' and split into children. Long stories collapse to noise."
- `think_model` is the primary SCAFFOLD tool. 16 models: first_principles, opportunity_cost, error_propagation, rubber_duck, pareto_principle, assumptions_xray, fishbone, value_of_info, swot, pre_mortem, design_review, complexity, root_cause, **kuba** (Know/Understand/Believe/Act progression — find the bottleneck stage), **systems_dynamics** (reinforcing/balancing loops, delays, leverage points), **inversion** (guaranteed-failure analysis first — work backward from disaster). Use pre_mortem before implementing, design_review before finalizing, root_cause for debugging, inversion when stuck in consensus thinking, systems_dynamics for feedback-heavy domains. **Strongly prefer the `items=[...]` form at analysis start** — it forces per-item structure (id/problem/steps/reasoning/conclusion) and unlocks `auto_graph`.
- All record types (ThoughtNode, HolonNode, EvaluationRecord) support `refs: list[str]`. The `think_refs_query(entity_id)` tool finds records that reference an id — use to compose across tool calls structurally rather than via text search.
- `holon_*` tools model domains holonically — entities that are simultaneously wholes and parts. Multi-membership: holons participate in multiple holarchies. Bridge finds paths between distant holons across holarchies. Propagation leaves structural traces (stale projections).
- Thinking tools (`think_*`) auto-create sessions on first call when `session_id` is omitted. Return compact text (not JSON) for token efficiency.
- SQL import supports 6 formats: csv, tsv, txt (custom delimiter), json, jsonl, parquet (base64). Plus batch import via `sql_import_batch`.
- Knowledge graph tools (`graph_knowledge_*`) layer semantic patterns: confidence scores, provenance, typed relations (supports/contradicts/etc.), inference (contradictions, gaps, chains, clusters). `graph_knowledge_add` and `knowledge_batch` accept `authority: "ground_truth" | "primary" | "inferred" | "external"` AND `domain: str` (free-form tag) on each node — omit either for `""` (unset). Use `think_bridge(action="authoritative_source", entity_name=...)` to rank nodes by authority, and `think_bridge(action="domain_context", domain=...)` to roll up everything tagged with a domain.
- `think_bridge` has **10 actions**: `thoughts_for_entity`, `entities_for_thought`, `hypotheses_for_entity`, `evidence_for_hypothesis`, `constraints_for_hypothesis`, `full_context`, `bundle`, `authoritative_source`, `domain_context(domain)`, `domain_connections(domain, domain_b)`. `thoughts_for_entity` falls back to substring search on ThoughtNode content (prefix `(text match) `) when no metadata.knowledge_refs match.
- **Domain grouping & entity registration on think records**: `think_graph(thoughts=[...])` items accept `entity_refs: list[str]` (merged into `metadata.knowledge_refs` so `thoughts_for_entity` finds them) and `domain: str` (written to `metadata.domain`). items[] forms of `think_model`, `think_decide`, `think_science`, `think_monitor` accept `domain: str` and write it to the record's `domain` field. When `auto_graph=True`, the materialised KnowledgeNode carries the item's `domain` automatically.
- **Data flow (SQL/graph):** `engine.execute_arrow(query)` → `pyarrow.Table` → `polars.from_arrow()` → `df.write_csv()` → str. Falls back to tuple-based `execute()` + `csv.writer` if Arrow unavailable.
- **Pagination:** `sql_query`/`graph_query` accept `offset`/`limit` (random access) and `paginate=True` (cursor-based). Cursor paging uses DuckDB's `to_arrow_reader()` for streaming without full materialization. Use `sql_query_next`/`graph_query_next` for subsequent pages.
- All database operations are blocking C calls wrapped in `anyio.to_thread.run_sync()` for async safety.
- Sessions use UUID-keyed temp directories cleaned up on destroy, timeout, or server shutdown. Orphaned dirs from failed `connect()` are auto-cleaned.
- SessionManager is thread-safe (`threading.Lock` guards all `_sessions` mutations). Periodic cleanup runs on worker thread (with error handling to prevent silent death).
- **Engine tuning:** DuckDB accepts `threads` and `memory_limit` config. LadybugDB accepts `buffer_pool_size` and `max_num_threads`. Configurable via CLI flags or `AISMARTBUDDY_*` environment variables.
- Config flows: CLI args (with envvar fallback) → `config.runtime_config` → server lifespan → SessionManager → engine constructors.

## Multi-Tenant Model

Sessions are bound to **(user_id, project_id)** at creation. This supports multiple users, multiple projects per user, and multiple sessions/agents per (user, project) — all isolated from each other on the backend:

- **Identity resolution** (in `identity.py`): `user_id` comes from `ctx.client_id` when MCP Bearer auth is configured (priority 1), otherwise from explicit tool parameter (priority 2), otherwise from `--default-user-id` / `AISMARTBUDDY_DEFAULT_USER_ID` config (priority 3), otherwise literal `"default"`. `project_id` follows the same fallback chain without the Bearer-token path.
- **Session ID entropy:** 128 bits (`uuid.uuid4().hex`, 32 hex chars) — session_id acts as a capability token. Possession equals authorization in the default case; under Bearer auth the ownership check also validates `session.user_id == ctx.client_id`.
- **Temp layout:** `{temp_dir}/aismartbuddy/{user_id}/{project_id}/{session_id}/` — disk hierarchy mirrors logical hierarchy.
- **Per-session lock:** each `SessionInfo` carries a `threading.Lock`. SQL/graph tools acquire it via `run_with_lock(info, fn)` (in `tools/__init__.py`) so two agents sharing a session serialize rather than corrupt engine state.
- **ThinkingEngine thread safety (three layered patterns):**
  1. **`@_synchronized` engine methods** — the default. Most mutations are single-step (`add_node`, `revise_node`, `upsert_*`, `add_*`, `join_holarchy`, `close`, `apply_finding`, `finalize_evaluation`). The decorator in `engines/thinking_engine.py` wraps them in `self._state_lock` (a `threading.RLock`). New tools should prefer this pattern.
  2. **`with engine.state_lock:` in tool code** — for multi-step read-modify-write on engine-owned records that can't be cleanly expressed as a single engine method. Current users: `think_graph_validate`, `think_graph_delegate`, `think_visualize`, `propagate_up`, `propagate_down` in `holon_analyze`. The RLock is reentrant so `@_synchronized` engine calls inside the block work.
  3. **Sync `_*_locked` helper called under `with engine.state_lock:`** — for tools with large/branching locked bodies that would otherwise require heavy indentation (`_holon_update_locked`, `_think_interfere_locked`). The async wrapper does session resolution + `with engine.state_lock:`, then delegates to a sync helper that runs the whole branch logic atomically.
- **Resource scoping:** `aismartbuddy://sessions/{user_id}/{project_id}` is the listing resource. The unscoped `aismartbuddy://sessions` returns a helpful error — no cross-tenant enumeration.
- **Error messages** are constant-text for "not found" vs "owned by someone else" to prevent presence-enumeration attacks.
- **Path-component validation:** `user_id` and `project_id` must match `^[A-Za-z0-9_.-]{1,64}$` — blocks `../`, `/`, null bytes, reserved names.

**Sharing:** multi-agent collaboration on one session works by sharing the `session_id` (out-of-band). All agents authenticating as the same user on the same project can access the session via just the session_id. No explicit "attach" step and no internal export/import tools — if agents need to copy content between sessions, they orchestrate it themselves via existing query/import tools.

## Authentication (optional)

Two paths are supported:

### 1. Microsoft Entra ID OAuth (built in)

`src/aismartbuddy/auth.py` ships a ready-to-use `EntraTokenVerifier` that validates Bearer tokens against an Entra tenant's JWKS. Activate by setting both env vars / CLI flags:

```bash
uv pip install aismartbuddy[entra]   # adds pyjwt[crypto] + httpx
export AISMARTBUDDY_ENTRA_TENANT="<tenant-guid>"
export AISMARTBUDDY_ENTRA_AUDIENCE="api://<app-id-uri>"
# Optional:
export AISMARTBUDDY_ENTRA_REQUIRED_SCOPE="mcp.invoke"
export AISMARTBUDDY_ENTRA_RESOURCE_SERVER_URL="https://your-host/"
uvx --from git+https://github.com/meghuizen/aismartbuddy aismartbuddy --transport sse
```

When activated, `server.py:_maybe_build_entra_auth` constructs the verifier + `AuthSettings` and passes them to `FastMCP(...)`. `ctx.client_id` in tool calls becomes the Entra `oid` claim — automatically picked up by `identity.py:resolve_identity` so every session is bound to the authenticated principal. Without these env vars, the server starts unauthenticated (current default behaviour).

If only one of the two required env vars is set, the server logs a warning and runs without auth (fail-open by design — partial config is treated as "not configured"). If `[entra]` extras aren't installed but the env vars are set, the server exits with a clear "install aismartbuddy[entra]" message (fail-closed for security).

### 2. Generic Bearer token (write your own verifier)

For non-Entra OAuth issuers, implement your own `TokenVerifier` subclass and pass it to `FastMCP(...)` like the Entra path does. The pattern in `auth.py` (JWKS fetch + cache + RS256 verify) is reusable.

```python
from mcp.server.auth.provider import TokenVerifier
from mcp.server.auth.settings import AuthSettings

class MyVerifier(TokenVerifier):
    async def verify_token(self, token: str):
        # Validate JWT, return AccessToken or None
        ...

```

`server.py:_maybe_build_entra_auth` shows the wiring pattern for any custom verifier (read RuntimeConfig, lazy-import the verifier class, return `(verifier, AuthSettings)` tuple). Replace `EntraTokenVerifier` with your own.

When configured, `ctx.client_id` becomes the authoritative `user_id` — tool-level `user_id` parameters are ignored to prevent claim spoofing. Without configuration, `user_id` is taken from the tool parameter or the configured default, which is appropriate for single-tenant stdio use.

## MCP Integration

```json
{
  "mcpServers": {
    "aismartbuddy": {
      "command": "uv",
      "args": ["run", "python", "-m", "aismartbuddy"]
    }
  }
}
```
