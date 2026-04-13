"""get_youtube_information MCP tool — fetches a video's metadata + transcript.

Single tool that returns title, description, available transcript languages,
and the full timed transcript in Markdown. Results cached on disk as
lxml-built XML under the OS temp directory (`yt_{video_id}_{langcode}.xml`).
OS handles cleanup — nothing to manage here.

See `.meridian/api-docs/yt-dlp.md`, `.meridian/api-docs/lxml.md`, and the
global `~/.meridian/api-docs/youtube-transcript-api.md`.
"""

from __future__ import annotations

import logging
import re
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

import anyio
from lxml import etree

from aismartbuddy import youtube_client as yt_mod
from aismartbuddy.youtube_client import parse_video_id

if TYPE_CHECKING:
    from youtube_transcript_api._transcripts import FetchedTranscriptSnippet

logger = logging.getLogger("aismartbuddy.tools.youtube")

# Cache schema version — bump if layout changes
_CACHE_VERSION = "1"

# Language code must be safe for a filename path component
_LANG_CODE_RE = re.compile(r"^[A-Za-z0-9_-]{1,10}$")


class _CacheMissError(Exception):
    """Internal signal that the on-disk cache can't be used and we must refetch."""


@dataclass
class _LanguageEntry:
    code: str
    name: str
    is_generated: bool


@dataclass
class _Segment:
    start: float
    duration: float
    text: str


# Stable category strings used in responses + tests. Frozen + validated in
# _ErrorInfo.__post_init__ so a typo at construction site fails loudly.
_ERROR_CATEGORIES = frozenset({
    "TRANSCRIPTS_DISABLED",
    "TRANSCRIPT_LANGUAGE_NOT_AVAILABLE",
    "TRANSCRIPT_TEMPORARILY_UNAVAILABLE",
    "TRANSCRIPT_RATE_LIMITED",
    "TRANSCRIPT_NETWORK_ERROR",
    "TRANSCRIPT_UNKNOWN_ERROR",
})


@dataclass
class _ErrorInfo:
    """Describes a partial-fetch failure where metadata succeeded but transcript
    (or another secondary element) didn't.

    Surfaced to the AI agent in the response's `## Transcript` section so it
    can decide whether to retry, switch language, or abandon the request.
    """

    category: str  # must be in _ERROR_CATEGORIES — validated below
    message: str   # human-readable upstream message (cleaned up)
    hint: str      # what the AI agent should try next

    def __post_init__(self) -> None:
        if self.category not in _ERROR_CATEGORIES:
            raise ValueError(
                f"Unknown _ErrorInfo category: {self.category!r}. "
                f"Valid: {sorted(_ERROR_CATEGORIES)}"
            )


@dataclass
class _CachedPayload:
    video_id: str
    language: str
    title: str
    description: str
    languages_available: list[_LanguageEntry]
    segments: list[_Segment] = field(default_factory=list)
    fetched_at: str = ""


# ── Cache path ─────────────────────────────────────────────────


def _cache_path(video_id: str, language: str) -> Path:
    """Return the cache file path for (video_id, language).

    Validates both components before constructing the path so a malicious
    input can't escape the temp directory.
    """
    # parse_video_id guarantees [A-Za-z0-9_-]{11}, but re-check for safety
    if not re.match(r"^[A-Za-z0-9_-]{11}$", video_id):
        raise ValueError(f"Invalid video_id: {video_id!r}")
    if not _LANG_CODE_RE.match(language):
        raise ValueError(f"Invalid language code: {language!r}")
    return Path(tempfile.gettempdir()) / f"yt_{video_id}_{language}.xml"


# ── XML build ──────────────────────────────────────────────────


