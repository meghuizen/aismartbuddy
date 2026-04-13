# get_youtube_information MCP Tool

## Verbatim Requirements

### Original Request
> I want duckdb to be: 1.5.1 minimal, ladybugdb to be: 0.15.3, lxml 6.0.4, yt-dlp 2026.3.17, youtube_transcript_api 1.2.4.  I want 1 mcp tool called get_youtube_information which gets in 1 call: title, description, transcript languages available and the youtube transcript with times and all the pages if it's multiple pages. Default language is english. The mcp tool can request optional another language, optional request no transcript or transcript without timestamps (which just uses the python to not return the transcript or to remove the timestamps). The call to youtube video needs to cache its results in a temporary location (no cleanup needed, thats by the OS) which stores in yt_{videoid}_{langcode}.xml which uses lxml to store all the data, included the timed transcripts. If exists, the mcp tool will load the cache. Test videos to test: https://www.youtube.com/watch?v=iAA7PTqs4xY  and https://www.youtube.com/watch?v=LM7DByKOHBs  make the response, including the transcripts token efficient. use the mcp build skill in this. and think through it with clear-thought

### Clarifications
**Q:** What does "all the pages if it's multiple pages" mean?
**A:** Return all segments, no truncation (Recommended)

**Q:** How should the transcript/timestamp flags look on the tool signature?
**A:** Two booleans — `include_transcript: bool = True`, `include_timestamps: bool = True`

**Q:** Response format?
**A:** Markdown sections (scannable by AI, compact)

**Q:** Input format?
**A:** Accept either URL or video ID

**Q:** (follow-up) The tool description can recommend the AI agent to store the results in a file before processing.

### User-provided example code
The user shared `__init__.py` from a related YouTube MCP server (Junpei Kawamoto) showing concrete patterns for:
- `YoutubeDL(params={'quiet': True}, auto_init=False)` + `dlp.add_info_extractor(YoutubeIE())` (fast init, only YouTube extractor loaded)
- `dlp.extract_info(video_url, download=False)` returns dict with `title`, `description`, `uploader`, `upload_date`, `timestamp`, `duration`
- `YouTubeTranscriptApi(http_client=session, proxy_config=...)` shared via lifespan context
- `ytt_api.fetch(video_id, languages=[lang])` returns object with `.snippets` of `FetchedTranscriptSnippet(text, start, duration)`
- `ytt_api.list(video_id)` returns iterable of available transcripts (str() gives language info)
- `_parse_video_id(url)` handles `youtu.be/ID` and `watch?v=ID` URLs

This plan reuses those patterns directly (minus the `@lru_cache` memory cache — replaced with the disk XML cache the user requested).

---

## Context

The AISmartBuddy MCP server currently provides SQL/graph/thinking tools but has no way to ingest YouTube video content. Agents frequently need to analyze a video's transcript, description, or title — requiring them to fetch it themselves or ask the user to paste content.

This plan adds **one new MCP tool**, `get_youtube_information`, that fetches a YouTube video's title, description, available transcript languages, and full timed transcript in a single call. Responses are cached on disk as lxml-built XML under the OS temp directory (filename `yt_{videoid}_{langcode}.xml`) and reused across calls. The response is Markdown-formatted for token efficiency and AI readability, with flags to exclude the transcript entirely or drop timestamps. Dependencies are bumped to the versions the user specified.

---

## Current State

**Relevant existing patterns:**
- **Tool registration** (`src/aismartbuddy/server.py`): tools imported → appended to `_TOOLS: list[tuple]` → registered via `mcp.tool(name, annotations)` in a loop. Annotation presets `_DEFAULT`, `_READONLY`, `_DESTRUCTIVE`.
- **Async tool shape** (`src/aismartbuddy/tools/meta.py`): `async def tool_name(...) -> str:` with structured docstring (summary, description, `Example:`, `Args:`, `Returns:`). No `mcp.tool()` decorator — registration is centralized.
- **Lifespan management** (`src/aismartbuddy/server.py:app_lifespan`): async context manager that currently initializes `SessionManager` as a module-level singleton and yields without a value. Background cleanup task runs in an `anyio.create_task_group()`.
- **Blocking I/O wrapping**: all engines dispatch blocking calls via `await anyio.to_thread.run_sync(...)`.
- **Temp dir**: `Path(tempfile.gettempdir())` is the OS temp base. Sessions use a nested hierarchy under it; standalone tools should just use `tempfile.gettempdir()` directly per the user's spec (no subdirs).

