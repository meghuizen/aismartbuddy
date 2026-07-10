"""Infrastructure tools: unified multi-backend sessions.

Only `session_create` and `session_destroy` live here. The previous
session_export / session_snapshot / bridge / workflow tools were removed
because they don't directly serve AI-thinking — see the redesign plan.

The unified-session facade exists primarily so SCAFFOLD/ASSESS tools can
opt into `auto_graph` (materialising items[] outputs as KnowledgeNode rows
in the graph backend during the same call).
"""

from __future__ import annotations

from mcp.server.mcpserver import Context

from aismartbuddy.concurrency import run_sync
from aismartbuddy.identity import resolve_identity
from aismartbuddy.tools import get_session_manager

_MODES = {"explore", "diverge", "iterate", "analyze"}
_ENFORCEMENTS = {"advisory", "strict"}


async def session_create(
    backends: list[str] | None = None,
    mode: str = "analyze",
    enforcement: str = "advisory",
    max_node_chars: int = 500,
    auto_graph: bool = False,
    user_id: str | None = None,
    project_id: str | None = None,
    reasoning_intent: str | None = None,
    reasoning_depth: str | None = None,
    output_budget_chars: int | None = None,
    share_from_session_id: str | None = None,
    share_backends: list[str] | None = None,
    ctx: Context | None = None,
) -> str:
    """[INFRA] Create a unified session that hosts one or more backends.

    Use when: you need cross-backend workflows, or want auto_graph available
    without per-call opt-in. Omit entirely to auto-create with think+graph.

    Args:
      backends: list of "think" | "graph" | "sql". Default ["think", "graph"].
      mode: immutable session mode — explore | diverge | iterate | analyze.
      enforcement: advisory (default) or strict phase/mode enforcement.
      max_node_chars: reason_graph node cap for this session.
      auto_graph: when True, all tools in this session materialise items[]
        outputs as KnowledgeNode rows without per-call auto_graph=True.
        Silent skip for tools that don't support auto_graph.
      user_id, project_id: multi-tenant identity. Bearer auth overrides.
      reasoning_intent, reasoning_depth: optional route metadata for quick,
        standard, or deep reasoning.
      output_budget_chars: default maximum for bounded summaries.
      share_from_session_id: source session whose selected mutable backends
        should be reused. The source must have the same stored owner/project.
      share_backends: subset of requested backends to share; other requested
        backends are created fresh.

    Returns: parent session_id and the per-backend child IDs.
    """
    if backends is None:
        backends = ["think", "graph"]
    if mode not in _MODES:
        raise ValueError(f"mode must be one of {sorted(_MODES)}")
    if enforcement not in _ENFORCEMENTS:
        raise ValueError(f"enforcement must be one of {sorted(_ENFORCEMENTS)}")
    if reasoning_depth is not None and reasoning_depth not in {"quick", "standard", "deep"}:
        raise ValueError("reasoning_depth must be quick, standard, or deep")
    if output_budget_chars is not None and not 1_000 <= output_budget_chars <= 500_000:
        raise ValueError("output_budget_chars must be between 1000 and 500000")
    resolved_user, resolved_project = resolve_identity(ctx, user_id, project_id)
    mgr = get_session_manager()
    parent = await run_sync(
        lambda: mgr.create_parent_session(
            backends,
            resolved_user,
            resolved_project,
            mode=mode,
            enforcement=enforcement,
            max_node_chars=max_node_chars,
            auto_graph=auto_graph,
            reasoning_intent=reasoning_intent,
            reasoning_depth=reasoning_depth,
            output_budget_chars=output_budget_chars,
            share_from_session_id=share_from_session_id,
            share_backends=share_backends,
        )
    )
    children_str = ", ".join(
        f"{b}={cid}" for b, cid in parent.children.items()
    )
    auto_graph_str = f" | auto_graph: {parent.auto_graph}" if parent.auto_graph else ""
    route_str = ""
    if parent.reasoning_intent or parent.reasoning_depth:
        route_str = (
            f"\nreasoning_intent: {parent.reasoning_intent or '(unset)'}"
            f" | reasoning_depth: {parent.reasoning_depth or '(unset)'}"
        )
    budget_str = (
        f"\noutput_budget_chars: {parent.output_budget_chars}"
        if parent.output_budget_chars is not None
        else ""
    )
    shared_str = (
        f"\nshared_from: {share_from_session_id}"
        f" | shared_backends: {', '.join(share_backends or backends)}"
        if share_from_session_id
        else ""
    )
    return (
        f"Unified session created.\n"
        f"session_id: {parent.parent_id}\n"
        f"parent_session_id: {parent.parent_id}\n"
        f"user_id: {parent.user_id} | project_id: {parent.project_id}\n"
        f"mode: {parent.mode} | enforcement: {parent.enforcement}"
        f" | max_node_chars: {parent.max_node_chars}{auto_graph_str}\n"
        f"{route_str}{budget_str}{shared_str}\n"
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
    await run_sync(
        lambda: mgr.destroy_parent_session(session_id)
    )
    return f"Destroyed unified session {session_id} and its children."
