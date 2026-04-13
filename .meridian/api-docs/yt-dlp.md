---
summary: Using yt-dlp as a Python library for metadata-only extraction (no download)
read_when: Implementing YouTube metadata tools, before touching YoutubeDL class or handling yt-dlp exceptions
---

# yt-dlp (Python Library)

A feature-rich video metadata extractor and downloader, used here strictly as a **Python library** for metadata-only extraction -- no media downloads.

**Version researched**: 2026.03.17 (PyPI: `yt-dlp==2026.3.17`)
**Python requirement**: 3.10+
**Official docs**: https://github.com/yt-dlp/yt-dlp
**License**: The Unlicense

## Overview

yt-dlp is a fork of youtube-dl with active development. When used as a Python library, the primary class is `YoutubeDL` from the `yt_dlp` package. For metadata extraction, you construct a `YoutubeDL` instance with options that suppress downloading and output, then call `extract_info(url, download=False)` to get a dict of video metadata.

This doc covers ONLY the library API for metadata extraction. It does not cover download management, format selection, post-processing, or CLI usage.

## How It Works

1. `YoutubeDL` is instantiated with an options dict.
2. `extract_info(url, download=False)` is called. This:
   - Iterates registered `InfoExtractor` instances to find one that matches the URL.
   - The matching extractor fetches the webpage, parses it, and returns an `info_dict`.
   - `YoutubeDL.process_ie_result()` post-processes the result (resolves playlists, applies filters).
   - With `download=False`, the download step is skipped entirely.
3. The return value is a dict-like object containing all extracted metadata.

The `extract_info` call is **synchronous and blocking** -- it makes HTTP requests to the target site. For async code, wrap it in `asyncio.to_thread()` or `anyio.to_thread.run_sync()`.

## Setup

```bash
pip install yt-dlp==2026.3.17
# or
uv add yt-dlp==2026.3.17
```

Import:

```python
from yt_dlp import YoutubeDL
```

## API: Constructing YoutubeDL for Metadata-Only Use

### Minimal Options (Metadata Only, Silent)

```python
ydl_opts = {
    'quiet': True,            # Suppress all normal output to stdout
    'no_warnings': True,      # Suppress warning messages to stderr
    'skip_download': True,    # Skip downloading video files (belt-and-suspenders with download=False)
    'noplaylist': True,       # Extract single video even if URL is part of a playlist
}
```

### With Custom Logger (Recommended for Library Use)

When `logger` is set, ALL output (screen, warnings, errors, debug) is routed through the logger instead of stdout/stderr. This is the cleanest way to suppress output in a library context.

```python
import logging

class _QuietLogger:
    """Routes yt-dlp output to Python logging instead of stdout/stderr."""
    def debug(self, msg):
        # yt-dlp sends both debug and info messages to debug().
        # Debug messages are prefixed with '[debug] '.
        if msg.startswith('[debug] '):
            logging.debug(msg)
        else:
            logging.info(msg)

    def warning(self, msg):
        logging.warning(msg)

    def error(self, msg):
        logging.error(msg)


ydl_opts = {
    'logger': _QuietLogger(),
    'skip_download': True,
    'noplaylist': True,
}
```

**How the logger option works (from source):**
- `to_screen()` -> calls `logger.debug(message)` and returns (skips stdout)
- `to_stderr()` -> calls `logger.error(message)` and returns (skips stderr)
- `report_warning()` -> calls `logger.warning(message)` (bypasses `no_warnings` check)
- `write_debug()` -> calls `logger.debug(message)` (only if `verbose=True`)

### Relevant Options Reference

These are the YoutubeDL constructor options relevant to metadata-only extraction (from source docstring):

