"""Shared YouTube client for the get_youtube_information tool.

Holds a shared `requests.Session` and a configured `YoutubeDL` instance so
subsequent tool calls don't pay the initialization cost on every invocation.
The singleton is initialized in `server.py:app_lifespan` (same pattern as
the `session_manager` in session.py).

See `.meridian/api-docs/yt-dlp.md` and the global
`~/.meridian/api-docs/youtube-transcript-api.md` for full API references.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING
from urllib.parse import parse_qs, urlparse

if TYPE_CHECKING:
    import requests
    from youtube_transcript_api import YouTubeTranscriptApi as _YTTApi
    from yt_dlp import YoutubeDL as _YoutubeDL

logger = logging.getLogger("aismartbuddy.youtube_client")

# Video ID is always 11 chars of [A-Za-z0-9_-]
_VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")


class _NoOpLogger:
    """Silent yt-dlp logger.

    yt-dlp's `no_warnings=True` is bypassed when a custom `logger` is passed,
    so to truly silence warnings we pass this no-op logger (per the researched
    yt-dlp gotcha in .meridian/api-docs/yt-dlp.md).
    """

    def debug(self, msg: str) -> None: ...
    def info(self, msg: str) -> None: ...
    def warning(self, msg: str) -> None: ...
    def error(self, msg: str) -> None: ...


@dataclass
class YouTubeClient:
    """Shared resources for YouTube metadata + transcript fetching.

    - http_client: shared requests.Session (connection pool reuse)
    - dlp: configured YoutubeDL for fast metadata-only extraction
    - Each tool call constructs its OWN YouTubeTranscriptApi instance around
      the shared http_client. The library is not thread-safe; per-call
      instances partially mitigate future parallel FastMCP dispatch (full
      safety would require per-call http_client too, but under the current
      one-worker-per-call model this is unnecessary overhead).
    """

    http_client: requests.Session
    dlp: _YoutubeDL

    @classmethod
    def create(cls) -> YouTubeClient:
        """Construct a YouTubeClient. Called once from app_lifespan."""
        import requests
        from yt_dlp import YoutubeDL
        from yt_dlp.extractor.youtube import YoutubeIE

        http_client = requests.Session()

        dlp = YoutubeDL(
            params={
                "quiet": True,
                "skip_download": True,
                # Custom logger bypasses no_warnings — use no-op for true silence
                "logger": _NoOpLogger(),
                # Skip format manifest resolution (2-3x faster for metadata-only)
                "extractor_args": {"youtube": {"skip": ["dash", "hls"]}},
            },
            auto_init=False,
        )
        dlp.add_info_extractor(YoutubeIE())

        logger.info("YouTubeClient initialized")
        return cls(http_client=http_client, dlp=dlp)

    def make_ytt_api(self) -> _YTTApi:
        """Create a per-call YouTubeTranscriptApi bound to the shared session.

        Cheap — just wraps the session. Called once per tool invocation
        instead of shared at class level (see class docstring).
        """
        from youtube_transcript_api import YouTubeTranscriptApi

        return YouTubeTranscriptApi(http_client=self.http_client)

    def close(self) -> None:
        """Close underlying resources. Called from app_lifespan on shutdown."""
        try:
            self.http_client.close()
        except Exception:
            logger.exception("Error closing YouTubeClient.http_client")
        try:
            self.dlp.close()
        except Exception:
            logger.exception("Error closing YouTubeClient.dlp")


def parse_video_id(url_or_id: str) -> str:
    """Extract an 11-char YouTube video ID from a URL or passthrough a raw ID.

    Accepts:
    - Raw 11-char ID: "iAA7PTqs4xY"
    - Standard watch URL: "https://www.youtube.com/watch?v=VID"
    - Short URL: "https://youtu.be/VID"
    - Embed URL: "https://www.youtube.com/embed/VID"
    - Shorts URL: "https://www.youtube.com/shorts/VID"

    Raises:
        ValueError: If the input can't be parsed as a video ID.
    """
    if not url_or_id or not isinstance(url_or_id, str):
        raise ValueError("url_or_id must be a non-empty string")

    # Strip whitespace
    s = url_or_id.strip()

    # Raw ID passthrough
    if _VIDEO_ID_RE.match(s):
        return s

    # Parse as URL
    try:
        parsed = urlparse(s)
    except Exception as exc:
        raise ValueError(f"Not a valid URL or video ID: {url_or_id!r}") from exc

    host = (parsed.hostname or "").lower()

    # youtu.be/VID
    if host == "youtu.be":
        vid = parsed.path.lstrip("/")
        if _VIDEO_ID_RE.match(vid):
            return vid

    # youtube.com variants
    if host in ("www.youtube.com", "youtube.com", "m.youtube.com", "music.youtube.com"):
        # watch?v=VID
        q = parse_qs(parsed.query).get("v")
        if q and _VIDEO_ID_RE.match(q[0]):
            return q[0]

        # embed/VID, shorts/VID, v/VID, live/VID
        parts = [p for p in parsed.path.split("/") if p]
        if len(parts) >= 2 and parts[0] in ("embed", "shorts", "v", "live"):
            if _VIDEO_ID_RE.match(parts[1]):
                return parts[1]

    raise ValueError(
        f"Could not extract video ID from {url_or_id!r}. "
        "Expected a raw 11-char ID or a YouTube URL "
        "(watch?v=, youtu.be/, embed/, shorts/)."
    )


# Module-level singleton — set by server.py:app_lifespan, cleared on shutdown.
youtube_client: YouTubeClient | None = None
