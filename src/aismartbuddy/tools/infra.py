"""Infrastructure tools: unified multi-backend sessions.

Only `session_create` and `session_destroy` live here. The previous
session_export / session_snapshot / bridge / workflow tools were removed
because they don't directly serve AI-thinking — see the redesign plan.

The unified-session facade exists primarily so SCAFFOLD/ASSESS tools can
opt into `auto_graph` (materialising items[] outputs as KnowledgeNode rows
in the graph backend during the same call).
"""

from __future__ import annotations

import anyio
from mcp.server.fastmcp import Context

from aismartbuddy.identity import resolve_identity
from aismartbuddy.tools import get_session_manager

_MODES = {"explore", "diverge", "iterate", "analyze"}
_ENFORCEMENTS = {"advisory", "strict"}


async def session_create(
    backends: list[str] | None = None,
    mode: str = "analyze",
    enforcement: str = "advisory",
    max_node_chars: int = 500,
    user_id: str | None = None,
    project_id: str | None = None,
    ctx: Context | None = None,
) -> str:
    """[INFRA] Create a unified session that hosts one or more backends.

    Use when: you need cross-backend workflows (e.g., scaffold thoughts then
    auto_graph them into a knowledge graph). For single-backend use, the
    individual *_create_session tools are simpler.

    Do NOT use when: a single backend session is sufficient.

    Args:
      backends: list of "think" | "graph" | "sql". Default ["think"].
      mode: immutable session mode — explore | diverge | iterate | analyze.
      enforcement: advisory (default) or strict phase/mode enforcement.
      max_node_chars: reason_graph node cap for this session.
      user_id, project_id: multi-tenant identity. Bearer auth overrides.

    Returns: parent session_id and the per-backend child IDs.
    """
    if backends is None:
        backends = ["think"]
    if mode not in _MODES:
        raise ValueError(f"mode must be one of {sorted(_MODES)}")
    if enforcement not in _ENFORCEMENTS:
        raise ValueError(f"enforcement must be one of {sorted(_ENFORCEMENTS)}")
    resolved_user, resolved_project = resolve_identity(ctx, user_id, project_id)
    mgr = get_session_manager()
    parent = await anyio.to_thread.run_sync(
        lambda: mgr.create_parent_session(
            backends,
            resolved_user,
            resolved_project,
            mode=mode,
            enforcement=enforcement,
            max_node_chars=max_node_chars,
        )
    )
    children_str = ", ".join(
        f"{b}={cid}" for b, cid in parent.children.items()
    )
    return (
        f"Unified session created.\n"
        f"session_id: {parent.parent_id}\n"
        f"parent_session_id: {parent.parent_id}\n"
        f"user_id: {parent.user_id} | project_id: {parent.project_id}\n"
        f"mode: {parent.mode} | enforcement: {parent.enforcement}"
        f" | max_node_chars: {parent.max_node_chars}\n"
        f"backends: {', '.join(parent.children.keys())}\n"
        f"children: {children_str}\n"
        f"child_session_ids: {children_str}"
    )


async def session_destroy(session_id: str) -> str:
    """[INFRA] Destroy a unified session and all its backend children.

    For single-backend sessions, use the backend-specific destroy tool
    (sql_destroy_session, graph_destroy_session, think_destroy_session).

    Args:
      session_id: parent session_id from session_create.

    Returns: confirmation string.
    """
    mgr = get_session_manager()
    await anyio.to_thread.run_sync(
        lambda: mgr.destroy_parent_session(session_id)
    )
    return f"Destroyed unified session {session_id} and its children."
