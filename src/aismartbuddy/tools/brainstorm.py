"""brainstorm — DIVERGE mode tool. Anti-forcing-function: demands quantity.

Forces a minimum idea count BEFORE any evaluation/convergence. No conclusion
field. No reasoning field. Just ideas + their sparks. Cluster suggestions
are auto-extracted via simple keyword grouping.
"""

from __future__ import annotations

import re
import uuid

from mcp.server.mcpserver import Context as _MCPContext

from aismartbuddy.concurrency import run_sync
from aismartbuddy.engines.thinking_engine import ThinkingEngine
from aismartbuddy.tools.think import _get_or_create_think_session

_STYLES = frozenset({"wild", "constrained", "analogical", "inversion"})

# Tiny stopword list — keeps clustering fast and dependency-free.
_STOPWORDS = frozenset({
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
    "of", "to", "in", "on", "at", "by", "for", "with", "as", "from",
    "and", "or", "but", "not", "no", "yes", "if", "then", "than",
    "this", "that", "these", "those", "it", "its", "they", "them",
    "i", "you", "we", "he", "she", "his", "her", "their", "our",
    "do", "does", "did", "have", "has", "had", "will", "would", "should",
    "can", "could", "may", "might", "must", "shall",
    "what", "when", "where", "why", "how", "who",
    "all", "any", "some", "more", "most", "less",
    "use", "using", "make", "made", "get", "got", "go", "going",
})


def _engine(info) -> ThinkingEngine:
    assert isinstance(info.engine, ThinkingEngine)
    return info.engine


def _tokenize(text: str) -> set[str]:
    """Return content-word tokens (lowercase, no stopwords, ≥4 chars)."""
    tokens = re.findall(r"[A-Za-z][A-Za-z0-9_-]+", text.lower())
    return {t for t in tokens if len(t) >= 4 and t not in _STOPWORDS}


def _cluster_ideas(
    ideas: list[dict], min_shared_tokens: int = 2,
) -> list[dict]:
    """Group ideas sharing ≥min_shared_tokens content tokens.

    Returns a list of cluster dicts: {keywords: [...], idea_indices: [...]}.
    Greedy: each idea joins the first cluster it overlaps with; otherwise
    starts a new one.
    """
    tokens_per_idea = [_tokenize(i.get("idea", "")) for i in ideas]
    clusters: list[dict] = []
    for idx, toks in enumerate(tokens_per_idea):
        if not toks:
            continue
        joined = False
        for c in clusters:
            if len(c["_tokens"] & toks) >= min_shared_tokens:
                c["_tokens"] |= toks
                c["idea_indices"].append(idx)
                joined = True
                break
        if not joined:
            clusters.append({
                "_tokens": set(toks),
                "idea_indices": [idx],
            })
    # Project to public form: top-3 keywords per cluster
    out: list[dict] = []
    for c in clusters:
        if len(c["idea_indices"]) < 2:
            continue  # Singletons aren't useful clusters
        keywords = sorted(c["_tokens"])[:3]
        out.append({
            "keywords": keywords,
            "idea_indices": c["idea_indices"],
            "size": len(c["idea_indices"]),
        })
    out.sort(key=lambda c: (-c["size"], c["keywords"]))
    return out