def _build_xml(payload: _CachedPayload) -> bytes:
    """Serialize a payload to pretty-printed UTF-8 XML bytes.

    Returns bytes (not str) because passing `encoding='utf-8'` with
    `xml_declaration=True` requires a real encoding name — `encoding='unicode'`
    + `xml_declaration=True` raises ValueError in lxml.
    """
    root = etree.Element(
        "video",
        attrib={
            "version": _CACHE_VERSION,
            "id": payload.video_id,
            "langcode": payload.language,
            "fetched_at": payload.fetched_at,
        },
    )

    title_el = etree.SubElement(root, "title")
    title_el.text = payload.title or ""

    desc_el = etree.SubElement(root, "description")
    # CDATA protects HTML/URLs/emoji in descriptions from escaping round-trip issues
    desc_el.text = etree.CDATA(payload.description or "")

    langs_el = etree.SubElement(root, "available_languages")
    for lang in payload.languages_available:
        etree.SubElement(
            langs_el,
            "lang",
            attrib={
                "code": lang.code,
                "name": lang.name,
                "generated": "true" if lang.is_generated else "false",
            },
        )

    tr_el = etree.SubElement(root, "transcript")
    for seg in payload.segments:
        seg_el = etree.SubElement(
            tr_el,
            "seg",
            attrib={
                "start": f"{seg.start:.3f}",
                "duration": f"{seg.duration:.3f}",
            },
        )
        seg_el.text = seg.text

    return etree.tostring(
        root,
        pretty_print=True,
        xml_declaration=True,
        encoding="utf-8",
    )


# ── XML parse ──────────────────────────────────────────────────


def _parse_xml(cache_path: Path) -> _CachedPayload:
    """Load a cached payload from XML.

    Raises _CacheMissError if the file can't be parsed or the schema version
    doesn't match. The caller is responsible for refetching + overwriting.
    """
    try:
        tree = etree.parse(str(cache_path))
    except (etree.XMLSyntaxError, OSError) as exc:
        # Corrupt or vanished cache (TOCTOU: file may be deleted between the
        # exists() check and the parse, e.g. by OS temp cleanup or AV).
        # Delete what's left and signal a miss so the caller refetches cleanly.
        try:
            cache_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise _CacheMissError(f"Cache unreadable: {exc}") from exc

    root = tree.getroot()
    if root.tag != "video" or root.get("version") != _CACHE_VERSION:
        raise _CacheMissError(
            f"Cache version mismatch (got {root.get('version')!r}, "
            f"want {_CACHE_VERSION!r})"
        )

    video_id = root.get("id") or ""
    language = root.get("langcode") or ""
    fetched_at = root.get("fetched_at") or ""

    title = (root.findtext("title") or "").strip()
    # description may have had CDATA stripped on read; text content preserved
    description = root.findtext("description") or ""

    langs: list[_LanguageEntry] = []
    langs_el = root.find("available_languages")
    if langs_el is not None:
        for lang_el in langs_el.iter("lang"):
            langs.append(
                _LanguageEntry(
                    code=lang_el.get("code") or "",
                    name=lang_el.get("name") or "",
                    is_generated=(lang_el.get("generated") == "true"),
                )
            )

    segs: list[_Segment] = []
    tr_el = root.find("transcript")
    if tr_el is not None:
        for seg_el in tr_el.iter("seg"):
            try:
                start = float(seg_el.get("start") or "0")
                duration = float(seg_el.get("duration") or "0")
            except ValueError:
                continue
            segs.append(
                _Segment(start=start, duration=duration, text=seg_el.text or "")
            )

    return _CachedPayload(
        video_id=video_id,
        language=language,
        title=title,
        description=description,
        languages_available=langs,
        segments=segs,
        fetched_at=fetched_at,
    )


# ── Fetch from YouTube ─────────────────────────────────────────


