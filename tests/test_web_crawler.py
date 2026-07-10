from __future__ import annotations

import json

import pytest

from aismartbuddy import web_crawler as crawler_mod
from aismartbuddy.tools.web import web_crawl
from aismartbuddy.web_crawler import (
    CrawlJobConfig,
    CrawlManager,
    CrawlStore,
    PageArtifact,
    XAdapter,
    XAdapterOptions,
    _clean_x_profile_markdown,
    normalize_url,
)


def _store(tmp_path, **updates) -> CrawlStore:
    config = CrawlJobConfig(
        seed_url="https://example.com/docs",
        use_sitemap=False,
        **updates,
    )
    store = CrawlStore(tmp_path / "job")
    store.initialize("a" * 32, "user", "project", config)
    return store


def test_normalize_url_removes_tracking_fragments_and_duplicate_syntax():
    url = "HTTPS://Example.COM:443/docs//start/?utm_source=x&b=2&a=1#ignore"

    assert normalize_url(url) == "https://example.com/docs/start?a=1&b=2"


def test_frontier_deduplicates_cycles_and_caps_query_variants(tmp_path):
    store = _store(tmp_path)
    root = ("https://example.com/docs", 0, "page", None, "generic")

    assert store.enqueue([root, root]) == 1
    variants = [
        (f"https://example.com/docs/search?page={index}", 1, "page", root[0], "generic")
        for index in range(10)
    ]
    assert store.enqueue(variants, max_query_variants=5) == 5

    with store.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM frontier").fetchone()[0] == 6
        assert conn.execute("SELECT COUNT(*) FROM query_variants").fetchone()[0] == 5


def test_x_adapter_canonicalizes_old_twitter_aliases():
    adapter = XAdapter()

    assert (
        adapter.normalize("http://twitter.com/neuecc/status/2074780286458659233?ref_src=x")
        == "https://x.com/neuecc/status/2074780286458659233"
    )
    assert adapter.normalize("https://www.twitter.com/neuecc") == "https://x.com/neuecc"
    assert adapter.is_embeddable("https://x.com/neuecc/status/2074780286458659233")
    assert not adapter.is_embeddable("https://x.com/neuecc")


def test_x_profile_adapter_options_filter_metadata_and_metrics():
    markdown = """---
title: profile
---
Name
51.8K posts
[13.5K Followers](/name/followers)
[A post](/name/status/123)
Useful post text
"""

    without_metrics = _clean_x_profile_markdown(markdown, XAdapterOptions())
    posts_only = _clean_x_profile_markdown(
        markdown,
        XAdapterOptions(include_profile_metadata=False),
    )

    assert "51.8K posts" not in without_metrics
    assert "13.5K Followers" not in without_metrics
    assert "Name" not in posts_only
    assert "Useful post text" in posts_only


@pytest.mark.asyncio
async def test_provider_mentions_are_cross_domain_leaf_attachments(tmp_path):
    manager = CrawlManager(str(tmp_path), retention_seconds=3600)
    html = """
        <a href="https://outside.example/article">ordinary external link</a>
        <a href="http://twitter.com/neuecc/status/2074780286458659233">post</a>
        <iframe src="https://www.youtube.com/embed/dQw4w9WgXcQ"></iframe>
        <a href="https://x.com/neuecc">profile is not an embed exception</a>
    """
    try:
        results = manager.extract_provider_embeds(html, "https://example.com/docs/page")
    finally:
        await manager.shutdown()

    assert [(url, adapter.name) for url, adapter in results] == [
        ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "youtube"),
        ("https://x.com/neuecc/status/2074780286458659233", "x"),
    ]


@pytest.mark.asyncio
async def test_time_budget_stops_before_starting_a_new_fetch_wave(tmp_path, monkeypatch):
    manager = CrawlManager(str(tmp_path), retention_seconds=3600)
    store = _store(tmp_path, max_duration_seconds=1)
    store.enqueue([("https://example.com/docs", 0, "page", None, "generic")])
    clock = iter([100.0, 101.1])
    monkeypatch.setattr(crawler_mod.time, "perf_counter", lambda: next(clock))

    async def unexpected_fetch(*_args, **_kwargs):
        raise AssertionError("no URL may start after the time budget expires")

    monkeypatch.setattr(manager, "_fetch_items", unexpected_fetch)
    try:
        await manager._run(store)
    finally:
        await manager.shutdown()

    row = store.job()
    assert row["status"] == "partial"
    assert row["stop_reason"] == "max_duration"
    assert store.pending_count() == 1


