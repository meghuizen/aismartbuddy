"""Tests for get_youtube_information MCP tool.

Unit tests use mocks to avoid network. Integration tests (marked
@pytest.mark.integration) hit the real YouTube API and are skipped by default
(see pyproject.toml: addopts = "-m 'not integration'"). Run them explicitly
with `uv run pytest -m integration`.
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass, field
from unittest.mock import MagicMock

import pytest

from aismartbuddy import youtube_client as yt_mod
from aismartbuddy.tools import youtube as ytool
from aismartbuddy.youtube_client import parse_video_id

# ── Fake fixtures ──────────────────────────────────────────────


@dataclass
class _FakeSnippet:
    """Mimics FetchedTranscriptSnippet."""

    text: str
    start: float
    duration: float


@dataclass
class _FakeFetchedTranscript:
    snippets: list[_FakeSnippet] = field(default_factory=list)


@dataclass
class _FakeTranscript:
    language_code: str
    language: str
    is_generated: bool


class _FakeTranscriptList:
    def __init__(self, transcripts: list[_FakeTranscript]) -> None:
        self._transcripts = transcripts

    def __iter__(self):
        return iter(self._transcripts)


def _default_snippets() -> list[_FakeSnippet]:
    return [
        _FakeSnippet(text="Welcome back to", start=0.0, duration=3.2),
        _FakeSnippet(text="my cooking channel", start=3.2, duration=5.0),
        _FakeSnippet(text="today we're making pasta", start=8.2, duration=4.5),
    ]


def _default_languages() -> list[_FakeTranscript]:
    return [
        _FakeTranscript(language_code="en", language="English", is_generated=True),
        _FakeTranscript(language_code="es", language="Spanish", is_generated=True),
        _FakeTranscript(language_code="fr", language="French", is_generated=False),
    ]


def _make_fake_client(
    snippets: list[_FakeSnippet] | None = None,
    languages: list[_FakeTranscript] | None = None,
    title: str = "How to cook pasta",
    description: str = "Join me as we cook a perfect pasta dish.",
    fetch_raises: Exception | None = None,
    list_raises: Exception | None = None,
) -> MagicMock:
    """Build a YouTubeClient-shaped mock."""
    client = MagicMock(spec=yt_mod.YouTubeClient)

    # dlp.extract_info → dict
    client.dlp = MagicMock()
    client.dlp.extract_info.return_value = {
        "title": title,
        "description": description,
    }

    # ytt_api.list → TranscriptList
    ytt_api = MagicMock()
    langs = languages if languages is not None else _default_languages()
    if list_raises:
        ytt_api.list.side_effect = list_raises
    else:
        ytt_api.list.return_value = _FakeTranscriptList(langs)

    # ytt_api.fetch → FetchedTranscript
    snips = snippets if snippets is not None else _default_snippets()
    if fetch_raises:
        ytt_api.fetch.side_effect = fetch_raises
    else:
        ytt_api.fetch.return_value = _FakeFetchedTranscript(snippets=snips)

    client.make_ytt_api.return_value = ytt_api
    return client


@pytest.fixture(autouse=True)
def _isolated_tempdir(tmp_path, monkeypatch):
    """Redirect tempfile.gettempdir to a per-test tmp_path.

    Ensures each test has a clean cache directory and nothing leaks between
    tests or into the real OS temp dir.
    """
    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(tmp_path))
    yield
    # tmp_path cleanup is automatic


@pytest.fixture
def install_client():
    """Install a fake YouTubeClient as the module singleton for the duration
    of the test, then restore None.
    """
    orig = yt_mod.youtube_client
    yield lambda client: setattr(yt_mod, "youtube_client", client)
    yt_mod.youtube_client = orig


# ── parse_video_id ─────────────────────────────────────────────


class TestParseVideoId:
    def test_from_watch_url(self):
        assert parse_video_id("https://www.youtube.com/watch?v=iAA7PTqs4xY") == "iAA7PTqs4xY"

    def test_from_youtu_be(self):
        assert parse_video_id("https://youtu.be/iAA7PTqs4xY") == "iAA7PTqs4xY"

    def test_from_shorts(self):
        assert parse_video_id("https://www.youtube.com/shorts/iAA7PTqs4xY") == "iAA7PTqs4xY"

    def test_from_embed(self):
        assert parse_video_id("https://www.youtube.com/embed/iAA7PTqs4xY") == "iAA7PTqs4xY"

    def test_raw_id_passthrough(self):
        assert parse_video_id("iAA7PTqs4xY") == "iAA7PTqs4xY"

    def test_music_host(self):
        assert parse_video_id("https://music.youtube.com/watch?v=LM7DByKOHBs") == "LM7DByKOHBs"

    def test_rejects_garbage(self):
        with pytest.raises(ValueError):
            parse_video_id("not a url and not an id")

    def test_rejects_empty(self):
        with pytest.raises(ValueError):
            parse_video_id("")

    def test_rejects_wrong_length_id(self):
        # 10 chars - not a valid video ID
        with pytest.raises(ValueError):
            parse_video_id("tooshortID")

    def test_rejects_non_youtube_url(self):
        with pytest.raises(ValueError):
            parse_video_id("https://vimeo.com/watch?v=abc")


# ── Cache behaviour ────────────────────────────────────────────


@pytest.mark.anyio
async def test_cache_miss_writes_xml(install_client, tmp_path):
    client = _make_fake_client()
    install_client(client)
    video_id = "iAA7PTqs4xY"

    result = await ytool.get_youtube_information(
        f"https://www.youtube.com/watch?v={video_id}"
    )

    # Cache file created at expected path
    cache_file = tmp_path / f"yt_{video_id}_en.xml"
    assert cache_file.exists()
    xml_bytes = cache_file.read_bytes()
    assert xml_bytes.startswith(b"<?xml")
    assert b'version="1"' in xml_bytes
    assert b'id="iAA7PTqs4xY"' in xml_bytes
    assert b"Welcome back to" in xml_bytes

    # Response shape
    assert "cache=miss" in result
    assert "## Title" in result
    assert "How to cook pasta" in result
    assert "## Description" in result
    assert "## Transcripts available" in result
    assert "en (auto)" in result
    assert "fr" in result and "fr (auto)" not in result  # fr is manually created
    assert "## Transcript" in result
    assert "[00:00]" in result  # MM:SS for short video


@pytest.mark.anyio
async def test_cache_hit_short_circuits_network(install_client, tmp_path):
    client = _make_fake_client()
    install_client(client)
    video_id = "LM7DByKOHBs"
    url = f"https://www.youtube.com/watch?v={video_id}"

    # First call — writes cache
    await ytool.get_youtube_information(url)
    assert client.dlp.extract_info.call_count == 1
    assert client.make_ytt_api.call_count == 1

    # Second call — should NOT hit the network
    result2 = await ytool.get_youtube_information(url)
    assert "cache=hit" in result2
    # Still the same call counts as the first call
    assert client.dlp.extract_info.call_count == 1
    assert client.make_ytt_api.call_count == 1


@pytest.mark.anyio
async def test_include_transcript_false_hides_section(install_client):
    client = _make_fake_client()
    install_client(client)

    result = await ytool.get_youtube_information(
        "iAA7PTqs4xY", include_transcript=False
    )

    assert "## Title" in result
    assert "## Description" in result
    assert "## Transcripts available" in result
    # The `## Transcript\n` section (not `## Transcripts available`) is gone
    assert "## Transcript\n" not in result + "\n"
    assert "Welcome back to" not in result


@pytest.mark.anyio
async def test_include_timestamps_false_strips_prefixes(install_client):
    client = _make_fake_client()
    install_client(client)

    result = await ytool.get_youtube_information(
        "iAA7PTqs4xY", include_timestamps=False
    )

    assert "## Transcript" in result
    assert "Welcome back to" in result
    # No [MM:SS] or [H:MM:SS] markers
    assert "[00:00]" not in result
    assert "[0:00:00]" not in result


@pytest.mark.anyio
async def test_hour_long_video_uses_hhmmss(install_client):
    long_snippets = [
        _FakeSnippet(text="intro", start=0.0, duration=5.0),
        _FakeSnippet(text="mid-video", start=1800.0, duration=5.0),
        # 1:01:40 — over the 1-hour mark
        _FakeSnippet(text="late segment", start=3700.0, duration=5.0),
    ]
    client = _make_fake_client(snippets=long_snippets)
    install_client(client)

    result = await ytool.get_youtube_information("iAA7PTqs4xY")

    # Uses H:MM:SS, so the last segment is [1:01:40]
    assert "[1:01:40]" in result
    # And earlier segments also use H:MM:SS format
    assert "[0:30:00]" in result
    assert "[0:00:00]" in result
    # NOT MM:SS format (would have been [01:01:40] truncated-hours)
    assert "[30:00]" not in result


@pytest.mark.anyio
async def test_corrupt_cache_is_replaced(install_client, tmp_path):
    client = _make_fake_client()
    install_client(client)
    video_id = "iAA7PTqs4xY"
    cache_file = tmp_path / f"yt_{video_id}_en.xml"
    # Pre-populate with garbage
    cache_file.write_bytes(b"this is <<< not valid xml >>>")

    # Should refetch and overwrite without raising
    result = await ytool.get_youtube_information(
        f"https://youtu.be/{video_id}"
    )
    assert "cache=miss" in result
    assert cache_file.exists()
    assert cache_file.read_bytes().startswith(b"<?xml")


@pytest.mark.anyio
async def test_version_mismatch_refetches(install_client, tmp_path):
    client = _make_fake_client()
    install_client(client)
    video_id = "iAA7PTqs4xY"
    cache_file = tmp_path / f"yt_{video_id}_en.xml"
    # Write an older-schema cache (version="0")
    cache_file.write_bytes(
        b'<?xml version="1.0"?><video version="0" id="iAA7PTqs4xY" '
        b'langcode="en" fetched_at="2024-01-01"><title>stale</title>'
        b"<description>stale</description><available_languages/>"
        b"<transcript/></video>"
    )

    result = await ytool.get_youtube_information(
        f"https://youtu.be/{video_id}"
    )
    # Must have refetched (cache=miss) and overwritten
    assert "cache=miss" in result
    assert client.dlp.extract_info.call_count == 1
    xml_now = cache_file.read_bytes()
    assert b'version="1"' in xml_now


@pytest.mark.anyio
async def test_language_unavailable_degrades_no_cache(install_client, tmp_path):
    """Requesting a language not in the available list returns a degraded
    response (metadata + error block listing alternatives) and does NOT
    write a cache file. The AI agent can then retry with one of the
    suggested codes."""
    from youtube_transcript_api._errors import NoTranscriptFound

    client = _make_fake_client(
        fetch_raises=NoTranscriptFound(
            video_id="iAA7PTqs4xY",
            requested_language_codes=["de"],
            transcript_data=None,
        )
    )
    install_client(client)

    result = await ytool.get_youtube_information("iAA7PTqs4xY", language="de")

    # Header signals degradation
    assert "cache=miss-degraded" in result
    # Metadata still present
    assert "## Title" in result
    assert "How to cook pasta" in result
    # Available langs listed for the agent
    assert "## Transcripts available" in result
    # Error block under Transcript with stable category + actionable hint
    assert "## Transcript" in result
    assert "TRANSCRIPT_LANGUAGE_NOT_AVAILABLE" in result
    assert "en" in result
    assert "fr" in result
    assert "Hint:" in result
    # Crucially: no cache file written for partial results
    assert not (tmp_path / "yt_iAA7PTqs4xY_de.xml").exists()


@pytest.mark.anyio
async def test_transcripts_disabled_degrades_no_cache(install_client, tmp_path):
    """When the uploader disabled transcripts, return metadata + error block
    and skip caching."""
    from youtube_transcript_api._errors import TranscriptsDisabled

    client = _make_fake_client(list_raises=TranscriptsDisabled("iAA7PTqs4xY"))
    install_client(client)

    result = await ytool.get_youtube_information("iAA7PTqs4xY")

    assert "cache=miss-degraded" in result
    assert "## Title" in result
    assert "TRANSCRIPTS_DISABLED" in result
    # No cache for degraded response
    assert not (tmp_path / "yt_iAA7PTqs4xY_en.xml").exists()


@pytest.mark.anyio
async def test_temporarily_unavailable_degrades(install_client, tmp_path):
    """The 'We're processing this video' case from real-world iAA7PTqs4xY.
    The transcript API raises CouldNotRetrieveTranscript; we surface it
    as a TEMPORARILY_UNAVAILABLE category, not a hard error."""
    from youtube_transcript_api._errors import CouldNotRetrieveTranscript

    # CouldNotRetrieveTranscript needs a video_id positional arg
    client = _make_fake_client(
        fetch_raises=CouldNotRetrieveTranscript("iAA7PTqs4xY")
    )
    install_client(client)

    result = await ytool.get_youtube_information("iAA7PTqs4xY")

    assert "cache=miss-degraded" in result
    assert "TRANSCRIPT_TEMPORARILY_UNAVAILABLE" in result
    assert "Retry" in result or "retry" in result
    # Degraded means no cache write — a follow-up call will re-attempt
    assert not (tmp_path / "yt_iAA7PTqs4xY_en.xml").exists()


@pytest.mark.anyio
async def test_rate_limited_degrades_with_proxy_hint(install_client, tmp_path):
    """When YouTube blocks us (IpBlocked / RequestBlocked / bot detection),
    the agent should learn this is rate-limiting and the hint should
    suggest a proxy or backoff."""
    from youtube_transcript_api._errors import IpBlocked

    client = _make_fake_client(fetch_raises=IpBlocked("iAA7PTqs4xY"))
    install_client(client)

    result = await ytool.get_youtube_information("iAA7PTqs4xY")

    assert "cache=miss-degraded" in result
    assert "TRANSCRIPT_RATE_LIMITED" in result
    assert "proxy" in result.lower() or "retry later" in result.lower()
    assert not (tmp_path / "yt_iAA7PTqs4xY_en.xml").exists()


@pytest.mark.anyio
async def test_network_error_on_list_degrades(install_client, tmp_path):
    """When ytt_api.list() fails with a generic exception (network blip,
    DNS, etc.) the language list is unavailable so the response is
    degraded with TRANSCRIPT_NETWORK_ERROR — distinct from the fetch
    path's TRANSCRIPT_UNKNOWN_ERROR."""
    client = _make_fake_client(list_raises=RuntimeError("network timeout"))
    install_client(client)

    result = await ytool.get_youtube_information("iAA7PTqs4xY")

    assert "cache=miss-degraded" in result
    assert "TRANSCRIPT_NETWORK_ERROR" in result
    # langs_available was unreachable, so the available-languages section
    # should show "(none)"
    assert "(none)" in result
    assert not (tmp_path / "yt_iAA7PTqs4xY_en.xml").exists()


