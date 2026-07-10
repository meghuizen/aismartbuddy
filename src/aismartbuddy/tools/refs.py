"""think_refs_query — find all records that reference a given entity_id.

Lets the AI compose across tools by ID rather than text-search. Queries
the `refs` list plus rule bindings / validations across the think backend.
"""

from __future__ import annotations

from mcp.server.mcpserver import Context as _MCPContext

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
        "models": [],
        "decisions": [],
        "inquiries": [],
        "monitors": [],
        "holon_nodes": [],
        "evaluations": [],
        "rule_profiles": [],
        "rule_conflicts": [],
        "validations": [],
        "hypotheses": [],
        "constraints": [],
        "constraint_validations": [],
        "topologies": [],
        "evidence": [],
        "evidence_chains": [],
    }
    with engine.state_lock:
        for nid, node in engine.thought_nodes.items():
            if entity_id in node.refs or engine._subject_rule_refs(node.rule_bindings, entity_id):
                matches["thought_nodes"].append(nid)
        for model in engine.models:
            if entity_id in model.refs or engine._subject_rule_refs(model.rule_bindings, entity_id):
                matches["models"].append(model.record_id or f"(anon:{model.model_name})")
        for did, decision in engine.decisions.items():
            if entity_id in decision.refs or engine._subject_rule_refs(
                decision.rule_bindings, entity_id
            ):
                matches["decisions"].append(did)
        for iid, inquiry in engine.inquiries.items():
            if entity_id in inquiry.refs or engine._subject_rule_refs(
                inquiry.rule_bindings, entity_id
            ):
                matches["inquiries"].append(iid)
        for mid, monitor in engine.monitors.items():
            if entity_id in monitor.refs or engine._subject_rule_refs(
                monitor.rule_bindings, entity_id
            ):
                matches["monitors"].append(mid)
        for hid, holon in engine.holon_nodes.items():
            if entity_id in holon.refs or engine._subject_rule_refs(holon.rule_bindings, entity_id):
                matches["holon_nodes"].append(hid)
        for eid, ev in engine.evaluations.items():
            if entity_id in ev.refs or engine._subject_rule_refs(ev.rule_bindings, entity_id):
                matches["evaluations"].append(eid)
        for pid, profile in engine.rule_profiles.items():
            if (
                entity_id == pid
                or entity_id in profile.refs
                or any(entity_id in {rule.id, *rule.refs} for rule in profile.rules)
            ):
                matches["rule_profiles"].append(pid)
        for cid, conflict in engine.rule_conflicts.items():
            if (
                entity_id == cid
                or entity_id in conflict.rule_ids
                or entity_id in conflict.profile_ids
            ):
                matches["rule_conflicts"].append(cid)
        for vid, validation in engine.validations.items():
            if (
                entity_id == vid
                or entity_id == validation.subject_id
                or entity_id in validation.refs
                or entity_id in validation.uncovered_rules
                or entity_id in validation.hard_failures
                or entity_id in validation.conflicting_rules
                or engine._subject_rule_refs(validation.rule_bindings, entity_id)
                or any(
                    entity_id == a.rule_id or entity_id in a.refs for a in validation.assessments
                )
            ):
                matches["validations"].append(vid)
        for hid, record in engine.hypotheses.items():
            if entity_id == hid or entity_id in record.refs:
                matches["hypotheses"].append(hid)
        for cid, record in engine.constraints.items():
            if entity_id == cid or entity_id in record.refs:
                matches["constraints"].append(cid)
        for cvid, record in engine.constraint_validations.items():
            if (
                entity_id == cvid
                or entity_id == record.constraint_id
                or entity_id == record.target_id
                or entity_id in record.refs
            ):
                matches["constraint_validations"].append(cvid)
        for tid, record in engine.topologies.items():
            node_ids = {str(node.get("id")) for node in record.nodes}
            if entity_id == tid or entity_id in node_ids:
                matches["topologies"].append(tid)
        for evid, record in engine.evidence.items():
            if entity_id == evid or entity_id in record.refs:
                matches["evidence"].append(evid)
        for chain_id, chain in engine.evidence_chains.items():
            if entity_id in {chain_id, chain.from_id, chain.to_id}:
                matches["evidence_chains"].append(chain_id)

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