| Option | Type | Default | Purpose |
|--------|------|---------|---------|
| `quiet` | bool | False | Suppress messages to stdout |
| `no_warnings` | bool | False | Suppress warning messages |
| `verbose` | bool | False | Print debug info (avoid in production) |
| `logger` | object | None | Custom logger with debug/warning/error methods |
| `skip_download` | bool | False | Skip downloading video files |
| `noplaylist` | bool | False | Download single video instead of playlist |
| `ignoreerrors` | bool/str | False (API) | Don't stop on errors. Can be `'only_download'` or `True` |
| `extract_flat` | bool/str | False (API) | Don't resolve nested URLs. `True` = never process, `'in_playlist'` = skip inside playlists |
| `socket_timeout` | int/float | None | Timeout for HTTP requests in seconds |
| `cookiefile` | str | None | Path to Netscape-format cookies.txt file |
| `cookiesfrombrowser` | tuple | None | `('browser_name',)` or `('browser_name', 'profile', 'keyring', 'container')` |
| `http_headers` | dict | None | Custom HTTP headers for all requests |
| `proxy` | str | None | Proxy URL |
| `sleep_interval_requests` | float | None | Seconds to sleep between HTTP requests during extraction |
| `extractor_retries` | int | 3 | Number of retries for known extractor errors |
| `extractor_args` | dict | None | Extractor-specific arguments, e.g. `{'youtube': {'skip': ['dash', 'hls']}}` |
| `ignore_no_formats_error` | bool | False | Don't error when no video formats found (useful for metadata-only on unavailable videos) |
| `allowed_extractors` | list | None | Restrict which extractors can be used, e.g. `['youtube', 'default']` |

## API: extract_info()

### Signature

```python
def extract_info(
    self,
    url: str,
    download: bool = True,
    ie_key: str | None = None,
    extra_info: dict | None = None,
    process: bool = True,
    force_generic_extractor: bool = False,  # Deprecated; use ie_key='Generic'
) -> dict | None:
```

### Parameters

- **url**: The video URL to extract info from.
- **download**: Whether to download the video. **Set to `False` for metadata only.**
- **ie_key**: Force a specific extractor by key (e.g. `'Youtube'`). Usually not needed.
- **process**: Whether to resolve nested URLs/playlists. Must be `True` (default) for most use cases. Setting to `False` returns raw extractor output without post-processing.
- **extra_info**: Internal use only. Do not pass.

### Return Value

Returns a dict (the `info_dict`) or `None` if extraction fails and `ignoreerrors` is set.

**The return value is NOT guaranteed to be JSON-serializable or even a plain dict.** It is dict-like but may contain non-serializable objects. To get a clean, JSON-serializable dict, use:

```python
clean_info = ydl.sanitize_info(info)
```

### Canonical Usage Pattern

```python
from yt_dlp import YoutubeDL

ydl_opts = {
    'quiet': True,
    'no_warnings': True,
    'skip_download': True,
    'noplaylist': True,
}

with YoutubeDL(ydl_opts) as ydl:
    info = ydl.extract_info(
        'https://www.youtube.com/watch?v=dQw4w9WgXcQ',
        download=False,
    )

    title = info.get('title')
    description = info.get('description')
```

**Always use the context manager** (`with` statement). `__exit__` calls `close()`, which saves cookies and closes the HTTP request director. Without this, connections may leak.

## API: sanitize_info()

```python
@staticmethod
def sanitize_info(info_dict, remove_private_keys=False) -> dict:
```

Converts the info_dict to a JSON-serializable dict. Handles:
- `LazyList` -> `list`
- `ImpersonateTarget` -> `str`
- Non-serializable objects -> `repr(obj)`
- Adds `epoch` timestamp and `_version` metadata

With `remove_private_keys=True`, also strips internal keys (`__`-prefixed), `requested_downloads`, `requested_formats`, `entries`, `filepath`, etc.

Use this when you need to serialize the result (logging, caching, returning as JSON).

## Return Dict Structure (info_dict)

### Required Fields (always present for videos)

| Key | Type | Description |
|-----|------|-------------|
| `id` | str | Video identifier (e.g. `'dQw4w9WgXcQ'`) |
| `title` | str | Video title, unescaped. Empty string if no title (not None). |

### Metadata Fields (commonly available for YouTube)