**Dependencies (`pyproject.toml`)**: currently `duckdb>=1.2.0`, `real-ladybug>=0.14.0`, plus polars/pyarrow/tabulate/mcp/click/etc. `lxml`, `yt-dlp`, `youtube-transcript-api` are NOT declared.

**API docs researched for this plan**:
- `.meridian/api-docs/youtube-transcript-api.md` (in global `~/.meridian/api-docs/`) — v1.2.4 instance API, exception hierarchy, language fallback, thread-safety notes (NOT thread-safe — each thread needs its own instance)
- `.meridian/api-docs/yt-dlp.md` (in project) — metadata-only extraction, exception hierarchy, `sanitize_info`, cookie/auth situation in 2026, gotchas (logger bypasses `no_warnings`)
- `.meridian/api-docs/lxml.md` (in project) — building, serializing, parsing, CDATA handling, gotchas (`encoding='unicode'` + `xml_declaration=True` raises `ValueError`; CDATA is stripped on default parse)
- `.meridian/api-docs/duckdb-python.md` — already documents v1.5.1
- `.meridian/api-docs/ladybugdb.md` — already documents v0.15.2 (our target 0.15.3 is one patch newer; no API change)

---

## Data Flow

```
MCP call: get_youtube_information(url_or_id, language="en", include_transcript=True, include_timestamps=True)
  │
  ├─ parse url_or_id → video_id (11 chars)
  │
  ├─ cache_path = {temp_dir}/yt_{video_id}_{language}.xml
  │
  ├─ if cache_path exists AND parses successfully → load from XML
  │     └─ shape response per flags, return Markdown
  │
  └─ else:
        │
        ├─ YoutubeDL.extract_info(url, download=False) → title, description, uploader, duration
        │     (wrapped in anyio.to_thread.run_sync — blocking I/O)
        │
        ├─ YouTubeTranscriptApi.list(video_id) → TranscriptList for available languages
        │
        ├─ YouTubeTranscriptApi.fetch(video_id, languages=[language])
        │     → FetchedTranscript with .snippets (list of FetchedTranscriptSnippet)
        │     → on language failure: NoTranscriptFound / TranscriptsDisabled / VideoUnavailable
        │
        ├─ build XML tree with lxml.etree (title, description CDATA, languages, transcript segments)
        │
        ├─ write cache_path
        │
        └─ shape response per flags, return Markdown
```

---

## Changes

### 1. `pyproject.toml` — dependency bumps + new deps

Under `dependencies`:
- Change `duckdb>=1.2.0` → `duckdb>=1.5.1` (matches already-researched api-doc version)
- Change `real-ladybug>=0.14.0` → `real-ladybug>=0.15.3`
- Add `lxml>=6.0.4`
- Add `yt-dlp>=2026.3.17`
- Add `youtube-transcript-api>=1.2.4`

`uv sync` will pick up the changes during verification. No pyproject structural changes beyond the dependency list.

### 2. NEW `src/aismartbuddy/youtube_client.py` — shared client singleton

Module-level `YouTubeClient` dataclass (frozen) holding:
- `http_client: requests.Session` — shared connection pool
- `ytt_api: YouTubeTranscriptApi` — instance-based API (v1.x requires instantiation)
- `dlp: YoutubeDL` — configured with:
  - `quiet=True`, `skip_download=True` — no output, no download
  - A **no-op logger** (not just `no_warnings=True`) — per the researched gotcha, a custom `logger` bypasses `no_warnings`; to get true silence we pass `logger=_NoOpLogger()` whose `debug/info/warning/error` methods do nothing.
  - `extractor_args={'youtube': {'skip': ['dash', 'hls']}}` — skips format manifest resolution (2-3× faster for metadata-only — per the researched performance tip).
  - `auto_init=False` + manual `add_info_extractor(YoutubeIE())` — fast startup, only the YouTube extractor is loaded.

Module-level singleton: `youtube_client: YouTubeClient | None = None` — mirrors the `session_manager` pattern at `session.py:363`.

Initialized by `server.py:app_lifespan` on startup, closed on shutdown (`http_client.close()`, `dlp.close()`).

Helper `_parse_video_id(url_or_id: str) -> str` here:
- If input length is 11 and matches `^[A-Za-z0-9_-]{11}$` → return as-is.
- Else parse with `urllib.parse.urlparse`. Handle `youtu.be/VID`, `youtube.com/watch?v=VID`, `youtube.com/embed/VID`, `youtube.com/shorts/VID`. Raise `ValueError` with helpful message on failure.