@pytest.mark.anyio
async def test_unknown_error_on_fetch_degrades(install_client, tmp_path):
    """Fetch-side generic exceptions (non-mapped) should degrade with
    TRANSCRIPT_UNKNOWN_ERROR. Distinct from NETWORK_ERROR (which is
    list-side) — the language list IS available here."""
    client = _make_fake_client(fetch_raises=RuntimeError("unexpected upstream"))
    install_client(client)

    result = await ytool.get_youtube_information("iAA7PTqs4xY")

    assert "cache=miss-degraded" in result
    assert "TRANSCRIPT_UNKNOWN_ERROR" in result
    # langs_available WAS available (list succeeded), so they show up
    assert "en (auto)" in result
    assert "fr" in result
    assert not (tmp_path / "yt_iAA7PTqs4xY_en.xml").exists()


@pytest.mark.anyio
async def test_invalid_error_category_rejected_at_construction():
    """_ErrorInfo.__post_init__ must reject unknown category strings so a
    typo in tools/youtube.py fails loudly, not silently."""
    with pytest.raises(ValueError) as excinfo:
        ytool._ErrorInfo(
            category="TRANSCRIPT_DOES_NOT_EXIST_AS_CATEGORY",
            message="x",
            hint="y",
        )
    assert "Unknown _ErrorInfo category" in str(excinfo.value)