| Key | Type | Description |
|-----|------|-------------|
| `description` | str/None | Full video description |
| `uploader` | str/None | Full name of the video uploader |
| `uploader_id` | str/None | Uploader's account ID |
| `uploader_url` | str/None | URL to uploader's page |
| `channel` | str/None | Channel name (may differ from uploader) |
| `channel_id` | str/None | Channel ID |
| `channel_url` | str/None | Channel URL |
| `channel_follower_count` | int/None | Subscriber count |
| `channel_is_verified` | bool/None | Whether channel is verified |
| `duration` | int/float/None | Length in seconds |
| `view_count` | int/None | View count |
| `like_count` | int/None | Like count |
| `comment_count` | int/None | Comment count |
| `upload_date` | str/None | Upload date as `'YYYYMMDD'` string |
| `timestamp` | int/None | UNIX timestamp of upload |
| `release_timestamp` | int/None | UNIX timestamp of release (if different from upload) |
| `webpage_url` | str | Canonical URL to the video page |
| `thumbnail` | str/None | URL to thumbnail image |
| `thumbnails` | list[dict]/None | List of thumbnail dicts with `url`, `width`, `height`, `preference` |
| `categories` | list[str]/None | Video categories |
| `tags` | list[str]/None | Video tags |
| `age_limit` | int/None | Age restriction in years |
| `is_live` | bool/None | Whether currently a live stream |
| `was_live` | bool/None | Whether was originally a live stream |
| `live_status` | str/None | One of: `'is_live'`, `'is_upcoming'`, `'was_live'`, `'not_live'`, `'post_live'` |
| `availability` | str/None | One of: `'private'`, `'premium_only'`, `'subscriber_only'`, `'needs_auth'`, `'unlisted'`, `'public'` |
| `chapters` | list[dict]/None | List of `{start_time, end_time, title}` dicts |
| `heatmap` | list[dict]/None | List of `{start_time, end_time, value}` dicts |
| `playable_in_embed` | bool/str/None | Whether embeddable |

### Extractor Metadata (added by YoutubeDL)

| Key | Type | Description |
|-----|------|-------------|
| `extractor` | str | Extractor name (e.g. `'youtube'`) |
| `extractor_key` | str | Extractor class key (e.g. `'Youtube'`) |
| `webpage_url_basename` | str | URL basename |
| `webpage_url_domain` | str | URL domain |
| `original_url` | str | The URL as originally passed to `extract_info` |

### Format Fields (present even with download=False)

| Key | Type | Description |
|-----|------|-------------|
| `formats` | list[dict] | All available formats with codec/quality/url info |
| `format` | str | Best format description |
| `format_id` | str | Best format ID |
| `ext` | str | File extension of best format |

### Music/Episode Fields (if applicable)

| Key | Type | Description |
|-----|------|-------------|
| `track` | str/None | Track title |
| `artists` | list[str]/None | Artist names |
| `album` | str/None | Album title |
| `series` | str/None | Series title |
| `season_number` | int/None | Season number |
| `episode` | str/None | Episode title |
| `episode_number` | int/None | Episode number |

## Subtitles and Automatic Captions

Both `subtitles` and `automatic_captions` share the same structure:

```python
{
    'en': [
        {'ext': 'json3', 'url': 'https://...'},
        {'ext': 'srv1', 'url': 'https://...'},
        {'ext': 'srv2', 'url': 'https://...'},
        {'ext': 'srv3', 'url': 'https://...'},
        {'ext': 'ttml', 'url': 'https://...'},
        {'ext': 'vtt', 'url': 'https://...'},
    ],
    'fr': [
        {'ext': 'json3', 'url': 'https://...'},
        ...
    ],
}
```

**Structure**: `dict[str, list[dict]]`
- **Outer key**: Language code (e.g. `'en'`, `'fr'`, `'es'`, `'en-US'`)
- **Value**: List of subtitle format dicts, sorted from lower to higher preference. Each dict has:
  - `ext` (str): Subtitle format extension (`'json3'`, `'srv1'`, `'srv2'`, `'srv3'`, `'ttml'`, `'vtt'`)
  - `url` (str): URL to fetch the subtitle file (present if subtitles are remote)
  - `data` (str, optional): Inline subtitle content (present if subtitles are embedded)
  - `name` (str, optional): Human-readable name/description of the subtitle track

**Key difference**:
- `subtitles`: Manually uploaded/authored captions (fewer languages, higher quality)
- `automatic_captions`: YouTube's auto-generated captions (many languages, lower quality)