### 3. NEW `src/aismartbuddy/tools/youtube.py` — the tool + XML cache

Contains:

- **`get_youtube_information(url_or_id, language="en", include_transcript=True, include_timestamps=True, ctx=None)` async tool** — the registered MCP tool. Returns `str`.

- **`_cache_path(video_id: str, language: str) -> Path`** — returns `Path(tempfile.gettempdir()) / f"yt_{video_id}_{language}.xml"`. No subdir (per spec). `video_id` and `language` both pass a small regex sanitization so no filesystem escape is possible.

- **`_build_xml(title, description, languages_available, snippets, video_id, language) -> bytes`** — builds the XML tree via `lxml.etree.Element` / `SubElement`, serializes with `etree.tostring(root, pretty_print=True, xml_declaration=True, encoding='utf-8')`. Returns **bytes** (passing `encoding='utf-8'` with `xml_declaration=True` requires a real encoding — `encoding='unicode'` with `xml_declaration=True` raises `ValueError`, per the lxml gotcha). Uses `lxml.etree.CDATA(description)` for the description to avoid escaping issues with HTML/URLs/special chars.

- **`_parse_xml(cache_path: Path) -> CachedPayload`** — returns an internal dataclass holding the same fields we wrote. Uses `lxml.etree.parse(str(cache_path)).getroot()` and `.find()` / `.iter()` accessors. Note: lxml's default parser **strips CDATA markers** on read — that's fine here because we only need the *text content* of `<description>`, which is preserved. On parse failure → delete the corrupt file and raise `_CacheMissError` so the caller refetches cleanly (no silent corruption).

- **`_fetch_from_youtube(client, url_or_id, language) -> CachedPayload`** — orchestrates yt-dlp + youtube_transcript_api calls, all wrapped with `anyio.to_thread.run_sync` since both libs do blocking network I/O. Raises `ValueError` with useful context on failure (language not available, video unavailable, transcripts disabled).

- **`_shape_response(payload, include_transcript, include_timestamps, cache_hit) -> str`** — formats the final Markdown response (see "Output format" below).

**XML schema** (`version="1"` for forward-compat so we can invalidate old caches):

```xml
<?xml version="1.0" encoding="utf-8"?>
<video version="1" id="VID" langcode="en" fetched_at="2026-04-13T10:00:00Z">
  <title>How to cook pasta</title>
  <description><![CDATA[Full description with HTML, URLs, emoji...]]></description>
  <available_languages>
    <lang code="en" name="English" generated="true"/>
    <lang code="es" name="Spanish" generated="false"/>
  </available_languages>
  <transcript>
    <seg start="0.0" duration="3.2">Welcome back to</seg>
    <seg start="3.2" duration="5.0">my cooking channel</seg>
    ...
  </transcript>
</video>
```

**Cache invalidation**: if `<video version>` attribute doesn't equal `"1"` when reading, treat as miss. If XML fails to parse, delete the corrupt file and treat as miss.

### 4. `src/aismartbuddy/server.py` — register tool + lifespan integration

- Import the tool:
  ```
  from aismartbuddy.tools.youtube import get_youtube_information
  ```
- Add to `_TOOLS` list:
  ```
  (get_youtube_information, "get_youtube_information", "Get YouTube Video Information", _READONLY),
  ```
  Chosen `_READONLY` because the tool doesn't modify any MCP server state — the disk cache is an internal implementation detail, not state the tool mutates on behalf of the caller.
- Extend `app_lifespan` to init/close the YouTube client:
  ```
  from aismartbuddy import youtube_client as yt_mod
  ...
  # after SessionManager init:
  try:
      yt_mod.youtube_client = yt_mod.YouTubeClient.create()
  except Exception:
      logger.exception("YouTubeClient init failed; get_youtube_information will be unavailable")
      yt_mod.youtube_client = None
  try:
      yield
  finally:
      tg.cancel_scope.cancel()
  session_mod.session_manager.cleanup_all()
  # Guard against failed init — close only if it exists
  if yt_mod.youtube_client is not None:
      yt_mod.youtube_client.close()
      yt_mod.youtube_client = None
  ```
  Failure of the YouTube init does NOT prevent server startup. The tool checks `if youtube_client is None` and raises a clear error at call-time.

### 5. Output format (Markdown sections)