def _fetch_payload(
    client: yt_mod.YouTubeClient,
    url_or_id: str,
    video_id: str,
    language: str,
) -> tuple[_CachedPayload, _ErrorInfo | None]:
    """Fetch title/description + available languages + transcript synchronously.

    Called inside anyio.to_thread.run_sync from the async tool.

    Returns:
        (payload, None) on full success — caller writes to cache.
        (payload_with_empty_segments, ErrorInfo) when METADATA succeeded but
            the transcript (or language list) couldn't be fetched. Caller
            should NOT write to cache (per design: cache only complete data).
        Raises ValueError if METADATA itself failed (nothing useful to return).
    """
    from youtube_transcript_api._errors import (
        CouldNotRetrieveTranscript,
        NoTranscriptFound,
        RequestBlocked,
        TranscriptsDisabled,
        VideoUnavailable,
        YouTubeRequestFailed,
    )
    # RequestBlocked covers IpBlocked AND bare bot-detection cases
    # (LOGIN_REQUIRED + BOT_DETECTED). IpBlocked is a subclass.

    # ── Step 1: metadata via yt-dlp (REQUIRED — if it fails, raise) ──
    try:
        info = client.dlp.extract_info(
            f"https://www.youtube.com/watch?v={video_id}", download=False
        )
    except Exception as exc:
        raise ValueError(
            f"Failed to fetch video metadata for {url_or_id!r}: {exc}"
        ) from exc
    if not isinstance(info, dict):
        raise ValueError(
            f"Unexpected metadata result for {url_or_id!r} (not a dict)"
        )

    title = info.get("title") or ""
    description = info.get("description") or ""
    fetched_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    # ── Step 2: list available transcript languages (degrade on failure) ──
    ytt_api = client.make_ytt_api()
    langs_available: list[_LanguageEntry] = []
    error_info: _ErrorInfo | None = None
    transcript_list = None
    try:
        transcript_list = ytt_api.list(video_id)
    except TranscriptsDisabled as exc:
        error_info = _ErrorInfo(
            category="TRANSCRIPTS_DISABLED",
            message=f"Transcripts are disabled for video {video_id!r}: {exc}",
            hint="The uploader disabled transcripts. No retry will succeed; "
            "skip the transcript or pick a different video.",
        )
    except VideoUnavailable as exc:
        # Anomaly: yt-dlp got metadata but the transcript API says video is
        # unavailable. Treat as terminal — raise with context.
        raise ValueError(
            f"Video {video_id!r} is unavailable: {exc}"
        ) from exc
    except (RequestBlocked, YouTubeRequestFailed) as exc:
        error_info = _ErrorInfo(
            category="TRANSCRIPT_RATE_LIMITED",
            message=f"YouTube blocked or rate-limited the request: {exc}",
            hint="Retry later. If persistent, configure a proxy or "
            "rotate the source IP.",
        )
    except Exception as exc:
        error_info = _ErrorInfo(
            category="TRANSCRIPT_NETWORK_ERROR",
            message=f"Failed to list transcripts: {exc}",
            hint="Likely a network or upstream issue. Retry in a few seconds.",
        )

    if transcript_list is not None:
        langs_available = [
            _LanguageEntry(
                code=t.language_code,
                name=t.language,
                is_generated=t.is_generated,
            )
            for t in transcript_list
        ]

    # ── Step 3: fetch the requested transcript (degrade on failure) ──
    segments: list[_Segment] = []
    if error_info is None:
        try:
            fetched = ytt_api.fetch(video_id, languages=[language])
        except NoTranscriptFound as exc:
            codes = ", ".join(sorted(lang.code for lang in langs_available))
            if codes:
                hint = f"Retry with one of the available language codes: {codes}"
            else:
                hint = (
                    "No transcripts are available for this video in any "
                    "language. The video may have just been uploaded, may be "
                    "live, or may have transcripts disabled. Skip the "
                    "transcript or try again later."
                )
            error_info = _ErrorInfo(
                category="TRANSCRIPT_LANGUAGE_NOT_AVAILABLE",
                message=(
                    f"Transcript not available in {language!r}. "
                    f"Upstream: {exc}"
                ),
                hint=hint,
            )
        except TranscriptsDisabled as exc:
            # Inconsistent with list() succeeding, but defensive
            error_info = _ErrorInfo(
                category="TRANSCRIPTS_DISABLED",
                message=f"Transcripts disabled: {exc}",
                hint="No retry will succeed; skip the transcript.",
            )
        except (RequestBlocked, YouTubeRequestFailed) as exc:
            error_info = _ErrorInfo(
                category="TRANSCRIPT_RATE_LIMITED",
                message=f"YouTube blocked or rate-limited the fetch: {exc}",
                hint="Retry later or configure a proxy.",
            )
        except CouldNotRetrieveTranscript as exc:
            # Catches "We're processing this video", live-stream-ongoing, etc.
            error_info = _ErrorInfo(
                category="TRANSCRIPT_TEMPORARILY_UNAVAILABLE",
                message=f"YouTube reports the transcript is not retrievable: {exc}",
                hint=(
                    "Likely transient: video may still be processing, may be "
                    "an ongoing live stream, or YouTube is having an outage. "
                    "Retry in a few minutes."
                ),
            )
        except Exception as exc:
            error_info = _ErrorInfo(
                category="TRANSCRIPT_UNKNOWN_ERROR",
                message=f"Unexpected transcript fetch error: {exc}",
                hint="Likely a network or upstream issue. Retry may succeed.",
            )
        else:
            snip: FetchedTranscriptSnippet
            for snip in fetched.snippets:
                segments.append(
                    _Segment(
                        start=snip.start, duration=snip.duration, text=snip.text
                    )
                )

    payload = _CachedPayload(
        video_id=video_id,
        language=language,
        title=title,
        description=description,
        languages_available=langs_available,
        segments=segments,
        fetched_at=fetched_at,
    )
    return payload, error_info