**To list available transcript languages**:

```python
info = ydl.extract_info(url, download=False)

# Manual subtitles
manual_langs = list(info.get('subtitles', {}).keys())

# Auto-generated captions
auto_langs = list(info.get('automatic_captions', {}).keys())
```

**To check if a specific language is available**:

```python
has_english_subs = 'en' in info.get('subtitles', {})
has_english_auto = 'en' in info.get('automatic_captions', {})
```

## Exception Hierarchy

All yt-dlp exceptions descend from `YoutubeDLError`. Import from `yt_dlp.utils`.

```
YoutubeDLError                        # Base exception
  +-- ExtractorError                  # Error during info extraction
  |     +-- UnsupportedError          # URL not supported (expected=True)
  |     +-- RegexNotFoundError        # Regex didn't match during extraction
  |     +-- GeoRestrictedError        # Geographic restriction (.countries attribute)
  |     +-- UserNotLive               # Channel not currently live (expected=True)
  +-- DownloadError                   # Download/processing error (.exc_info attribute)
  +-- PostProcessingError             # Post-processor failure
  +-- DownloadCancelled               # Download queue interrupted
  |     +-- ExistingVideoReached      # --break-on-existing triggered
  |     +-- RejectedVideoReached      # --break-match-filter triggered
  |     +-- MaxDownloadsReached       # --max-downloads reached
  +-- ReExtractInfo                   # Video needs re-extraction (internal, usually caught)
  |     +-- ThrottledDownload         # Download speed below threshold
  +-- UnavailableVideoError           # Video not available in requested format
  +-- EntryNotInPlaylist              # Requested entry not in playlist
  +-- SameFileError                   # Multiple files map to same output
  +-- ContentTooShortError            # Downloaded less than expected
```

Additionally, from `yt_dlp.cookies`:
```
YoutubeDLError
  +-- CookieLoadError                 # Failed to load cookies from browser/file
```

### Exceptions Relevant to Metadata Extraction

For metadata-only extraction (`download=False`), these are the exceptions you should handle:

```python
from yt_dlp.utils import DownloadError, ExtractorError

try:
    info = ydl.extract_info(url, download=False)
except ExtractorError as e:
    # Extraction failed (network error, page parsing error, geo-restriction, etc.)
    # e.orig_msg has the original message string
    # e.expected is True if this is a "normal" error (not a bug)
    # e.video_id may be set
    handle_extraction_error(e)
except DownloadError as e:
    # Raised by YoutubeDL.trouble() when ignoreerrors is False (default for API).
    # This wraps other errors. e.exc_info has the original exception info.
    # In practice, ExtractorError is often wrapped into DownloadError.
    handle_download_error(e)
```

**Important**: When `ignoreerrors=False` (the API default), `report_error()` calls `trouble()` which raises `DownloadError`. So most extraction failures surface as `DownloadError`, not `ExtractorError` directly. The `ExtractorError` is caught by `_handle_extraction_exceptions` and re-raised as `DownloadError` via `trouble()`.

**Practical exception handling**:

```python
from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError, ExtractorError, YoutubeDLError

ydl_opts = {
    'quiet': True,
    'no_warnings': True,
    'skip_download': True,
    'noplaylist': True,
}

try:
    with YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
        if info is None:
            # Extractor returned nothing (rare)
            raise ValueError("No info extracted")
except DownloadError as e:
    # Most common exception. Covers: network errors, bot detection,
    # geo-restriction, unsupported URL, private/deleted video, etc.
    error_msg = str(e)
    # Check for specific conditions:
    if 'Sign in to confirm' in error_msg:
        # Bot detection -- needs cookies
        ...
    elif 'is not available' in error_msg or 'Private video' in error_msg:
        # Video unavailable
        ...
    elif 'Unsupported URL' in error_msg:
        # URL not recognized by any extractor
        ...
except YoutubeDLError as e:
    # Catch-all for any other yt-dlp error
    ...
except Exception as e:
    # Non-yt-dlp errors (network timeout, etc.)
    ...
```

## Best Practices

### 1. Always Use Context Manager