**Cache hit, full output**:
```
# YouTube iAA7PTqs4xY | lang=en | cache=hit
## Title
How to cook pasta
## Description
Join me as we cook a perfect pasta dish in under 15 minutes.
Visit our website: https://example.com
## Transcripts available
en (auto), es (auto), fr
## Transcript
[0:00] Welcome back to
[0:03] my cooking channel
[0:08] today we're making...
```

- Header line: `# YouTube {video_id} | lang={language} | cache={hit|miss}`
- `## Transcripts available` — comma-separated `code (auto)` or `code` (manually created), omit `(auto)` for human-created.
- `## Transcript` — one segment per line. Format is `[MM:SS] text` for videos < 1 hour, `[H:MM:SS] text` for videos ≥ 1 hour. Auto-selects from max segment timestamp.
- If `include_transcript=False` → omit the `## Transcript` section entirely (still include the rest).
- If `include_timestamps=False` and `include_transcript=True` → `## Transcript` with each segment on its own line, no `[MM:SS]` prefix.

### 6. Tool description (docstring)

The docstring MUST include the "save to file first" recommendation the user asked for. Structure:

- One-sentence summary: "Fetch title, description, available transcript languages, and the full timed transcript of a YouTube video in a single call."
- Paragraph on caching: "Results are cached at the OS temp directory under `yt_{video_id}_{language}.xml`. Subsequent calls with the same video + language are served from cache."
- Paragraph on large outputs: "Long videos produce long transcripts. For hour-long videos, the response may exceed your context budget. Consider writing the tool's response to a file via your filesystem tool (or a subagent) and then processing it in sections, rather than holding the full transcript inline."
- `Example:` line showing a minimal call.
- `See also:` pointing to the MCP server's other tools (optional — keep short).
- Full `Args:` / `Returns:` sections.

### 7. Tests

**New file `tests/test_youtube_tool.py`**:

1. `test_parse_video_id_from_watch_url` — `watch?v=VID` → `VID`
2. `test_parse_video_id_from_youtu_be` — `youtu.be/VID` → `VID`
3. `test_parse_video_id_from_shorts` — `youtube.com/shorts/VID` → `VID`
4. `test_parse_video_id_passthrough` — `"iAA7PTqs4xY"` (raw 11 chars) → `"iAA7PTqs4xY"`
5. `test_parse_video_id_rejects_garbage` — invalid URL raises `ValueError`
6. `test_cache_hit_short_circuits_network` — pre-populate a valid XML cache file, monkeypatch `YouTubeClient` to raise if called, confirm the tool still returns and contains the cached title.
7. `test_cache_miss_writes_then_reads` — mock both yt-dlp `extract_info` and `YouTubeTranscriptApi.fetch` / `list`, call tool twice, assert the mocks were hit only once (first call) and the second call used the cache.
8. `test_include_transcript_false_hides_transcript_section` — response Markdown lacks `## Transcript`.
9. `test_include_timestamps_false_strips_timestamps` — segments rendered without `[MM:SS]` prefix.
10. `test_hour_long_uses_hhmmss_format` — stub a transcript with start=3700.0; assert prefix is `[1:01:40]` not `[61:40]`.
11. `test_corrupt_cache_is_replaced` — write malformed XML to the cache path, call tool with mocks; tool refetches and overwrites cleanly without raising.
12. `test_version_mismatch_refetches` — write XML with `version="0"`, call tool, assert mocks were called (cache treated as miss).
13. `test_language_unavailable_error_message` — mock `fetch` to raise `NoTranscriptFound`; tool returns a clear error that includes the list of available languages from `list(video_id)`.
14. `test_integration_real_video` — **parametrized over both test videos (`iAA7PTqs4xY` and `LM7DByKOHBs`)**. Marked `@pytest.mark.integration`, skipped by default (`-m "not integration"` in pytest.ini_options or via env var). Hits each video live; validates schema (valid XML at expected path), required fields are populated (non-empty title, description, at least one transcript segment), and calling a second time returns from cache with `cache=hit` in the response header.

Fixtures:
- `tmp_path` from pytest + monkeypatch `tempfile.gettempdir` so caches land under the test temp dir, auto-cleaned after each test.
- A `mock_youtube_client` fixture that replaces `youtube_client.youtube_client` with a Mock that returns canned data.

### 8. Documentation