@pytest.mark.anyio
async def test_metadata_failure_still_raises(install_client):
    """When the metadata fetch (yt-dlp) itself fails, we have nothing
    useful to return — must raise ValueError (not degrade)."""
    client = _make_fake_client()
    client.dlp.extract_info.side_effect = RuntimeError("yt-dlp blew up")
    install_client(client)

    with pytest.raises(ValueError) as excinfo:
        await ytool.get_youtube_information("iAA7PTqs4xY")
    assert "metadata" in str(excinfo.value).lower()


@pytest.mark.anyio
async def test_missing_cache_file_falls_through(install_client, tmp_path):
    """TOCTOU: cache_path.exists() returns True but the file vanishes
    before _parse_xml reads it. Must NOT crash with OSError; must fall
    through to a fresh fetch."""
    import unittest.mock

    client = _make_fake_client()
    install_client(client)

    # Patch Path.exists to True but the file actually doesn't exist
    with unittest.mock.patch.object(
        ytool.Path, "exists", return_value=True
    ):
        # Should not raise — _parse_xml catches OSError and signals miss
        result = await ytool.get_youtube_information("iAA7PTqs4xY")
        assert "cache=miss" in result  # Either "miss" or "miss-degraded"


@pytest.mark.anyio
async def test_no_client_initialized_raises_clear_error(tmp_path):
    orig = yt_mod.youtube_client
    yt_mod.youtube_client = None
    try:
        with pytest.raises(RuntimeError) as excinfo:
            await ytool.get_youtube_information("iAA7PTqs4xY")
        assert "YouTubeClient not initialized" in str(excinfo.value)
    finally:
        yt_mod.youtube_client = orig