async def brainstorm(
    topic: str,
    ideas: list[dict],
    min_ideas: int = 10,
    constraints: list[str] | None = None,
    style: str = "wild",
    session_id: str | None = None,
    ctx: _MCPContext | None = None,
) -> str:
    """[ELABORATE] Generate quantity and diversity of ideas BEFORE evaluation.

    REJECTS submissions below min_ideas. Forces expansion. There is NO
    conclusion field. NO reasoning field. NO confidence. Just ideas + the
    spark that triggered each. The forcing function inverts the usual
    pattern — it makes premature convergence impossible.

    Cluster suggestions are auto-extracted via simple keyword grouping
    (Jaccard-like overlap on content words). Useful for the next phase
    where you select the best ideas for development.

    Args:
        topic: What you're brainstorming about.
        ideas: List of dicts. Each: {idea: str, spark: str}.
        min_ideas: Server REJECTS submissions below this threshold (default 10).
            Quantity before quality — that's the rule.
        constraints: Optional list of boundaries (NOT conclusions).
        style: One of: wild, constrained, analogical, inversion.
        session_id: Thinking session ID. Omit to auto-create.

    Returns:
        Compact summary with idea_ids and detected cluster suggestions.
    """
    if not topic:
        raise ValueError("brainstorm requires 'topic'")
    if style not in _STYLES:
        raise ValueError(
            f"style must be one of {sorted(_STYLES)}, got {style!r}"
        )
    if not isinstance(ideas, list):
        raise ValueError("ideas must be a list")
    if len(ideas) < min_ideas:
        raise ValueError(
            f"brainstorm received {len(ideas)} ideas but min_ideas={min_ideas}. "
            "Generate more ideas before converging — quantity before quality."
        )
    for i, item in enumerate(ideas):
        if not isinstance(item, dict):
            raise ValueError(f"ideas[{i}] must be a dict")
        if not item.get("idea"):
            raise ValueError(f"ideas[{i}] missing 'idea'")
        if not item.get("spark"):
            raise ValueError(
                f"ideas[{i}] missing 'spark' — what triggered this idea?"
            )

    _, info = await run_sync(
        lambda: _get_or_create_think_session(session_id, ctx)
    )
    engine = _engine(info)

    # Store as a single ThoughtNode tree under a fresh root, with each idea
    # as a child. Reuses the existing thought-graph plumbing — no new
    # storage table required. Brainstorm-specific metadata identifies them.
    brainstorm_id = uuid.uuid4().hex[:10]
    idea_ids: list[str] = []
    from aismartbuddy.engines.thinking_engine import ThoughtNode

    with engine.state_lock:
        root_node = ThoughtNode(
            id=brainstorm_id,
            tree_id=brainstorm_id,
            content=f"BRAINSTORM ({style}): {topic}",
            action="branch",
            depth=0,
            metadata={
                "kind": "brainstorm",
                "topic": topic,
                "style": style,
                "constraints": list(constraints or []),
                "min_ideas": min_ideas,
            },
        )
        # Evict BEFORE inserting so new nodes aren't victims (matches
        # add_node / add_node_with_children eviction contract).
        engine._cleanup_graph_memory()
        engine.thought_nodes[brainstorm_id] = root_node
        engine.thought_trees[brainstorm_id] = brainstorm_id
        for item in ideas:
            iid = uuid.uuid4().hex[:10]
            node = ThoughtNode(
                id=iid,
                tree_id=brainstorm_id,
                content=item["idea"],
                action="think",
                parent_id=brainstorm_id,
                depth=1,
                metadata={
                    "kind": "brainstorm_idea",
                    "spark": item["spark"],
                    "style": style,
                },
            )
            engine.thought_nodes[iid] = node
            root_node.children.append(iid)
            idea_ids.append(iid)

    clusters = _cluster_ideas(ideas)

    parts = [
        f"Session: {info.session_id} | Brainstorm: {brainstorm_id}"
        f" | Style: {style}",
        f"Topic: {topic[:80]}",
        f"Ideas: {len(idea_ids)} | Min required: {min_ideas}",
    ]
    if clusters:
        parts.append(f"Cluster suggestions: {len(clusters)}")
        for i, c in enumerate(clusters):
            parts.append(
                f"  cluster_{i}: keywords={c['keywords']}, "
                f"size={c['size']}, ideas={c['idea_indices']}"
            )
    else:
        parts.append("Cluster suggestions: none (low keyword overlap)")
    parts.append("Status: brainstormed")
    return "\n".join(parts)