- Update `CLAUDE.md`:
  - Bump tool count from 48 to 49 in the "Key patterns" section.
  - Add a one-line bullet under that section about `get_youtube_information`: "Fetches a YouTube video's title, description, available transcript languages, and timed transcript in a single call. Cached as XML at the OS temp dir (`yt_{videoid}_{langcode}.xml`). Supports cache hit/miss, language selection, and transcript/timestamp flags."
  - Add `identity.py` already there — add `youtube_client.py` to the architecture diagram at the same indent level.
- The two docs-researcher output files (`.meridian/api-docs/yt-dlp.md`, `.meridian/api-docs/lxml.md`) land automatically during the background research — reference them in `youtube_client.py` and `tools/youtube.py` module docstrings ("see `.meridian/api-docs/yt-dlp.md`").

---

## Critical Files

| File | Action | Purpose |
|---|---|---|
| `pyproject.toml` | modify | Bump duckdb, real-ladybug; add lxml, yt-dlp, youtube-transcript-api |
| `src/aismartbuddy/youtube_client.py` | **create** | `YouTubeClient` dataclass + singleton + `_parse_video_id` helper |
| `src/aismartbuddy/tools/youtube.py` | **create** | `get_youtube_information` tool + XML cache read/write + Markdown formatter |
| `src/aismartbuddy/server.py` | modify | Import + register tool in `_TOOLS`; init/close `youtube_client` in `app_lifespan` |
| `tests/test_youtube_tool.py` | **create** | Unit tests (mocked) + optional integration test for real videos |
| `CLAUDE.md` | modify | Tool count 48→49; new bullet; architecture diagram add `youtube_client.py` |

No changes to session.py, identity.py, engines/, or any other tool module.

---

## Decisions

1. **Shared YouTube client in lifespan, not per-call**: `YoutubeDL` and `YouTubeTranscriptApi` are expensive to construct (yt-dlp loads the YouTube extractor; http_client opens a connection pool). Mirroring the example code's lifespan pattern gives us warm resources across tool calls.

2. **Module-level singleton (not lifespan context dict)**: Matches the existing `session_manager` pattern for consistency with the rest of the codebase. No need to thread `ctx.request_context.lifespan_context["youtube"]` through tool code.

3. **youtube-transcript-api is NOT thread-safe** — each thread needs its own `YouTubeTranscriptApi` instance. The underlying reason is the shared `requests.Session`; strictly speaking, true thread-safety would require a per-call `http_client` as well. For the current FastMCP dispatch model (one worker thread per call via `anyio.to_thread.run_sync`) this is not an issue. To **partially mitigate** the risk if future FastMCP versions dispatch in parallel, we create a **new `YouTubeTranscriptApi` instance per call** (cheap — it just wraps the shared `http_client`), while keeping the shared `http_client` and `YoutubeDL` as the singleton. This is a small deviation from the example code; documented in a comment inside `youtube_client.py`.

4. **Cache file naming**: strictly `yt_{video_id}_{language}.xml` with no subdirectories, per the user's spec. Both `video_id` (matched to `^[A-Za-z0-9_-]{11}$`) and `language` (matched to `^[A-Za-z0-9_-]{1,10}$`) are validated before being used in the path to prevent filesystem escape.

5. **Always cache the full transcript with timestamps**: the `include_transcript` / `include_timestamps` flags only affect the response shape, never what's written to cache. This way subsequent calls with different flags reuse the same cache file.

6. **Language mismatch is an error, not silent fallback**: if the user asks for `language="fr"` but only `en` is available, raise a clear error listing available languages. Do NOT auto-fallback — this matches the principle of explicit behavior.

7. **yt-dlp via `auto_init=False` + manual `YoutubeIE()` registration**: from the user's example code. Avoids the 1-2s delay of loading every site's extractor when we only need YouTube.

8. **`_READONLY` annotation**: the tool is read-only from the MCP client's point of view. The disk cache is an internal optimization — not state the tool is mutating on the caller's behalf.

9. **Response format is Markdown with per-line segment timestamps**: confirmed with user. `[MM:SS]` for videos < 1 hour, `[H:MM:SS]` for videos ≥ 1 hour (auto-selected from max timestamp in the transcript).

10. **No bs4 / `humanize` dependencies**: the example code uses them for title-scraping and human-friendly durations respectively. We don't need bs4 because yt-dlp already gives the title. For duration, we render `duration` as `H:MM:SS` from the integer seconds returned by yt-dlp — no extra dep.

---

## Acceptance Criteria