@pytest.mark.anyio
async def test_different_languages_use_separate_cache_files(install_client, tmp_path):
    client = _make_fake_client()
    install_client(client)
    video_id = "iAA7PTqs4xY"

    await ytool.get_youtube_information(video_id, language="en")
    await ytool.get_youtube_information(video_id, language="fr")

    assert (tmp_path / f"yt_{video_id}_en.xml").exists()
    assert (tmp_path / f"yt_{video_id}_fr.xml").exists()


# ── Integration tests (hit network, skipped by default) ─────


@pytest.mark.anyio
@pytest.mark.integration
@pytest.mark.parametrize("video_id", ["iAA7PTqs4xY", "LM7DByKOHBs"])
async def test_integration_real_video(video_id, tmp_path):
    """Hit the real YouTube API. Skipped unless `-m integration` is set."""
    # Real client (replaces the isolated tempdir fixture's fake setup)
    yt_mod.youtube_client = yt_mod.YouTubeClient.create()
    try:
        url = f"https://www.youtube.com/watch?v={video_id}"

        # First call — cache miss
        result = await ytool.get_youtube_information(url)
        assert f"# YouTube {video_id}" in result
        assert "cache=miss" in result
        assert "## Title" in result
        assert "## Description" in result
        assert "## Transcripts available" in result
        assert "## Transcript" in result

        # Cache file exists
        cache_file = tmp_path / f"yt_{video_id}_en.xml"
        assert cache_file.exists()
        assert cache_file.stat().st_size > 100  # non-trivial content

        # Second call — cache hit
        result2 = await ytool.get_youtube_information(url)
        assert "cache=hit" in result2
    finally:
        if yt_mod.youtube_client:
            yt_mod.youtube_client.close()
            yt_mod.youtube_client = None