```python
# Good
with YoutubeDL(opts) as ydl:
    info = ydl.extract_info(url, download=False)

# Bad -- leaks connections
ydl = YoutubeDL(opts)
info = ydl.extract_info(url, download=False)
# ydl.close() never called if exception occurs
```

### 2. Both download=False AND skip_download=True

Use both for defense in depth. `download=False` is the `extract_info` parameter that skips download. `skip_download=True` is a YoutubeDL option that acts as a second guard.

### 3. Use sanitize_info for Serialization

```python
info = ydl.extract_info(url, download=False)
# info may contain LazyList, ImpersonateTarget, etc.
clean = YoutubeDL.sanitize_info(info)  # Now JSON-safe
```

### 4. Use .get() for All Optional Fields

Only `id` and `title` are guaranteed. Everything else may be `None` or absent:

```python
description = info.get('description')  # Could be None
duration = info.get('duration')        # Could be None
```

### 5. Reuse YoutubeDL Instances

For multiple extractions, create one instance and reuse it:

```python
with YoutubeDL(opts) as ydl:
    for url in urls:
        info = ydl.extract_info(url, download=False)
```

This reuses the HTTP session and cookies across requests.

### 6. Set Socket Timeout

For MCP tool use, always set a timeout to prevent hanging:

```python
ydl_opts = {
    'socket_timeout': 30,  # seconds
    ...
}
```

## Gotchas

### YouTube Bot Detection (Critical, as of 2026)

YouTube increasingly blocks requests from datacenter IPs and automated tools. Symptoms:
- `DownloadError` with message containing "Sign in to confirm you're not a bot"
- HTTP 429 errors

**Mitigation approaches** (in order of preference):

1. **Cookies from browser** (API option):
   ```python
   ydl_opts = {
       'cookiesfrombrowser': ('firefox',),  # tuple, not string!
       # Supported browsers: 'brave', 'chrome', 'chromium', 'edge',
       # 'firefox', 'opera', 'safari', 'vivaldi', 'whale'
   }
   ```
   Note: Chrome cookie extraction is broken on Windows since Chrome 127+ (app-bound encryption). **Firefox is the most reliable** as it stores cookies in a plain SQLite database.

2. **Cookies from file** (API option):
   ```python
   ydl_opts = {
       'cookiefile': '/path/to/cookies.txt',  # Netscape format
       # First line must be: # Netscape HTTP Cookie File
       # or: # HTTP Cookie File
   }
   ```

3. **Custom headers** (less effective, may not bypass bot detection):
   ```python
   ydl_opts = {
       'http_headers': {
           'User-Agent': 'Mozilla/5.0 ...',
           'Accept-Language': 'en-US,en;q=0.9',
       },
   }
   ```

**Cookie expiration**: YouTube cookies expire roughly every 2 weeks. Automated cookie refresh requires re-exporting from a browser.

### cookiesfrombrowser Must Be a Tuple

The `cookiesfrombrowser` option takes a tuple, not a string. The tuple format is:
`(browser_name,)` or `(browser_name, profile, keyring, container)`

```python
# Correct
{'cookiesfrombrowser': ('firefox',)}

# Wrong -- will cause errors
{'cookiesfrombrowser': 'firefox'}
```

### extract_info Returns None on Soft Failure

If `ignoreerrors` is set and an error occurs, `extract_info` returns `None` instead of raising. Always check:

```python
info = ydl.extract_info(url, download=False)
if info is None:
    # Handle failure
```

### info_dict Is Not a Plain Dict

The return value from `extract_info` is dict-like but may contain non-serializable objects (LazyList, ImpersonateTarget, etc.). Do NOT pass it directly to `json.dumps()`. Use `sanitize_info()` first.

### yt-dlp Prints to stdout/stderr by Default

Without `quiet=True` or a custom `logger`, YoutubeDL prints extraction progress, warnings, and other messages directly to stdout/stderr. This will pollute MCP tool output. Always suppress output for library use.

### Blocking I/O

`extract_info()` is synchronous and makes HTTP requests. In an async context (like MCP tools using anyio), you MUST run it in a thread:

```python
import anyio

info = await anyio.to_thread.run_sync(
    lambda: ydl.extract_info(url, download=False)
)
```

