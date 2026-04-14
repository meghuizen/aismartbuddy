"""think_refs_query — find all records that reference a given entity_id.

Lets the AI compose across tools by ID rather than text-search. Queries
the `refs` list on ThoughtNode / HolonNode / EvaluationRecord.
"""

from __future__ import annotations

from mcp.server.fastmcp import Context as _MCPContext

from aismartbuddy.engines.thinking_engine import ThinkingEngine
from aismartbuddy.tools.think import _engine, _get_or_create_think_session


async def think_refs_query(
    entity_id: str,
    session_id: str | None = None,
    ctx: _MCPContext | None = None,
) -> str:
    """[ELABORATE] Find all records whose refs list contains entity_id.

    Use when: you've previously stored an item id (from think_model(items=[]),
    think_science(items=[]), holon_create, etc.) and want to find every later
    record that mentioned it via its `refs` list. Lets analyses compose by ID,
    not text-search.
    Do NOT use when: you can directly query holon_query / think_summarize.

    Args:
      entity_id: the id to look up across refs lists.
      session_id: omit to auto-create.

    Returns: per-type counts and matching record IDs (compact).
    """
    if not entity_id:
        raise ValueError("entity_id is required")
    _, info = _get_or_create_think_session(session_id, ctx)
    engine: ThinkingEngine = _engine(info)

    matches: dict[str, list[str]] = {
        "thought_nodes": [],
        "holon_nodes": [],
        "evaluations": [],
    }
    with engine.state_lock:
        for nid, node in engine.thought_nodes.items():
            if entity_id in node.refs:
                matches["thought_nodes"].append(nid)
        for hid, holon in engine.holon_nodes.items():
            if entity_id in holon.refs:
                matches["holon_nodes"].append(hid)
        for eid, ev in engine.evaluations.items():
            if entity_id in ev.refs:
                matches["evaluations"].append(eid)

    total = sum(len(v) for v in matches.values())
    parts = [
        f"Session: {info.session_id} | refs query: {entity_id}",
        f"Total refs: {total}",
    ]
    for kind, ids in matches.items():
        if ids:
            parts.append(f"{kind} ({len(ids)}): {', '.join(ids)}")
    if total == 0:
        parts.append("No records reference this id.")
    return "\n".join(parts)
