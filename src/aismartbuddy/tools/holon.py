"""Holonic thinking tools for multi-level domain modeling.

Tools for building and navigating holarchies where every entity is
simultaneously a whole (self-contained) and a part (embedded in a
larger system). Supports multi-membership: a holon can participate
in multiple holarchies with different parents and roles.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import anyio
from mcp.server.fastmcp import Context as _MCPContext

from aismartbuddy import config as cfg
from aismartbuddy.engines.thinking_engine import HolonNode

if TYPE_CHECKING:
    from aismartbuddy.engines.thinking_engine import ThinkingEngine
    from aismartbuddy.session import SessionInfo

from aismartbuddy.tools import effective_session_id, resolve_auto_graph, size_guarded
from aismartbuddy.tools.think import (
    _engine,
    _get_or_create_think_session,
    _materialize_subject_rule_bindings,
    _require_think_session,
    _rule_bindings_from_profile_ids,
    _validate_enum,
)

# ── Display truncation helpers ───────────────────────────────
# Runtime-configurable via RuntimeConfig.holon_display_truncate_{chars,long}
# (CLI: --holon-truncate-chars / --holon-truncate-long). Defaults: 60 / 80.


def _trunc(s: str) -> str:
    """Truncate to display chars (default 60) for inline context/description."""
    return s[: max(1, cfg.runtime_config.holon_truncate_chars)]


def _trunc_long(s: str) -> str:
    """Truncate to long display chars (default 80) for primary content."""
    return s[: max(1, cfg.runtime_config.holon_truncate_long)]


# ── Validation constants ─────────────────────────────────────

_HOLON_UPDATE_ACTIONS = frozenset(
    {
        "context",
        "rules",
        "description",
        "properties",
        "projection",
        "join_holarchy",
        "add_lens",
    }
)

_HOLON_VIEW_ACTIONS = frozenset(
    {
        "zoom_in",
        "zoom_out",
        "sideways",
        "cross_level",
        "memberships",
    }
)

_HOLON_ANALYZE_ACTIONS = frozenset(
    {
        "tensions",
        "emergence",
        "propagate_up",
        "propagate_down",
        "coherence",
        "bridge",
        "lens",
        "feedback_loops",
        "leverage_points",
    }
)

_PROPAGATION_UP_TYPES = frozenset(
    {
        "inform",
        "constrain",
        "transform",
    }
)

_PROPAGATION_DOWN_TYPES = frozenset(
    {
        "constrain",
        "enable",
        "restructure",
    }
)

_HOLON_QUERY_RESOLUTIONS = frozenset(
    {
        "local",
        "subtree",
        "holarchy",
    }
)


# ── Helpers ──────────────────────────────────────────────────


def _get_membership(node: HolonNode, holarchy_id: str) -> dict | None:
    """Find a specific membership entry on a holon."""
    for m in node.memberships:
        if m["holarchy_id"] == holarchy_id:
            return m
    return None


def _resolve_holarchy(node: HolonNode, holarchy_id: str | None) -> str | None:
    """Resolve which holarchy to use. If None and only one membership, use it."""
    if holarchy_id:
        if _get_membership(node, holarchy_id) is None:
            raise ValueError(f"Holon '{node.id}' has no membership in holarchy '{holarchy_id}'")
        return holarchy_id
    if len(node.memberships) == 1:
        return node.memberships[0]["holarchy_id"]
    return None


def _holon_summary_line(node: HolonNode, holarchy_id: str) -> str:
    """One-line summary of a holon in a specific holarchy."""
    m = _get_membership(node, holarchy_id)
    role = m["role_in_parent"][:40] if m else ""
    proj = node.projections.get(holarchy_id, "")
    stale = " [STALE]" if holarchy_id in node.stale_projections else ""
    parts = [f"{node.name}"]
    if role:
        parts.append(f"role={role}")
    if proj:
        parts.append(f"proj={proj[:40]}{stale}")
    elif stale:
        parts.append(f"proj=?{stale}")
    return " | ".join(parts)


# ── Tool: holon_create ───────────────────────────────────────


async def holon_create(
    name: str = "",
    description: str = "",
    session_id: str | None = None,
    holarchy_id: str | None = None,
    parent_id: str | None = None,
    role_in_parent: str = "",
    context: str = "",
    rules: list[str] | None = None,
    properties: list[str] | None = None,
    projection: str = "",
    holons: list[dict] | None = None,
    auto_graph: bool = False,
    rule_profile_ids: list[str] | None = None,
    ctx: _MCPContext | None = None,
) -> str:
    """[ELABORATE] Create a holon — an entity that is both a whole and a part.
    Returns: created holon IDs, holarchy IDs, and parent-child edge summaries (text format).

    Single mode: omit `holons`. Provide name + description (+ optional
    parent_id, holarchy_id, role_in_parent, context, rules, properties,
    projection). If parent_id is None, creates a new holarchy with this
    holon as root.

    Batch mode: pass `holons=[...]` to create N holons atomically. All-or-nothing:
    validation failures abort the whole batch.

    holons item schema (all fields):
      ref (required)         - temp reference for resolving parent_ref within same batch
      name (required)        - human-readable label
      description (required) - what this holon IS
      parent_ref?            - ref or existing holon_id of parent
      holarchy_id?           - which holarchy; auto-created if this is root
      role_in_parent?        - what this holon DOES as a part
      context?               - working state/knowledge at this level
      rules?                 - internal constraints (list of strings)
      properties?            - observable properties (list of strings)
      projection?            - what this holon exposes upward in the holarchy

    Pass auto_graph=True (requires session_create(backends=['think','graph']))
    to materialise each holon as a KnowledgeNode with PartOf edges in one
    round-trip. Batch-mode only — auto_graph requires holons=[...].

    To add an existing holon to a second holarchy, use holon_update
    with action="join_holarchy".
    session_id: think session; omit to auto-create or reuse active session

    Args:
        name: Human-readable label (single mode).
        description: What this holon IS (single mode).
        session_id: Thinking session ID. Omit to auto-create.
        holarchy_id: Which holarchy. Auto-created for root holons.
        parent_id: Parent holon ID. None = root of new holarchy.
        role_in_parent: What this holon DOES (as a part).
        context: Working state / knowledge at this level.
        rules: Internal constraints.
        properties: Observable properties.
        projection: What this holon exposes upward in this holarchy.
        holons: Batch mode — list of dicts. Each: {ref, name, description,
            parent_ref?, holarchy_id?, role_in_parent?, context?, rules?,
            properties?, projection?}. Topologically resolved server-side.
        auto_graph: Batch-only (holons=[...]). When True + parent session has
            graph backend, materialise each holon as a KnowledgeNode +
            parent_ref edges (PartOf) in one round trip. Requires an
            explicit unified session_id from
            session_create(backends=['think','graph']).

    Returns:
        Single mode: compact status with holon position.
        Batch mode: ref→id mapping for all created holons (+ graph node
        count if auto_graph).
    """
    _, info = await anyio.to_thread.run_sync(lambda: _get_or_create_think_session(session_id, ctx))
    engine = _engine(info)
    sid = info.session_id

    # ── Batch path ─────────────────────────────────────
    if holons is not None:
        if not holons:
            raise ValueError("holons batch must be non-empty")
        default_hid = holarchy_id or uuid.uuid4().hex[:10]
        ref_to_id = engine.add_holons_batch(holons, default_hid)
        if rule_profile_ids:
            bindings = _rule_bindings_from_profile_ids(engine, rule_profile_ids)
            for holon_ref, holon_id in ref_to_id.items():
                engine.bind_rule_profiles(holon_id, "holon", bindings)
                await _materialize_subject_rule_bindings(
                    engine,
                    session_id,
                    subject_kind="holon",
                    subject_id=holon_id,
                    subject_label=next(
                        (item["name"] for item in holons if item["ref"] == holon_ref),
                        holon_id,
                    ),
                    bindings=bindings,
                    source="holon_create",
                )
        # Discover holarchies actually created
        hids_used: set[str] = set()
        for hid_val in [item.get("holarchy_id") or default_hid for item in holons]:
            hids_used.add(hid_val)
        ref_lines = ", ".join(f"{r}={i}" for r, i in ref_to_id.items())

        eff_auto_graph = resolve_auto_graph(auto_graph, info, session_id)
        eff_sid = effective_session_id(session_id, info)
        graph_count = 0
        if eff_auto_graph:
            from aismartbuddy.tools import materialize_auto_graph

            if not eff_sid:
                raise ValueError(
                    "auto_graph requires a parent session with a graph backend. "
                    "Use session_create(backends=['think','graph']) or omit session_id "
                    "to auto-create a session with graph support."
                )
            # Build a synthetic items list keyed on the FINAL assigned holon-id
            # so KnowledgeNode rows match how downstream tools reference holons.
            # parent_ref values are mapped through ref_to_id when they refer to
            # a batch ref; existing holon-ids pass through via dict.get fallback.
            synthetic = [
                {
                    "id": ref_to_id[h["ref"]],
                    "description": h.get("description", ""),
                    "parent_ref": (
                        [ref_to_id.get(h["parent_ref"], h["parent_ref"])]
                        if h.get("parent_ref")
                        else []
                    ),
                }
                for h in holons
            ]
            graph_count = await materialize_auto_graph(
                eff_sid,
                synthetic,
                source_tag="holon_create",
                entity_type="holon",
                description_field="description",
                edge_label="PartOf",
                ref_field="parent_ref",
            )

        out_lines = [
            f"Session: {sid} | Batch: {len(ref_to_id)} holons created",
            f"Holarchies: {', '.join(sorted(hids_used))}",
            f"Refs: {ref_lines}",
        ]
        if eff_auto_graph:
            out_lines.append(f"Graph nodes created: {graph_count}")
        out_lines.append("Status: created")
        return "\n".join(out_lines)

    # ── Single mode (existing behavior) ────────────────
    if auto_graph:
        raise ValueError(
            "auto_graph is only supported in batch mode. "
            "Pass holons=[...] to use auto_graph."
        )
    if not name:
        raise ValueError("Single-mode holon_create requires 'name'")
    if not description:
        raise ValueError("Single-mode holon_create requires 'description'")
    hid = holarchy_id or uuid.uuid4().hex[:10]
    nid = uuid.uuid4().hex[:10]
    level = 0

    if parent_id:
        parent = engine.get_holon(parent_id)
        if parent is None:
            raise ValueError(f"Parent holon '{parent_id}' not found")
        # Infer holarchy from parent if not specified
        if not holarchy_id:
            if parent.memberships:
                hid = parent.memberships[0]["holarchy_id"]
            else:
                raise ValueError("Parent has no memberships — specify holarchy_id")
        # Derive level from parent's level in this holarchy
        pm = _get_membership(parent, hid)
        if pm:
            level = pm["level"] + 1

    node = HolonNode(
        id=nid,
        name=name,
        description=description,
        context=context,
        rules=rules or [],
        properties=properties or [],
        rule_bindings=_rule_bindings_from_profile_ids(engine, rule_profile_ids),
        memberships=[
            {
                "holarchy_id": hid,
                "parent_id": parent_id,
                "role_in_parent": role_in_parent,
                "level": level,
            }
        ],
        projections={hid: projection} if projection else {},
    )
    engine.add_holon(node)
    await _materialize_subject_rule_bindings(
        engine,
        session_id,
        subject_kind="holon",
        subject_id=nid,
        subject_label=name,
        bindings=node.rule_bindings,
        source="holon_create",
    )

    parent_name = ""
    if parent_id:
        p = engine.get_holon(parent_id)
        if p:
            parent_name = p.name

    return (
        f"Session: {sid} | Holarchy: {hid} | Holon: {nid}\n"
        f"Name: {name} | Level: {level} | Memberships: 1\n"
        f"Parent: {parent_name or 'root'}"
        + (f" | Role: {role_in_parent}" if role_in_parent else "")
        + "\nStatus: created"
    )


# ── Tool: holon_update ──────────────────────────────────────


async def holon_update(
    session_id: str,
    holon_id: str,
    action: str,
    content: str | None = None,
    rules: list[str] | None = None,
    properties: list[str] | None = None,
    holarchy_id: str | None = None,
    parent_id: str | None = None,
    role_in_parent: str | None = None,
    projection: str | None = None,
    lens_name: str | None = None,
    lens_findings: str | None = None,
    rule_profile_ids: list[str] | None = None,
) -> str:
    """[ELABORATE] Update a holon's state, join a holarchy, or add an analytical lens.

    Actions:
        context: Update working state (requires content).
        rules: Replace internal constraints (requires rules).
        description: Update what the holon IS (requires content).
        properties: Update observable properties (requires properties).
        projection: Update projected state in a holarchy
            (requires holarchy_id and content).
        join_holarchy: Add this holon to another holarchy
            (requires holarchy_id, parent_id, role_in_parent).
        add_lens: Add an analytical lens result
            (requires lens_name, lens_findings). Any name works —
            built-in suggestions: agency, communion, transcendence,
            dissolution. Or define your own.

    Args:
        session_id: Thinking session ID.
        holon_id: Which holon to update.
        action: What to update.
        content: New text for context/description/projection.
        rules: New rules list.
        properties: New properties list.
        holarchy_id: For projection/join_holarchy.
        parent_id: For join_holarchy.
        role_in_parent: For join_holarchy.
        projection: Initial projection for join_holarchy.
        lens_name: Name of analytical lens.
        lens_findings: Findings text.

    Returns:
        Compact status confirming update.
    """
    _validate_enum(action, _HOLON_UPDATE_ACTIONS, "action")
    _, info = _require_think_session(session_id)
    engine = _engine(info)

    # Hold engine lock for the whole lookup+mutation sequence so concurrent
    # tool calls don't race on the same holon node's fields. RLock reentry
    # keeps nested @_synchronized engine calls safe.
    with engine.state_lock:
        node = engine.get_holon(holon_id)
        if node is None:
            raise ValueError(f"Holon '{holon_id}' not found")

        result = _holon_update_locked(
            engine,
            info,
            node,
            holon_id,
            action,
            content,
            rules,
            properties,
            holarchy_id,
            parent_id,
            role_in_parent,
            projection,
            lens_name,
            lens_findings,
            rule_profile_ids,
        )
        bindings = list(node.rule_bindings)
        subject_label = node.name
    await _materialize_subject_rule_bindings(
        engine,
        session_id,
        subject_kind="holon",
        subject_id=holon_id,
        subject_label=subject_label,
        bindings=bindings,
        source="holon_update",
    )
    return result


def _holon_update_locked(
    engine: ThinkingEngine,
    info: SessionInfo,
    node: HolonNode,
    holon_id: str,
    action: str,
    content: str | None,
    rules: list[str] | None,
    properties: list[str] | None,
    holarchy_id: str | None,
    parent_id: str | None,
    role_in_parent: str | None,
    projection: str | None,
    lens_name: str | None,
    lens_findings: str | None,
    rule_profile_ids: list[str] | None,
) -> str:
    """Body of holon_update executed under engine.state_lock.

    Extracted to a helper so the locked region is expressed as a single
    function call rather than a large indented block. Callers MUST hold
    engine.state_lock (enforced by holon_update's with-block).
    """
    session_id = info.session_id
    if rule_profile_ids:
        bindings = _rule_bindings_from_profile_ids(engine, rule_profile_ids)
        existing = list(node.rule_bindings)
        seen = {(b.get("profile_id"), b.get("snapshot_id")) for b in existing}
        for binding in bindings:
            key = (binding.get("profile_id"), binding.get("snapshot_id"))
            if key not in seen:
                seen.add(key)
                existing.append(binding)
        node.rule_bindings = existing
    if action == "context":
        if not content:
            raise ValueError("content is required for context action")
        node.context = content
        return f"Session: {session_id} | Holon: {holon_id}\nContext updated: {_trunc_long(content)}"

    if action == "rules":
        if rules is None:
            raise ValueError("rules is required for rules action")
        node.rules = rules
        return f"Session: {session_id} | Holon: {holon_id}\nRules updated: {len(rules)} rules"

    if action == "description":
        if not content:
            raise ValueError("content is required for description action")
        node.description = content
        return (
            f"Session: {session_id} | Holon: {holon_id}\n"
            f"Description updated: {_trunc_long(content)}"
        )

    if action == "properties":
        if properties is None:
            raise ValueError("properties is required for properties action")
        node.properties = properties
        return (
            f"Session: {session_id} | Holon: {holon_id}\n"
            f"Properties updated: {len(properties)} properties"
        )

    if action == "projection":
        if not holarchy_id or not content:
            raise ValueError("holarchy_id and content required for projection action")
        node.projections[holarchy_id] = content
        # Clear stale flag
        node.stale_projections.discard(holarchy_id)
        return (
            f"Session: {session_id} | Holon: {holon_id}\n"
            f"Projection in {holarchy_id} updated: {_trunc_long(content)}"
        )

    if action == "join_holarchy":
        if not holarchy_id or not parent_id:
            raise ValueError("holarchy_id and parent_id required for join_holarchy")
        parent = engine.get_holon(parent_id)
        if parent is None:
            raise ValueError(f"Parent '{parent_id}' not found")
        pm = _get_membership(parent, holarchy_id)
        level = (pm["level"] + 1) if pm else 0
        engine.join_holarchy(
            holon_id,
            holarchy_id,
            parent_id,
            role_in_parent or "",
            level,
        )
        if projection:
            node.projections[holarchy_id] = projection
        return (
            f"Session: {session_id} | Holon: {holon_id}\n"
            f"Joined holarchy {holarchy_id} under {parent.name}"
            f" | Memberships: {len(node.memberships)}"
        )

    # action == "add_lens"
    if not lens_name or not lens_findings:
        raise ValueError("lens_name and lens_findings required for add_lens")
    node.analytical_lenses.append(
        {
            "name": lens_name,
            "findings": lens_findings,
        }
    )
    return (
        f"Session: {session_id} | Holon: {holon_id}\n"
        f"Lens '{lens_name}' added"
        f" | Total lenses: {len(node.analytical_lenses)}"
    )


# ── Tool: holon_view ────────────────────────────────────────


@size_guarded
async def holon_view(
    session_id: str,
    holon_id: str,
    action: str = "cross_level",
    holarchy_id: str | None = None,
    levels_up: int = 1,
    levels_down: int = 1,
) -> str:
    """[ELABORATE] Navigate the holarchy while preserving context at each level.

    Actions:
        zoom_in: Descend one level. Shows children with parent
            context as constraint header. Warns on stale projections.
        zoom_out: Ascend one level. Shows parent state, all siblings,
            and synthesis prompt.
        sideways: View peers (children of same parent). Shows
            projections and detected tensions.
        cross_level: Three-level view — ancestry, this holon,
            descendants. Most useful for analysis.
        memberships: Show all holarchies this holon participates in.

    Args:
        session_id: Thinking session ID.
        holon_id: Which holon to view from.
        action: Navigation type.
        holarchy_id: Which holarchy perspective. Auto-resolved if
            holon has only one membership.
        levels_up: For cross_level — how many ancestor levels.
        levels_down: For cross_level — how many descendant levels.

    Returns:
        Structured multi-level view with context preservation.
    """
    _validate_enum(action, _HOLON_VIEW_ACTIONS, "action")
    _, info = _require_think_session(session_id)
    engine = _engine(info)

    node = engine.get_holon(holon_id)
    if node is None:
        raise ValueError(f"Holon '{holon_id}' not found")

    # ── memberships: show all holarchies ─────────────────
    if action == "memberships":
        lines = [
            f"Session: {session_id} | Holon: {holon_id}",
            f"Name: {node.name}",
            f"Memberships: {len(node.memberships)}",
        ]
        for m in node.memberships:
            hid = m["holarchy_id"]
            pid = m.get("parent_id")
            parent_name = ""
            if pid:
                p = engine.get_holon(pid)
                parent_name = p.name if p else "?"
            stale = " [STALE]" if hid in node.stale_projections else ""
            proj = node.projections.get(hid, "(none)")
            lines.append(
                f"  {hid}: level={m['level']}"
                f" | parent={parent_name or 'root'}"
                f" | role={m['role_in_parent']}"
                f" | proj={proj[:40]}{stale}"
            )
        return "\n".join(lines)

    # Resolve holarchy for navigation actions
    hid = _resolve_holarchy(node, holarchy_id)
    if hid is None:
        return (
            f"Session: {session_id} | Holon: {holon_id}\n"
            f"Multiple memberships ({len(node.memberships)}). "
            "Specify holarchy_id or use action='memberships' to see all."
        )

    # ── zoom_in ──────────────────────────────────────────
    if action == "zoom_in":
        children = engine.get_holon_children(holon_id, hid)
        parent = engine.get_holon_parent(holon_id, hid)
        lines = [
            f"Session: {session_id} | Holarchy: {hid}",
            f"## Zooming into: {node.name} (Level {_get_membership(node, hid)['level']})",
        ]
        if parent:
            lines.append("\n### Parent Context (constraint header):")
            lines.append(f"{parent.context or '(no context)'}")
        lines.append(f"\n### This Holon: {node.name}")
        lines.append(f"{node.description}")
        if node.context:
            lines.append(f"Context: {node.context}")
        if node.rules:
            lines.append(f"Rules: {'; '.join(node.rules)}")
        if hid in node.stale_projections:
            lines.append("WARNING: Projection in this holarchy is STALE")
        _MAX_ZOOM_CHILDREN = 20
        shown_children = children[:_MAX_ZOOM_CHILDREN]
        omitted_children = len(children) - len(shown_children)
        lines.append(f"\n### Children ({len(children)}):")
        for i, child in enumerate(shown_children):
            lines.append(f"  {i + 1}. {_holon_summary_line(child, hid)}")
            if child.context:
                lines.append(f"     Context: {_trunc_long(child.context)}")
        if omitted_children:
            lines.append(f"  ... {omitted_children} more (use holon_query resolution=subtree)")
        if not children:
            lines.append("  (leaf holon — no children)")
        return "\n".join(lines)

    # ── zoom_out ─────────────────────────────────────────
    if action == "zoom_out":
        parent = engine.get_holon_parent(holon_id, hid)
        if parent is None:
            return (
                f"Session: {session_id} | Holarchy: {hid}\n"
                f"{node.name} is the root — cannot zoom out."
            )
        siblings = engine.get_holon_siblings(holon_id, hid)
        lines = [
            f"Session: {session_id} | Holarchy: {hid}",
            f"## Zooming out from: {node.name} → {parent.name}",
            f"\n### Parent: {parent.name}",
            f"{parent.description}",
        ]
        if parent.context:
            lines.append(f"Context: {parent.context}")
        if parent.rules:
            lines.append(f"Rules: {'; '.join(parent.rules)}")
        lines.append(f"\n### Siblings ({len(siblings)} + you):")
        lines.append(f"  [YOU] {_holon_summary_line(node, hid)}")
        for sib in siblings:
            lines.append(f"  - {_holon_summary_line(sib, hid)}")
            if sib.context:
                lines.append(f"    Context: {_trunc(sib.context)}")
        lines.append(
            "\n### Synthesis prompt:"
            " Given what you learned at the child level,"
            " does the parent context need updating?"
        )
        return "\n".join(lines)

    # ── sideways ─────────────────────────────────────────
    if action == "sideways":
        parent = engine.get_holon_parent(holon_id, hid)
        siblings = engine.get_holon_siblings(holon_id, hid)
        lines = [
            f"Session: {session_id} | Holarchy: {hid}",
            f"## Peers of: {node.name}",
        ]
        if parent:
            lines.append(f"\n### Shared Parent: {parent.name}")
            lines.append(f"Context: {parent.context or '(none)'}")
        _MAX_SIDEWAYS_SIBLINGS = 20
        shown_siblings = siblings[:_MAX_SIDEWAYS_SIBLINGS]
        omitted_siblings = len(siblings) - len(shown_siblings)
        lines.append(f"\n### Peers ({len(siblings)}):")
        for sib in shown_siblings:
            lines.append(f"  - {_holon_summary_line(sib, hid)}")
            if sib.description:
                lines.append(f"    Description: {_trunc(sib.description)}")
            if sib.context:
                lines.append(f"    Context: {_trunc(sib.context)}")
        if omitted_siblings:
            lines.append(f"  ... {omitted_siblings} more (use holon_query resolution=local)")
        if not siblings:
            lines.append("  (no peers — only child)")
        return "\n".join(lines)

    # ── cross_level ──────────────────────────────────────
    ancestry = engine.get_holon_ancestry(holon_id, hid)
    ancestry.reverse()  # root first
    ancestry = ancestry[-levels_up - 1 :]  # trim to levels_up + self
    descendants = engine.get_holon_subtree(holon_id, hid, max_depth=levels_down)

    lines = [
        f"Session: {session_id} | Holarchy: {hid}",
        f"## Cross-Level View: {node.name} ({levels_up} up, {levels_down} down)",
    ]
    lines.append("\n### Ancestry:")
    for anc in ancestry:
        m = _get_membership(anc, hid)
        lvl = m["level"] if m else "?"
        marker = " [THIS]" if anc.id == holon_id else ""
        indent = "  " * (int(lvl) if isinstance(lvl, int) else 0)
        lines.append(f"{indent}{anc.name} (L{lvl}){marker}")
        if anc.context and anc.id != holon_id:
            lines.append(f"{indent}  Context: {_trunc(anc.context)}")

    if len(descendants) > 1:
        desc_list = [d for d in descendants if d.id != holon_id]
        _MAX_CROSS_DESC = 20
        shown = desc_list[:_MAX_CROSS_DESC]
        omitted = len(desc_list) - len(shown)
        lines.append(f"\n### Descendants ({len(desc_list)}):")
        for desc in shown:
            m = _get_membership(desc, hid)
            lvl = m["level"] if m else "?"
            proj = desc.projections.get(hid, "")
            stale = " [STALE]" if hid in desc.stale_projections else ""
            role = m["role_in_parent"][:40] if m and m.get("role_in_parent") else ""
            parts = [f"  {desc.name} (L{lvl})"]
            if role:
                parts.append(f"role={role}")
            if proj:
                parts.append(f"proj={proj[:40]}{stale}")
            elif stale:
                parts.append(f"proj=?{stale}")
            lines.append(" | ".join(parts))
        if omitted:
            lines.append(f"  ... {omitted} more (use holon_query resolution=subtree)")

    stale_count = sum(1 for d in descendants if hid in d.stale_projections)
    if stale_count:
        lines.append(f"\nStale projections in scope: {stale_count}")

    return "\n".join(lines)


# ── Tool: holon_analyze ──────────────────────────────────────


@size_guarded
async def holon_analyze(
    session_id: str,
    action: str,
    holon_id: str | None = None,
    holarchy_id: str | None = None,
    insight: str | None = None,
    propagation_type: str | None = None,
    lens_name: str | None = None,
    lens_prompt: str | None = None,
    holon_a_id: str | None = None,
    holon_b_id: str | None = None,
    from_id: str | None = None,
    to_id: str | None = None,
) -> str:
    """[ELABORATE] Analyze holarchy patterns, propagate insights, find bridges.

    Actions:
        tensions: Scan for structural problems — missing levels,
            conflicting projections, stale data. Scope: holon_id=None
            scans all; holon_id scans that subtree.
        emergence: Compare holon's properties to children's.
            Gap = emergent properties.
        propagate_up: Push insight upward. Modifies parent data:
            inform (update context + flag stale), constrain (add rule),
            transform (flag description stale).
        propagate_down: Push directive downward. Modifies descendants:
            constrain (add rule), enable (add property),
            restructure (flag description stale).
        coherence: Given two holons, assess what each implies about
            the other. Gathers state and presents coherence assessment.
        bridge: Find shortest path between two holons across all
            holarchies. Returns intermediate holons in the causal chain.
        lens: Apply an analytical lens. Any name works — suggested:
            agency, communion, transcendence, dissolution. Or define
            your own (e.g., vulnerability, information_flow).
        feedback_loops: Detect bidirectional causal references
            between holons (A references B AND B references A).
            Scoped by holarchy_id and/or holon_id.
        leverage_points: Find structurally important holons by
            multi-membership count and connection density.
            Scans all holons globally.

    Args:
        session_id: Thinking session ID.
        action: Analysis type.
        holon_id: Target holon (for tensions/emergence/propagate/lens).
        holarchy_id: Which holarchy (for propagation).
        insight: Text to propagate (for propagate_up/down).
        propagation_type: inform/constrain/transform/enable/restructure.
        lens_name: Name of analytical lens.
        lens_prompt: Guiding question for the lens.
        holon_a_id: First holon (for coherence).
        holon_b_id: Second holon (for coherence).
        from_id: Start holon (for bridge).
        to_id: End holon (for bridge).

    Returns:
        Analysis results in compact text.
    """
    _validate_enum(action, _HOLON_ANALYZE_ACTIONS, "action")
    _, info = _require_think_session(session_id)
    engine = _engine(info)

    # ── tensions ─────────────────────────────────────────
    if action == "tensions":
        issues: list[str] = []
        holons = (
            [engine.get_holon(holon_id)]
            if holon_id and engine.get_holon(holon_id)
            else list(engine.holon_nodes.values())
        )
        for h in holons:
            if h is None:
                continue
            # Stale projections
            if h.stale_projections:
                issues.append(f"{h.name}: stale projections in {', '.join(h.stale_projections)}")
            # Description stale
            if h.description_stale:
                issues.append(f"{h.name}: description may be invalid")
            # Check for holons with no children but marked as
            # having sub-structure implied by properties
            for m in h.memberships:
                hid = m["holarchy_id"]
                children = engine.get_holon_children(h.id, hid)
                parent = engine.get_holon_parent(h.id, hid)
                # Orphan check: parent doesn't exist
                pid = m.get("parent_id")
                if pid and not engine.get_holon(pid):
                    issues.append(f"{h.name}: orphaned in {hid} (parent {pid} missing)")
                # No children at non-leaf level
                if not children and parent and engine.get_holon_children(parent.id, hid):
                    sibs = engine.get_holon_siblings(h.id, hid)
                    sibs_with_children = [s for s in sibs if engine.get_holon_children(s.id, hid)]
                    if sibs_with_children:
                        issues.append(
                            f"{h.name}: leaf in {hid} but "
                            f"siblings have children "
                            "(possible missing decomposition)"
                        )

        lines = [
            f"Session: {session_id}",
            f"## Tension Scan: {len(issues)} issues found",
        ]
        for issue in issues:
            lines.append(f"  - {issue}")
        if not issues:
            lines.append("  No structural tensions detected.")
        return "\n".join(lines)

    # ── emergence ────────────────────────────────────────
    if action == "emergence":
        if not holon_id:
            raise ValueError("holon_id required for emergence")
        node = engine.get_holon(holon_id)
        if node is None:
            raise ValueError(f"Holon '{holon_id}' not found")

        hid = _resolve_holarchy(node, holarchy_id)
        children = engine.get_holon_children(holon_id, hid) if hid else []
        child_props: set[str] = set()
        for child in children:
            child_props.update(child.properties)

        parent_props = set(node.properties)
        emergent = parent_props - child_props

        lines = [
            f"Session: {session_id} | Holon: {node.name}",
            "## Emergence Analysis",
            f"\nChildren's combined properties ({len(child_props)}):",
        ]
        for p in sorted(child_props):
            lines.append(f"  - {p}")
        lines.append(f"\nThis holon's properties ({len(parent_props)}):")
        for p in sorted(parent_props):
            marker = " [EMERGENT]" if p in emergent else ""
            lines.append(f"  - {p}{marker}")
        lines.append(f"\nEmergent properties ({len(emergent)}):")
        for p in sorted(emergent):
            lines.append(f"  - {p}")
        if not emergent:
            lines.append(
                "  None detected — all properties traceable "
                "to children. Consider: are there properties "
                "at this level not yet documented?"
            )
        return "\n".join(lines)

    # ── propagate_up ─────────────────────────────────────
    if action == "propagate_up":
        if not holon_id or not insight or not propagation_type:
            raise ValueError("holon_id, insight, and propagation_type required for propagate_up")
        _validate_enum(
            propagation_type,
            _PROPAGATION_UP_TYPES,
            "propagation_type (up)",
        )
        node = engine.get_holon(holon_id)
        if node is None:
            raise ValueError(f"Holon '{holon_id}' not found")

        hid = _resolve_holarchy(node, holarchy_id)
        if hid is None:
            raise ValueError("Specify holarchy_id for propagation")

        affected: list[str] = []
        # Atomic propagation — whole ancestor chain updated under one lock
        with engine.state_lock:
            current = engine.get_holon_parent(holon_id, hid)
            while current:
                if propagation_type == "inform":
                    sep = "\n" if current.context else ""
                    current.context += f"{sep}[propagated] {insight}"
                    current.stale_projections.add(hid)
                elif propagation_type == "constrain":
                    current.rules.append(f"[propagated] {insight}")
                elif propagation_type == "transform":
                    current.description_stale = True
                affected.append(current.name)
                current = engine.get_holon_parent(current.id, hid)

        return (
            f"Session: {session_id} | Propagated UP in {hid}\n"
            f"Type: {propagation_type}\n"
            f"Insight: {_trunc_long(insight)}\n"
            f"Affected ({len(affected)}): " + " → ".join(affected)
        )

    # ── propagate_down ───────────────────────────────────
    if action == "propagate_down":
        if not holon_id or not insight or not propagation_type:
            raise ValueError("holon_id, insight, and propagation_type required for propagate_down")
        _validate_enum(
            propagation_type,
            _PROPAGATION_DOWN_TYPES,
            "propagation_type (down)",
        )
        node = engine.get_holon(holon_id)
        if node is None:
            raise ValueError(f"Holon '{holon_id}' not found")

        hid = _resolve_holarchy(node, holarchy_id)
        if hid is None:
            raise ValueError("Specify holarchy_id for propagation")

        affected: list[str] = []
        # Atomic propagation — snapshot + updates under one lock
        with engine.state_lock:
            subtree = engine.get_holon_subtree(holon_id, hid)
            for desc in subtree:
                if desc.id == holon_id:
                    continue
                if propagation_type == "constrain":
                    desc.rules.append(f"[propagated] {insight}")
                elif propagation_type == "enable":
                    desc.properties.append(f"[propagated] {insight}")
                elif propagation_type == "restructure":
                    desc.description_stale = True
                affected.append(desc.name)

        return (
            f"Session: {session_id} | Propagated DOWN in {hid}\n"
            f"Type: {propagation_type}\n"
            f"Directive: {_trunc_long(insight)}\n"
            f"Affected ({len(affected)}): {', '.join(affected)}"
        )

    # ── coherence ────────────────────────────────────────
    if action == "coherence":
        if not holon_a_id or not holon_b_id:
            raise ValueError("holon_a_id and holon_b_id required for coherence")
        a = engine.get_holon(holon_a_id)
        b = engine.get_holon(holon_b_id)
        if a is None:
            raise ValueError(f"Holon '{holon_a_id}' not found")
        if b is None:
            raise ValueError(f"Holon '{holon_b_id}' not found")

        # Find shared holarchies
        a_hids = {m["holarchy_id"] for m in a.memberships}
        b_hids = {m["holarchy_id"] for m in b.memberships}
        shared = a_hids & b_hids

        lines = [
            f"Session: {session_id}",
            f"## Coherence: {a.name} ↔ {b.name}",
            f"\n### {a.name}:",
            f"Description: {a.description}",
            f"Context: {a.context or '(none)'}",
            f"Rules: {'; '.join(a.rules) or '(none)'}",
        ]
        for hid in a_hids:
            proj = a.projections.get(hid, "(none)")
            lines.append(f"Projection [{hid}]: {proj}")
        lines.append(f"\n### {b.name}:")
        lines.append(f"Description: {b.description}")
        lines.append(f"Context: {b.context or '(none)'}")
        lines.append(f"Rules: {'; '.join(b.rules) or '(none)'}")
        for hid in b_hids:
            proj = b.projections.get(hid, "(none)")
            lines.append(f"Projection [{hid}]: {proj}")

        lines.append(f"\n### Shared holarchies: {len(shared)}")
        if shared:
            lines.append(f"  {', '.join(shared)}")

        # Bridge path
        bridge = engine.find_bridge(holon_a_id, holon_b_id)
        if bridge and len(bridge) > 2:
            lines.append(
                f"\n### Bridge ({len(bridge)} hops): " + " → ".join(n.name for n in bridge)
            )

        lines.append(
            "\n### Coherence prompt:"
            f" Given {a.name}'s state and {b.name}'s state,"
            " what must be true for both to be coherent?"
            " What can be verified or falsified?"
        )
        return "\n".join(lines)

    # ── bridge ───────────────────────────────────────────
    if action == "bridge":
        if not from_id or not to_id:
            raise ValueError("from_id and to_id required for bridge")
        from_node = engine.get_holon(from_id)
        to_node = engine.get_holon(to_id)
        if from_node is None:
            raise ValueError(f"Holon '{from_id}' not found")
        if to_node is None:
            raise ValueError(f"Holon '{to_id}' not found")

        path = engine.find_bridge(from_id, to_id)
        if not path:
            return (
                f"Session: {session_id}\nNo path found between {from_node.name} and {to_node.name}"
            )

        lines = [
            f"Session: {session_id}",
            f"## Bridge: {from_node.name} → {to_node.name}",
            f"Path length: {len(path)} holons",
            "",
        ]
        for i, node in enumerate(path):
            marker = ""
            if i == 0:
                marker = " [START]"
            elif i == len(path) - 1:
                marker = " [END]"
            lines.append(f"  {i + 1}. {node.name}{marker} — {_trunc(node.description)}")
            if node.context:
                lines.append(f"     Context: {_trunc(node.context)}")
        return "\n".join(lines)

    # ── feedback_loops ───────────────────────────────────
    if action == "feedback_loops":
        return _analyze_feedback_loops(
            engine,
            session_id,
            holarchy_id,
            holon_id,
        )

    # ── leverage_points ──────────────────────────────────
    if action == "leverage_points":
        return _analyze_leverage_points(engine, session_id)

    # ── lens ─────────────────────────────────────────────
    if not holon_id:
        raise ValueError("holon_id required for lens")
    if not lens_name:
        # Return suggestions
        node = engine.get_holon(holon_id)
        name = node.name if node else holon_id
        return (
            f"Session: {session_id} | Holon: {name}\n"
            "Suggested lenses:\n"
            "  agency: What maintains this holon's identity?"
            " What would destroy it?\n"
            "  communion: How does it serve the larger whole?"
            " What does it sacrifice?\n"
            "  transcendence: What is it becoming?"
            " What emergent properties appear?\n"
            "  dissolution: What happens if it fails?"
            " What cascading failures propagate?\n"
            "  (or define your own: any lens_name"
            " + lens_prompt works)"
        )

    node = engine.get_holon(holon_id)
    if node is None:
        raise ValueError(f"Holon '{holon_id}' not found")

    # Return context for analysis — use holon_update(add_lens) to store
    lines = [
        f"Session: {session_id} | Holon: {node.name}",
        f"Lens: {lens_name}",
    ]
    if lens_prompt:
        lines.append(f"Prompt: {lens_prompt}")
    lines.append(f"Description: {node.description}")
    lines.append(f"Context: {node.context or '(none)'}")
    if node.rules:
        lines.append(f"Rules: {'; '.join(node.rules)}")
    if node.properties:
        lines.append(f"Properties: {', '.join(node.properties)}")
    lines.append("Use holon_update(action='add_lens') to store findings.")
    return "\n".join(lines)


# ── holon_analyze: feedback_loops + leverage_points ──────────


def _analyze_feedback_loops(
    engine: ThinkingEngine,
    session_id: str,
    holarchy_id: str | None,
    holon_id: str | None,
) -> str:
    """Detect feedback loops by finding bidirectional references."""
    holons = list(engine.holon_nodes.values())
    if holon_id:
        node = engine.get_holon(holon_id)
        if node is None:
            raise ValueError(f"Holon '{holon_id}' not found")
        hid = _resolve_holarchy(node, holarchy_id)
        if hid is None:
            raise ValueError("Specify holarchy_id (holon has multiple memberships)")
        subtree_ids = {n.id for n in engine.get_holon_subtree(holon_id, hid)}
        holons = [h for h in holons if h.id in subtree_ids]
    elif holarchy_id:
        holons = [h for h in holons if any(m["holarchy_id"] == holarchy_id for m in h.memberships)]

    # Find bidirectional references in context/rules
    _MAX_FEEDBACK_PAIRS = 50
    loops: list[dict] = []
    checked: set[tuple[str, str]] = set()
    truncated = False
    texts = {h.id: (h.context + " " + " ".join(h.rules)).lower() for h in holons}
    names = {h.id: h.name.lower() for h in holons}
    outer_break = False
    for a in holons:
        if outer_break:
            break
        for b in holons:
            if len(checked) >= _MAX_FEEDBACK_PAIRS:
                truncated = True
                outer_break = True
                break
            if a.id == b.id:
                continue
            pair = tuple(sorted([a.id, b.id]))
            if pair in checked:
                continue
            checked.add(pair)
            if names[b.id] in texts[a.id] and names[a.id] in texts[b.id]:
                loops.append(
                    {
                        "holon_a": a.name,
                        "holon_b": b.name,
                        "a_context": _trunc(a.context),
                        "b_context": _trunc(b.context),
                    }
                )

    lines = [
        f"Session: {session_id}",
        f"## Feedback Loops: {len(loops)} detected",
    ]
    for loop in loops:
        lines.append(f"  {loop['holon_a']} <-> {loop['holon_b']}")
        lines.append(f"    A: {loop['a_context']}")
        lines.append(f"    B: {loop['b_context']}")
    if not loops:
        lines.append(
            "  No bidirectional references detected. "
            "Feedback loops may exist but aren't reflected "
            "in holon context/rules text yet."
        )
    if truncated:
        lines.append(
            f"  (search capped at {_MAX_FEEDBACK_PAIRS} pairs"
            f" across {len(holons)} holons — scope with holon_id to search deeper)"
        )
    return "\n".join(lines)


def _analyze_leverage_points(
    engine: ThinkingEngine,
    session_id: str,
) -> str:
    """Find structurally important holons by connectivity."""
    scores: list[tuple[str, str, float]] = []
    for hid, node in engine.holon_nodes.items():
        membership_count = len(node.memberships)
        total_children = sum(len(kids) for kids in node.children_by_holarchy.values())
        # Score: memberships weight 3x, children weight 1x
        score = (membership_count * 3.0) + total_children
        if score > 0:
            scores.append((hid, node.name, score))

    scores.sort(key=lambda x: x[2], reverse=True)
    top = scores[:10]

    lines = [
        f"Session: {session_id}",
        f"## Leverage Points: top {len(top)} by connectivity",
    ]
    for i, (hid, name, score) in enumerate(top):
        node = engine.holon_nodes[hid]
        memberships = len(node.memberships)
        children = sum(len(kids) for kids in node.children_by_holarchy.values())
        lines.append(
            f"  {i + 1}. {name} (score={score:.0f})"
            f" | memberships={memberships}"
            f" | children={children}"
        )
    if not top:
        lines.append("  No holons found.")
    return "\n".join(lines)


# ── Tool: holon_query ────────────────────────────────────────


@size_guarded
async def holon_query(
    session_id: str,
    question: str,
    vantage_id: str,
    holarchy_id: str | None = None,
    resolution: str = "local",
) -> str:
    """[ELABORATE] Query the holarchy from a specific vantage point and resolution.

    Assembles context visible from the vantage holon at the
    specified resolution and presents it as a structured briefing.

    This is the embryonic form of perspectival reconstruction —
    the interface is designed so Layer 2 can make the implementation
    smarter without changing the tool contract.

    Resolutions:
        local: The holon's state + parent context + children.
        subtree: The holon + all descendants in the holarchy.
        holarchy: The entire holarchy, centered on the vantage holon.

    Args:
        session_id: Thinking session ID.
        question: What you're trying to understand.
        vantage_id: From whose perspective to assemble context.
        holarchy_id: Which holarchy. Auto-resolved if single membership.
        resolution: How much context to gather.

    Returns:
        Structured briefing with question and gathered context.
    """
    _validate_enum(resolution, _HOLON_QUERY_RESOLUTIONS, "resolution")
    _, info = _require_think_session(session_id)
    engine = _engine(info)

    vantage = engine.get_holon(vantage_id)
    if vantage is None:
        raise ValueError(f"Vantage holon '{vantage_id}' not found")

    hid = _resolve_holarchy(vantage, holarchy_id)
    if hid is None:
        raise ValueError("Specify holarchy_id (vantage has multiple memberships)")

    lines = [
        f"Session: {session_id} | Query from: {vantage.name} | Resolution: {resolution}",
        f"Question: {question}",
        f"\n## Vantage Point: {vantage.name}",
        f"Description: {vantage.description}",
        f"Context: {vantage.context or '(none)'}",
    ]
    proj = vantage.projections.get(hid, "")
    if proj:
        stale = " [STALE]" if hid in vantage.stale_projections else ""
        lines.append(f"Projection: {proj}{stale}")
    if vantage.rules:
        lines.append(f"Rules: {'; '.join(vantage.rules)}")
    if vantage.analytical_lenses:
        lines.append(f"Lenses: {len(vantage.analytical_lenses)}")
        for lens in vantage.analytical_lenses:
            lines.append(f"  {lens['name']}: {_trunc(lens['findings'])}")

    # Gather scope — collect visible nodes for stale scan
    scope_nodes: list[HolonNode] = [vantage]
    if resolution == "local":
        parent = engine.get_holon_parent(vantage_id, hid)
        children = engine.get_holon_children(vantage_id, hid)
        scope_nodes.extend(children)
        if parent:
            scope_nodes.append(parent)
        lines.append("\n## Visible Context (local):")
        if parent:
            lines.append(f"Parent: {parent.name}")
            lines.append(f"  Context: {parent.context or '(none)'}")
        lines.append(f"Children ({len(children)}):")
        for child in children:
            lines.append(f"  - {_holon_summary_line(child, hid)}")

    elif resolution == "subtree":
        subtree = engine.get_holon_subtree(vantage_id, hid)
        scope_nodes = subtree
        lines.append(f"\n## Visible Context (subtree, {len(subtree)} holons):")
        for node in subtree:
            m = _get_membership(node, hid)
            lvl = m["level"] if m else "?"
            indent = "  " * (int(lvl) if isinstance(lvl, int) else 0)
            lines.append(f"{indent}{node.name} (L{lvl})")
            if node.context:
                lines.append(f"{indent}  Context: {_trunc(node.context)}")

    else:  # holarchy
        root_id = engine.holon_holarchies.get(hid)
        if root_id:
            all_nodes = engine.get_holon_subtree(root_id, hid)
            scope_nodes = all_nodes
            lines.append(f"\n## Visible Context (holarchy, {len(all_nodes)} holons):")
            for node in all_nodes:
                m = _get_membership(node, hid)
                lvl = m["level"] if m else "?"
                indent = "  " * (int(lvl) if isinstance(lvl, int) else 0)
                marker = " [VANTAGE]" if node.id == vantage_id else ""
                lines.append(f"{indent}{node.name} (L{lvl}){marker}")
                if node.context:
                    lines.append(f"{indent}  Context: {_trunc(node.context)}")

    # Stale projections — scoped to visible nodes only
    stale_nodes = [n for n in scope_nodes if hid in n.stale_projections]
    if stale_nodes:
        lines.append(f"\n## Stale Projections ({len(stale_nodes)}):")
        for n in stale_nodes:
            lines.append(f"  - {n.name}")

    return "\n".join(lines)