# ── Response formatter ────────────────────────────────────────


def _format_timestamp(seconds: float, hours_format: bool) -> str:
    """Format `seconds` as [MM:SS] or [H:MM:SS]."""
    total = int(seconds)
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    if hours_format:
        return f"[{h}:{m:02d}:{s:02d}]"
    # For videos < 1h, use MM:SS
    return f"[{m:02d}:{s:02d}]"


def _shape_response(
    payload: _CachedPayload,
    include_transcript: bool,
    include_timestamps: bool,
    cache_hit: bool,
    error_info: _ErrorInfo | None = None,
) -> str:
    """Build the Markdown response from a payload + flags.

    When `error_info` is non-None, the metadata sections are still emitted
    (graceful degradation) and the `## Transcript` section becomes a
    structured error block telling the AI agent what went wrong and what
    to try next. This only happens on cache miss with a partial fetch —
    cache hits always have full data because we never persist partials.
    """
    parts: list[str] = []
    if error_info is None:
        cache_label = "hit" if cache_hit else "miss"
    else:
        # Make the degradation explicit in the header so the AI immediately
        # knows what state it's looking at.
        cache_label = "miss-degraded"
    header = (
        f"# YouTube {payload.video_id} | lang={payload.language} "
        f"| cache={cache_label}"
    )
    parts.append(header)

    parts.append("## Title")
    parts.append(payload.title or "(no title)")

    parts.append("## Description")
    parts.append(payload.description or "(no description)")

    parts.append("## Transcripts available")
    if payload.languages_available:
        lang_bits = []
        for lang in payload.languages_available:
            if lang.is_generated:
                lang_bits.append(f"{lang.code} (auto)")
            else:
                lang_bits.append(lang.code)
        parts.append(", ".join(lang_bits))
    else:
        parts.append("(none)")

    if include_transcript:
        parts.append("## Transcript")
        if error_info is not None:
            # Render the error in a stable, machine-skimmable shape so the
            # AI agent can decide whether to retry or change its request.
            parts.append(f"**Unavailable** — category: `{error_info.category}`")
            parts.append(f"- Reason: {error_info.message}")
            parts.append(f"- Hint: {error_info.hint}")
            parts.append(
                "- Note: this response was NOT cached; a future call will "
                "re-fetch."
            )
        elif not payload.segments:
            # Shouldn't happen on a clean fetch (we'd have set error_info),
            # but defensive.
            parts.append("(empty)")
        else:
            # Decide MM:SS vs H:MM:SS once, based on the last segment
            max_start = max(seg.start for seg in payload.segments)
            hours_format = max_start >= 3600
            if include_timestamps:
                for seg in payload.segments:
                    ts = _format_timestamp(seg.start, hours_format)
                    parts.append(f"{ts} {seg.text}")
            else:
                for seg in payload.segments:
                    parts.append(seg.text)

    return "\n".join(parts)


# ── Tool ─────────────────────────────────────────────────────