1. `uv sync` succeeds with the new dependencies and version bumps.
2. `uv run pytest -v` shows all existing 233 tests still pass + ~13 new unit tests in `test_youtube_tool.py` pass.
3. `uv run ruff check src/ tests/` is clean.
4. `uv run pyright` is clean (or only pre-existing warnings, no new ones).
5. Starting the server via `uv run python -m aismartbuddy` logs `YouTubeClient initialized` (no exceptions).
6. First call to `get_youtube_information("https://www.youtube.com/watch?v=iAA7PTqs4xY")`:
   - Creates `{tempdir}/yt_iAA7PTqs4xY_en.xml`
   - Returns Markdown with `cache=miss`, title, description, available languages, full timed transcript
7. Second call to the same URL:
   - Returns Markdown with `cache=hit`
   - No network calls (verifiable by monkeypatching or by observing response time — sub-50 ms)
8. Call with `include_transcript=False` returns everything except the `## Transcript` section.
9. Call with `include_timestamps=False` returns the transcript as plain lines without `[MM:SS]` prefixes.
10. Call with `language="fr"` for a video that lacks French → clear error message listing available languages.
11. Both test videos (`iAA7PTqs4xY`, `LM7DByKOHBs`) produce valid XML caches and valid Markdown responses.

---

## Verification

After implementation, run:

```bash
# Dependency sync + lint + type + tests
rtk uv sync
rtk uv run ruff check src/ tests/
rtk uv run pytest -v
rtk uv run pyright

# Unit test subset
rtk uv run pytest tests/test_youtube_tool.py -v

# Optional integration test (hits the network)
rtk uv run pytest -m integration -v

# Manual end-to-end verification
uv run python -c "
import anyio
from aismartbuddy import youtube_client as yt_mod
from aismartbuddy.tools.youtube import get_youtube_information

async def main():
    yt_mod.youtube_client = yt_mod.YouTubeClient.create()
    try:
        # First call — cache miss
        out = await get_youtube_information('https://www.youtube.com/watch?v=iAA7PTqs4xY')
        print(out[:500])
        print('---')
        # Second call — cache hit
        out2 = await get_youtube_information('https://www.youtube.com/watch?v=iAA7PTqs4xY')
        assert 'cache=hit' in out2
        # Transcript-disabled
        out3 = await get_youtube_information('https://www.youtube.com/watch?v=iAA7PTqs4xY', include_transcript=False)
        assert '## Transcript' not in out3
        # Second video
        out4 = await get_youtube_information('https://www.youtube.com/watch?v=LM7DByKOHBs')
        assert '# YouTube LM7DByKOHBs' in out4
    finally:
        yt_mod.youtube_client.close()

anyio.run(main)
"
```

Expected output:
- First call: takes a few seconds (network).
- Second call: returns immediately with `cache=hit` in the header.
- `/tmp` (or `%TEMP%`) contains `yt_iAA7PTqs4xY_en.xml` and `yt_LM7DByKOHBs_en.xml`.

---

## Non-Goals

- **Not changing the transcript storage format** — the user specified XML via lxml. No switch to Parquet / JSON / SQLite.
- **Not adding download features** — yt-dlp is used strictly in `skip_download=True` mode. No audio / video files are ever written.
- **No playlist or channel support** — the tool accepts a single video URL or ID only.
- **No cache pagination / cursor API** — the user chose "return all segments, no truncation".
- **No bs4 / humanize dependencies** — leaner footprint.
- **No proxy configuration** — the example code supports proxies; we skip it for the first cut. Can be added later if needed (open a follow-up).
- **No API key / OAuth** — this tool uses youtube-transcript-api's public endpoint + yt-dlp's HTML scraping; no YouTube Data API usage.
- **No changes to existing engines, tools, session management, identity, pagination, or multi-tenant behavior** — this is a pure addition.

---

## TLDR

Add one MCP tool `get_youtube_information(url_or_id, language="en", include_transcript=True, include_timestamps=True)` that returns a video's title, description, available transcript languages, and full timed transcript in Markdown. Cache the full payload as lxml-built XML at `{OS_temp_dir}/yt_{videoid}_{langcode}.xml` (OS handles cleanup). Bump duckdb, real-ladybug and add lxml, yt-dlp, youtube-transcript-api pins. Shared http_client + YoutubeDL live in a module-level singleton initialized in the server's `app_lifespan` (same pattern as `session_manager`). Tool docstring recommends saving the response to a file first for long videos.