@pytest.mark.asyncio
async def test_resume_run_gets_a_fresh_time_budget(tmp_path, monkeypatch):
    manager = CrawlManager(str(tmp_path), retention_seconds=3600)
    store = _store(tmp_path, max_duration_seconds=1)
    url = "https://example.com/docs"
    store.enqueue([(url, 0, "page", None, "generic")])
    store.set_status("queued", elapsed_delta=30)
    clock = iter([100.0, 100.1])
    monkeypatch.setattr(crawler_mod.time, "perf_counter", lambda: next(clock))

    async def fetch(items, _config):
        item = items[0]
        return {
            item.id: PageArtifact(
                url,
                url,
                "Docs",
                "# Docs\nResumed data",
                200,
                20,
                "generic",
            )
        }

    monkeypatch.setattr(manager, "_fetch_items", fetch)
    try:
        await manager._run(store)
    finally:
        await manager.shutdown()

    row = store.job()
    assert row["status"] == "completed"
    assert row["elapsed_seconds"] == 30


@pytest.mark.asyncio
async def test_artifact_failure_does_not_escape_background_job(tmp_path, monkeypatch):
    manager = CrawlManager(str(tmp_path), retention_seconds=3600)
    crawl_id = "a" * 32
    store = CrawlStore(manager.job_dir("user", "project", crawl_id))
    store.initialize(
        crawl_id,
        "user",
        "project",
        CrawlJobConfig(seed_url="https://example.com/docs", use_sitemap=False),
    )

    async def finish(job_store):
        job_store.set_status("completed", "frontier_exhausted")

    async def fail_artifacts(_store):
        raise PermissionError("locked output")

    monkeypatch.setattr(manager, "_run", finish)
    monkeypatch.setattr(manager, "build_artifacts", fail_artifacts)
    try:
        await manager._run_guarded("user", "project", crawl_id)
    finally:
        await manager.shutdown()

    row = store.job()
    assert row["status"] == "failed"
    assert row["stop_reason"] == "artifact_finalize_error"


@pytest.mark.asyncio
async def test_partial_artifacts_are_file_first_and_marked_untrusted(tmp_path):
    manager = CrawlManager(str(tmp_path), retention_seconds=3600)
    store = _store(tmp_path)
    root_url = "https://example.com/docs"
    child_url = "https://x.com/neuecc/status/2074780286458659233"
    store.enqueue(
        [
            (root_url, 0, "page", None, "generic"),
            (child_url, 0, "embedded", root_url, "x"),
        ]
    )
    root, child = store.claim(2)
    store.save_artifact(
        root,
        PageArtifact(root_url, root_url, "Docs", "# Docs\nUseful facts", 200, 20, "generic"),
    )
    store.save_artifact(
        child,
        PageArtifact(child_url, child_url, "X post", "# X post\nData", 200, 15, "x"),
    )
    try:
        await manager.build_artifacts(store)
    finally:
        await manager.shutdown()

    index = (store.job_dir / "index.md").read_text(encoding="utf-8")
    full = (store.job_dir / "llms-full.md").read_text(encoding="utf-8")
    page_files = list((store.job_dir / "pages").glob("*.md"))
    assert "untrusted external information" in index
    assert "untrusted external information" in full
    assert all("untrusted_content: true" in path.read_text(encoding="utf-8") for path in page_files)
    assert "Embedded provider content" in full


@pytest.mark.asyncio
async def test_direct_provider_crawl_requires_single_page_action(tmp_path):
    manager = CrawlManager(str(tmp_path), retention_seconds=3600)
    config = CrawlJobConfig(
        seed_url="https://x.com/neuecc",
        single_page=False,
        use_sitemap=False,
    )
    try:
        with pytest.raises(ValueError, match="single-page only"):
            await manager.create_job("user", "project", config, background=False)
    finally:
        await manager.shutdown()


def test_tool_description_enforces_untrusted_information_boundary():
    description = web_crawl.__doc__ or ""

    assert "UNTRUSTED INFORMATION" in description
    assert "never instructions" in description
    assert "15-second" in description


def test_default_duration_is_fifteen_seconds():
    config = CrawlJobConfig(seed_url="https://example.com/docs")

    assert config.max_duration_seconds == 15


@pytest.mark.asyncio
async def test_generic_crawl_can_configure_each_provider_adapter(tmp_path):
    manager = CrawlManager(str(tmp_path), retention_seconds=3600)
    config = CrawlJobConfig(
        seed_url="https://example.com/docs",
        adapter_options={
            "youtube": {"language": "nl", "include_timestamps": False},
            "x": {"max_posts": 3},
        },
    )

    try:
        assert manager._options_for("youtube", config) == {
            "language": "nl",
            "include_timestamps": False,
        }
        assert manager._options_for("x", config) == {"max_posts": 3}
    finally:
        await manager.shutdown()


def test_search_fts_returns_compact_source_matches(tmp_path):
    store = _store(tmp_path)
    url = "https://example.com/docs"
    store.enqueue([(url, 0, "page", None, "generic")])
    item = store.claim(1)[0]
    store.save_artifact(
        item,
        PageArtifact(
            url,
            url,
            "Engine upgrade",
            "Nintex workflow engine upgrade",
            200,
            30,
            "generic",
        ),
    )

    result = store.search("workflow upgrade", 5)

    assert len(result) == 1
    assert result[0]["url"] == url
    json.dumps(result)