async def get_youtube_information(
    url_or_id: str,
    language: str = "en",
    include_transcript: bool = True,
    include_timestamps: bool = True,
) -> str:
    """Fetch title, description, available transcript languages, and the full
    timed transcript of a YouTube video in a single call.

    Results are cached at the OS temp directory under `yt_{video_id}_{language}.xml`.
    Subsequent calls with the same video + language are served from cache
    (sub-50 ms) and skip all network calls. The OS handles eventual cleanup.

    Caching policy: results are cached ONLY when all data is present
    (metadata + transcript). If the transcript can't be retrieved (uploader
    disabled it, language not available, video still processing, network
    blip, etc.) the response is returned in degraded form (metadata only,
    plus a structured error block under `## Transcript`) and is NOT cached.
    Subsequent calls will re-fetch.

    The header line ends with `cache=hit` (full from cache), `cache=miss`
    (full from fresh fetch, now cached), or `cache=miss-degraded` (partial
    fetch, not cached).

    Degraded responses include a `## Transcript` block with:
      - `category`: stable code, exactly one of: TRANSCRIPTS_DISABLED,
        TRANSCRIPT_LANGUAGE_NOT_AVAILABLE, TRANSCRIPT_TEMPORARILY_UNAVAILABLE,
        TRANSCRIPT_RATE_LIMITED, TRANSCRIPT_NETWORK_ERROR,
        TRANSCRIPT_UNKNOWN_ERROR
      - `Reason`: upstream message
      - `Hint`: actionable next step

    Long videos produce long transcripts. For hour-long videos, the response
    may exceed your context budget. Consider writing the tool's response to
    a file via your filesystem tool (or a subagent) and then processing it
    in sections, rather than holding the full transcript inline.

    Input accepts: raw 11-char video ID, `https://www.youtube.com/watch?v=VID`,
    `https://youtu.be/VID`, `https://www.youtube.com/embed/VID`, or
    `https://www.youtube.com/shorts/VID`.

    Example: get_youtube_information("https://www.youtube.com/watch?v=iAA7PTqs4xY")

    Args:
        url_or_id: YouTube video URL or 11-character video ID.
        language: Preferred transcript language code. Default "en".
            If the requested language is not available, the response is
            degraded (metadata + error block listing available languages),
            not raised — so the AI can pick a different language and retry.
        include_transcript: Default True. Set False to skip the transcript
            entirely in the response (metadata + available languages only).
        include_timestamps: Default True. Set False to return the transcript
            text only (one segment per line, no `[MM:SS]` prefix).

    Returns:
        Markdown-formatted response with sections: header, Title, Description,
        Transcripts available, Transcript (optional). Format is
        `[MM:SS] text` for videos under 1 hour and `[H:MM:SS] text` for
        videos 1 hour or longer.
    """
    # 1) Validate identity + compute cache path
    video_id = parse_video_id(url_or_id)
    if not language:
        language = "en"
    cache_path = _cache_path(video_id, language)

    # 2) Try cache first
    cache_hit = False
    payload: _CachedPayload | None = None
    if cache_path.exists():
        try:
            payload = await anyio.to_thread.run_sync(_parse_xml, cache_path)
            cache_hit = True
        except _CacheMissError:
            payload = None

    # 3) Fetch + (conditionally) write cache on miss
    error_info: _ErrorInfo | None = None
    if payload is None:
        if yt_mod.youtube_client is None:
            raise RuntimeError(
                "YouTubeClient not initialized. Server lifespan may have failed "
                "to construct it — check server startup logs."
            )
        client = yt_mod.youtube_client
        payload, error_info = await anyio.to_thread.run_sync(
            _fetch_payload, client, url_or_id, video_id, language
        )
        # Cache only when ALL information is present. If any data element is
        # missing (transcript disabled, language not available, network blip,
        # processing, etc.) we skip the cache write so a future call will
        # re-attempt the fetch instead of serving a permanently-incomplete
        # response.
        if error_info is None:
            xml_bytes = _build_xml(payload)
            await anyio.to_thread.run_sync(
                lambda: cache_path.write_bytes(xml_bytes)
            )

    return _shape_response(
        payload, include_transcript, include_timestamps, cache_hit, error_info
    )