### The logger Bypasses no_warnings

When you set the `logger` option, warnings are sent to `logger.warning()` regardless of `no_warnings`. The `no_warnings` option only suppresses warnings when there is no custom logger. If you want to suppress warnings with a logger, make the logger's `warning()` method a no-op.

### Rate Limiting Behavior

yt-dlp does NOT have built-in rate limiting for metadata extraction by default. Each `extract_info` call makes several HTTP requests to YouTube. If you call it in a tight loop, YouTube may throttle or block you.

To add delays between requests during extraction:
```python
ydl_opts = {
    'sleep_interval_requests': 1.0,  # seconds between HTTP requests
}
```

YouTube reportedly throttles HTTP requests with chunks > 10MB, but this mainly affects downloads, not metadata extraction.

### Private/Age-Restricted Videos

- **Private videos**: Return `DownloadError` with "Private video" message. Cookies from an account with access are required.
- **Age-restricted videos**: Require cookies from an account that has confirmed age.
- Use `ignore_no_formats_error=True` to still get metadata even if no playable formats are found.

### YouTube Extractor Arguments

You can pass YouTube-specific arguments to skip unnecessary work:

```python
ydl_opts = {
    'extractor_args': {
        'youtube': {
            'skip': ['dash', 'hls'],     # Skip format manifests (faster for metadata-only)
            'player_skip': ['configs'],   # Skip player config fetching
        }
    }
}
```

This can speed up metadata extraction by avoiding format resolution, though it may result in an empty `formats` list.

## Complete Example: MCP Tool Pattern

```python
from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError, YoutubeDLError
import logging

logger = logging.getLogger(__name__)


class _SilentLogger:
    def debug(self, msg): pass
    def warning(self, msg): pass
    def error(self, msg): logger.error(f"yt-dlp: {msg}")


_YDL_OPTS = {
    'logger': _SilentLogger(),
    'skip_download': True,
    'noplaylist': True,
    'socket_timeout': 30,
    'extractor_args': {
        'youtube': {
            'skip': ['dash', 'hls'],
        }
    },
}


def get_video_metadata(url: str) -> dict:
    """Extract video metadata without downloading.

    Returns dict with title, description, and other metadata.
    Raises DownloadError on failure.
    """
    with YoutubeDL(_YDL_OPTS) as ydl:
        info = ydl.extract_info(url, download=False)
        if info is None:
            raise ValueError(f"Failed to extract info from {url}")

        return {
            'id': info['id'],
            'title': info['title'],
            'description': info.get('description'),
            'uploader': info.get('uploader'),
            'channel': info.get('channel'),
            'channel_id': info.get('channel_id'),
            'duration': info.get('duration'),
            'view_count': info.get('view_count'),
            'like_count': info.get('like_count'),
            'upload_date': info.get('upload_date'),
            'webpage_url': info.get('webpage_url'),
            'thumbnail': info.get('thumbnail'),
            'tags': info.get('tags'),
            'categories': info.get('categories'),
            'is_live': info.get('is_live'),
            'availability': info.get('availability'),
            'subtitles_languages': list(info.get('subtitles', {}).keys()),
            'auto_captions_languages': list(info.get('automatic_captions', {}).keys()),
        }
```

### Async Wrapper for MCP

```python
import anyio

async def get_video_metadata_async(url: str) -> dict:
    return await anyio.to_thread.run_sync(lambda: get_video_metadata(url))
```

## Links

- **GitHub**: https://github.com/yt-dlp/yt-dlp
- **PyPI**: https://pypi.org/project/yt-dlp/
- **Source: YoutubeDL.py** (options docstring, extract_info, sanitize_info): https://github.com/yt-dlp/yt-dlp/blob/master/yt_dlp/YoutubeDL.py
- **Source: extractor/common.py** (info_dict field definitions): https://github.com/yt-dlp/yt-dlp/blob/master/yt_dlp/extractor/common.py
- **Source: utils/_utils.py** (exception classes): https://github.com/yt-dlp/yt-dlp/blob/master/yt_dlp/utils/_utils.py
- **FAQ / Cookies**: https://github.com/yt-dlp/yt-dlp/wiki/FAQ
