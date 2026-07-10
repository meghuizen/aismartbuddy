"""V2 mode-first structured reasoning tools."""

from __future__ import annotations

import json
import uuid
from collections import Counter
from typing import Any, NoReturn

from mcp.server.mcpserver import Context as _MCPContext

from aismartbuddy.concurrency import run_sync
from aismartbuddy.engines.thinking_engine import (
    ArgRecord,
    ArtifactRecord,
    IterationRecord,
    MonitorRecord,
    ThinkingEngine,
)
from aismartbuddy.identity import resolve_identity
from aismartbuddy.tools import (
    collect_item_refs,
    get_session_manager,
    run_with_lock,
    size_guarded,
    validate_items,
)
from aismartbuddy.tools.graph import escape_cypher_string

_MODES = frozenset({"explore", "diverge", "iterate", "analyze"})
_ENFORCEMENTS = frozenset({"advisory", "strict"})
_SCAFFOLD_MODELS = frozenset(
    {
        "first_principles",
        "design_review",
        "root_cause",
        "pre_mortem",
        "assumptions_xray",
        "error_propagation",
        "complexity",
        "swot",
        "fishbone",
        "pareto",
        "opportunity_cost",
        "value_of_info",
        "rubber_duck",
    }
)
_ARGUMENT_TYPES = frozenset({"thesis", "antithesis", "synthesis", "objection", "rebuttal"})
_KNOWLEDGE_LEVELS = frozenset({"expert", "proficient", "familiar", "basic", "minimal", "none"})
_DEBUG_APPROACHES = frozenset(
    {
        "binary_search",
        "reverse_engineering",
        "divide_conquer",
        "backtracking",
        "cause_elimination",
        "program_slicing",
    }
)
_REASON_GRAPH_ACTIONS = frozenset({"think", "branch", "connect", "synthesize", "revise"})


def _json_notice(code: str, message: str, next_tool: str | None = None) -> str:
    payload: dict[str, Any] = {"code": code, "message": message}
    if next_tool:
        payload["next_tool"] = next_tool
    return json.dumps(payload, separators=(",", ":"))


def _raise_json(code: str, message: str, next_tool: str | None = None) -> NoReturn:
    raise ValueError(_json_notice(code, message, next_tool))


def _validate_enum(value: str, valid: frozenset[str], label: str) -> str:
    if value not in valid:
        _raise_json(
            "VALIDATION_ERROR",
            f"Invalid {label}: {value!r}. Must be one of {', '.join(sorted(valid))}.",
        )
    return value


def _engine(info) -> ThinkingEngine:
    assert isinstance(info.engine, ThinkingEngine)
    return info.engine


def _resolve_reason_session(
    session_id: str | None,
    ctx: _MCPContext | None = None,
    *,
    required_backends: list[str] | None = None,
    default_mode: str = "analyze",
):
    """Return (manager, parent_session_or_none, think_session_info)."""
    mgr = get_session_manager()
    required_backends = required_backends or ["think"]
    if session_id:
        try:
            parent = mgr.get_parent_session(session_id)
            info = mgr.resolve_backend_session(session_id, "think")
            return mgr, parent, info
        except ValueError:
            info = mgr.get_session(session_id)
            if info.session_type != "think":
                _raise_json(
                    "VALIDATION_ERROR",
                    f"Session '{session_id}' is a {info.session_type} session, not think.",
                    "session_create",
                )
            return mgr, None, info

    user_id, project_id = resolve_identity(ctx, None, None)
    if required_backends == ["think"]:
        info = mgr.create_session(
            "think",
            user_id,
            project_id,
            mode=default_mode,
            enforcement="advisory",
        )
        return mgr, None, info
    parent = mgr.create_parent_session(
        required_backends,
        user_id,
        project_id,
        mode=default_mode,
        enforcement="advisory",
    )
    info = mgr.resolve_backend_session(parent.parent_id, "think")
    return mgr, parent, info


def _mode_for(info, parent) -> str:
    return getattr(parent, "mode", getattr(info, "mode", "analyze"))


def _enforcement_for(info, parent) -> str:
    return getattr(parent, "enforcement", getattr(info, "enforcement", "advisory"))


def _max_node_chars_for(info, parent) -> int:
    return int(getattr(parent, "max_node_chars", getattr(info, "max_node_chars", 500)))


def _artifact_summary(art: ArtifactRecord) -> str:
    for key in (
        "problem",
        "conclusion",
        "hypothesis",
        "idea",
        "claim",
        "thought",
        "task",
        "finding",
    ):
        if key in art.content:
            return str(art.content[key])[:100]
    return json.dumps(art.content, separators=(",", ":"))[:100]


def _session_tool_line(parent, info, mode: str, tool_name: str) -> str:
    session_ref = _graph_parent_id(parent, info) or info.session_id
    return f"Session: {session_ref} | Mode: {mode} | Tool: {tool_name}"


def _artifact_to_dict(art: ArtifactRecord) -> dict[str, Any]:
    return {
        "id": art.id,
        "kind": art.kind,
        "mode": art.mode,
        "phase": art.phase,
        "status": art.status,
        "model_name": art.model_name,
        "domain_tags": art.domain_tags,
        "content": art.content,
        "refs": art.refs,
        "connects_to": art.connects_to,
        "supports": art.supports,
        "contradicts": art.contradicts,
        "derived_from": art.derived_from,
        "confidence": art.confidence,
        "provenance": art.provenance,
        "created_at": art.created_at.isoformat(),
    }


def _has_phase(engine: ThinkingEngine, phase: str) -> bool:
    return any(a.phase == phase for a in engine.artifacts.values())


def _phase_guard(
    *,
    mode: str,
    phase: str,
    enforcement: str,
    engine: ThinkingEngine,
    session_id: str,
) -> str | None:
    mapping = {
        "explore": {"EXPLORE"},
        "diverge": {"DIVERGE"},
        "iterate": {"ITERATE"},
        "analyze": {"SCAFFOLD", "ELABORATE", "ASSESS"},
    }
    allowed = mapping[mode]
    if phase not in allowed:
        notice = _json_notice(
            "PHASE_GUARD",
            f"Current session mode is {mode}; {phase} tools are not primary in this session.",
            "session_create",
        )
        if enforcement == "strict":
            raise ValueError(notice)
        return notice

    if mode == "analyze":
        if phase == "ELABORATE" and not _has_phase(engine, "SCAFFOLD"):
            notice = _json_notice(
                "PHASE_GUARD",
                (
                    f"Current session {session_id} has no scaffold artifacts yet; "
                    "elaborate work is likely premature."
                ),
                "scaffold",
            )
            if enforcement == "strict":
                raise ValueError(notice)
            return notice
        if phase == "ASSESS" and not any(
            a.phase in {"SCAFFOLD", "ELABORATE"} for a in engine.artifacts.values()
        ):
            notice = _json_notice(
                "PHASE_GUARD",
                f"Current session {session_id} has no prior analysis artifacts to assess.",
                "scaffold",
            )
            if enforcement == "strict":
                raise ValueError(notice)
            return notice
    return None


def _store_artifact(
    engine: ThinkingEngine,
    *,
    artifact_id: str,
    kind: str,
    mode: str,
    phase: str,
    model_name: str = "",
    content: dict[str, Any],
    refs: list[str] | None = None,
    connects_to: list[str] | None = None,
    supports: list[str] | None = None,
    contradicts: list[str] | None = None,
    derived_from: list[str] | None = None,
    confidence: float | None = None,
    domain_tags: list[str] | None = None,
    status: str = "active",
    provenance: dict[str, Any] | None = None,
) -> ArtifactRecord:
    record = ArtifactRecord(
        id=artifact_id,
        kind=kind,
        mode=mode,
        phase=phase,
        status=status,
        model_name=model_name,
        domain_tags=list(domain_tags or []),
        content=content,
        refs=list(refs or []),
        connects_to=list(connects_to or []),
        supports=list(supports or []),
        contradicts=list(contradicts or []),
        derived_from=list(derived_from or []),
        confidence=confidence,
        provenance=dict(provenance or {}),
    )
    engine.upsert_artifact(record)
    return record


def _graph_parent_id(parent, info) -> str | None:
    if parent is not None:
        return parent.parent_id
    return info.session_id


async def _auto_graph_if_enabled(parent, items: list[dict], *, source_tag: str) -> list[dict]:
    if parent is None or "graph" not in parent.children:
        return []
    mgr = get_session_manager()
    graph_info = mgr.resolve_backend_session(parent.parent_id, "graph")
    mappings = [
        {"artifact_id": item["id"], "graph_node_id": item["id"]}
        for item in items
    ]

    def _do() -> list[dict]:
        with graph_info.lock:
            try:
                graph_info.engine.execute(
                    "CREATE NODE TABLE IF NOT EXISTS KnowledgeNode ("
                    "id SERIAL PRIMARY KEY, name STRING, description STRING, "
                    "entity_type STRING, confidence DOUBLE, source STRING, "
                    "created_at STRING, domain STRING, authority STRING);"
                )
            except Exception:
                pass
            try:
                graph_info.engine.execute(
                    "CREATE REL TABLE IF NOT EXISTS DerivedFrom ("
                    "FROM KnowledgeNode TO KnowledgeNode, weight DOUBLE, justification STRING, "
                    "source STRING, created_at STRING);"
                )
            except Exception:
                pass
            node_statements: list[str] = []
            edge_statements: list[str] = []
            edge_source = escape_cypher_string(source_tag)
            for item in items:
                desc = escape_cypher_string(
                    str(item.get("_graph_desc", item.get("conclusion", "")))[:200]
                )
                name = escape_cypher_string(item["id"])
                etype = escape_cypher_string(str(item.get("_graph_kind", source_tag)))
                created_at = escape_cypher_string(str(item.get("_created_at")))
                domain_val = escape_cypher_string(str(item.get("domain", "")))
                node_statements.append(
                    "CREATE (k:KnowledgeNode {"
                    f"name: '{name}', "
                    f"description: '{desc}', "
                    f"entity_type: '{etype}', "
                    "confidence: 1.0, "
                    f"source: '{edge_source}', "
                    f"created_at: '{created_at}', "
                    f"domain: '{domain_val}', "
                    "authority: 'inferred'"
                    "})"
                )
                for ref in item.get("connects_to") or []:
                    tgt_id = escape_cypher_string(str(ref))
                    edge_statements.append(
                        "MATCH "
                        f"(a:KnowledgeNode {{name: '{name}'}}) "
                        "OPTIONAL MATCH "
                        f"(b:KnowledgeNode {{name: '{tgt_id}'}}) "
                        "WITH a, b "
                        "WHERE b IS NOT NULL "
                        "CREATE "
                        "(a)-[:DerivedFrom {"
                        "weight: 1.0, "
                        "justification: 'connects_to', "
                        f"source: '{edge_source}', "
                        f"created_at: '{created_at}'"
                        "}]->(b)"
                    )
            if node_statements:
                graph_info.engine.execute(";\n".join(node_statements) + ";")
            if edge_statements:
                graph_info.engine.execute(";\n".join(edge_statements) + ";")
        return mappings

    return await run_sync(_do)


def _require_artifact(
    engine: ThinkingEngine, artifact_id: str, next_tool: str = "reason_index"
) -> ArtifactRecord:
    artifact = engine.get_artifact(artifact_id)
    if artifact is None:
        _raise_json("NOT_FOUND", f"Artifact '{artifact_id}' not found.", next_tool)
    return artifact


async def scaffold(
    model_name: str,
    items: list[dict],
    session_id: str | None = None,
    ctx: _MCPContext | None = None,
) -> str:
    """[SCAFFOLD] Force structured analysis early with a generic model."""
    _validate_enum(model_name, _SCAFFOLD_MODELS, "model_name")
    _, parent, info = await run_sync(
        lambda: _resolve_reason_session(
            session_id, ctx, required_backends=["think"], default_mode="analyze"
        )
    )
    engine = _engine(info)
    mode = _mode_for(info, parent)
    enforcement = _enforcement_for(info, parent)
    notice = _phase_guard(
        mode=mode,
        phase="SCAFFOLD",
        enforcement=enforcement,
        engine=engine,
        session_id=info.session_id,
    )

    validate_items(items, ["problem", "steps", "reasoning", "conclusion"], tool="scaffold")
    created: list[ArtifactRecord] = []
    normalized: list[dict] = []
    with engine.state_lock:
        for item in items:
            refs = collect_item_refs(item)
            created.append(
                _store_artifact(
                    engine,
                    artifact_id=item["id"],
                    kind="scaffold",
                    mode=mode,
                    phase="SCAFFOLD",
                    model_name=model_name,
                    content={
                        "problem": item["problem"],
                        "steps": list(item["steps"]),
                        "reasoning": item["reasoning"],
                        "conclusion": item["conclusion"],
                    },
                    refs=refs,
                    connects_to=list(item.get("connects_to") or []),
                    confidence=item.get("confidence"),
                    domain_tags=item.get("domain_tags") or [],
                )
            )
            normalized.append(
                {
                    "id": item["id"],
                    "conclusion": item["conclusion"],
                    "connects_to": list(item.get("connects_to") or []),
                    "_graph_desc": item["conclusion"],
                    "_graph_kind": "scaffold",
                    "_created_at": created[-1].created_at.isoformat(),
                }
            )
    mappings = await _auto_graph_if_enabled(parent, normalized, source_tag=f"scaffold:{model_name}")
    lines = []
    if notice:
        lines.append(f"Advisory: {notice}")
    lines.extend(
        [
            _session_tool_line(parent, info, mode, "scaffold"),
            f"Model: {model_name} | Items: {len(created)}",
            "Item IDs: " + ", ".join(a.id for a in created),
        ]
    )
    if mappings:
        lines.append("Graph: " + json.dumps(mappings, separators=(",", ":")))
    lines.append("Status: scaffolded")
    return "\n".join(lines)


async def hypothesize(
    items: list[dict],
    session_id: str | None = None,
    ctx: _MCPContext | None = None,
) -> str:
    """[SCAFFOLD] Force falsifiable hypotheses with mechanisms and expected signals."""
    _, parent, info = await run_sync(
        lambda: _resolve_reason_session(
            session_id, ctx, required_backends=["think"], default_mode="analyze"
        )
    )
    engine = _engine(info)
    mode = _mode_for(info, parent)
    enforcement = _enforcement_for(info, parent)
    notice = _phase_guard(
        mode=mode,
        phase="SCAFFOLD",
        enforcement=enforcement,
        engine=engine,
        session_id=info.session_id,
    )
    validate_items(
        items,
        [
            "observation",
            "question",
            "hypothesis",
            "mechanism",
            "variables",
            "assumptions",
            "falsifiability",
            "expected_signals",
        ],
        tool="hypothesize",
    )
    created: list[ArtifactRecord] = []
    normalized: list[dict] = []
    with engine.state_lock:
        for item in items:
            refs = collect_item_refs(item)
            created.append(
                _store_artifact(
                    engine,
                    artifact_id=item["id"],
                    kind="hypothesis",
                    mode=mode,
                    phase="SCAFFOLD",
                    model_name="hypothesize",
                    content={
                        "observation": item["observation"],
                        "question": item["question"],
                        "hypothesis": item["hypothesis"],
                        "mechanism": item["mechanism"],
                        "variables": list(item["variables"]),
                        "assumptions": list(item["assumptions"]),
                        "falsifiability": item["falsifiability"],
                        "expected_signals": list(item["expected_signals"])
                        if isinstance(item["expected_signals"], list)
                        else item["expected_signals"],
                    },
                    refs=refs,
                    connects_to=list(item.get("connects_to") or []),
                    confidence=item.get("confidence"),
                    domain_tags=item.get("domain_tags") or [],
                )
            )
            normalized.append(
                {
                    "id": item["id"],
                    "conclusion": item["hypothesis"],
                    "connects_to": list(item.get("connects_to") or []),
                    "_graph_desc": item["hypothesis"],
                    "_graph_kind": "hypothesis",
                    "_created_at": created[-1].created_at.isoformat(),
                }
            )
    mappings = await _auto_graph_if_enabled(parent, normalized, source_tag="hypothesize")
    lines = []
    if notice:
        lines.append(f"Advisory: {notice}")
    lines.extend(
        [
            _session_tool_line(parent, info, mode, "hypothesize"),
            f"Items: {len(created)}",
            "Item IDs: " + ", ".join(a.id for a in created),
        ]
    )
    if mappings:
        lines.append("Graph: " + json.dumps(mappings, separators=(",", ":")))
    lines.append("Status: hypothesized")
    return "\n".join(lines)


async def argue(
    chain: list[dict],
    session_id: str | None = None,
    ctx: _MCPContext | None = None,
) -> str:
    """[SCAFFOLD] Record a structured argument chain."""
    _, parent, info = await run_sync(
        lambda: _resolve_reason_session(
            session_id, ctx, required_backends=["think"], default_mode="analyze"
        )
    )
    engine = _engine(info)
    mode = _mode_for(info, parent)
    enforcement = _enforcement_for(info, parent)
    notice = _phase_guard(
        mode=mode,
        phase="SCAFFOLD",
        enforcement=enforcement,
        engine=engine,
        session_id=info.session_id,
    )
    if not chain:
        _raise_json("VALIDATION_ERROR", "argue.chain must be a non-empty list.")
    chain_id = uuid.uuid4().hex[:10]
    ids: list[str] = []
    with engine.state_lock:
        for i, item in enumerate(chain):
            if item.get("type") not in _ARGUMENT_TYPES:
                _raise_json("VALIDATION_ERROR", f"argue.chain[{i}].type invalid.", "argue")
            if not item.get("claim"):
                _raise_json("VALIDATION_ERROR", f"argue.chain[{i}] missing claim.", "argue")
            aid = item.get("id") or f"{chain_id}_{i + 1}"
            record = ArgRecord(
                argument_id=aid,
                claim=item["claim"],
                premises=list(item.get("premises") or []),
                conclusion=item.get("conclusion", ""),
                argument_type=item["type"],
                confidence=float(item.get("confidence", 0.5)),
                responds_to=item.get("responds_to"),
                supports=list(item.get("supports") or []),
                contradicts=list(item.get("contradicts") or []),
                strengths=list(item.get("strengths") or []),
                weaknesses=list(item.get("weaknesses") or []),
            )
            engine.add_argument(chain_id, record)
            _store_artifact(
                engine,
                artifact_id=aid,
                kind="argument",
                mode=mode,
                phase="SCAFFOLD",
                content={
                    "claim": item["claim"],
                    "premises": list(item.get("premises") or []),
                    "conclusion": item.get("conclusion", ""),
                    "type": item["type"],
                },
                refs=collect_item_refs(item),
                supports=list(item.get("supports") or []),
                contradicts=list(item.get("contradicts") or []),
                confidence=float(item.get("confidence", 0.5)),
            )
            ids.append(aid)
    lines = []
    if notice:
        lines.append(f"Advisory: {notice}")
    lines.extend(
        [
            _session_tool_line(parent, info, mode, "argue"),
            f"Chain: {chain_id} | Items: {len(ids)}",
            "Item IDs: " + ", ".join(ids),
            "Status: argued",
        ]
    )
    return "\n".join(lines)


async def self_assess(
    items: list[dict],
    session_id: str | None = None,
    ctx: _MCPContext | None = None,
) -> str:
    """[SCAFFOLD] Force knowledge-boundary awareness before deeper work."""
    _, parent, info = await run_sync(
        lambda: _resolve_reason_session(
            session_id, ctx, required_backends=["think"], default_mode="analyze"
        )
    )
    engine = _engine(info)
    mode = _mode_for(info, parent)
    enforcement = _enforcement_for(info, parent)
    notice = _phase_guard(
        mode=mode,
        phase="SCAFFOLD",
        enforcement=enforcement,
        engine=engine,
        session_id=info.session_id,
    )
    validate_items(
        items,
        [
            "task",
            "knowledge_level",
            "known_knowns",
            "known_unknowns",
            "limitations",
            "confidence",
            "recommended_next_step",
        ],
        tool="self_assess",
    )
    ids: list[str] = []
    with engine.state_lock:
        for item in items:
            _validate_enum(item["knowledge_level"], _KNOWLEDGE_LEVELS, "knowledge_level")
            if not item["limitations"]:
                _raise_json("VALIDATION_ERROR", "self_assess.limitations must be non-empty.")
            rec = MonitorRecord(
                monitoring_id=item["id"],
                task=item["task"],
                stage="self-assess",
                overall_confidence=float(item["confidence"]),
                knowledge_assessment={
                    "knowledgeLevel": item["knowledge_level"],
                    "knownKnowns": list(item["known_knowns"]),
                    "knownUnknowns": list(item["known_unknowns"]),
                    "limitations": list(item["limitations"]),
                },
                recommended_approach=item["recommended_next_step"],
            )
            engine.upsert_monitor(rec)
            _store_artifact(
                engine,
                artifact_id=item["id"],
                kind="self_assess",
                mode=mode,
                phase="SCAFFOLD",
                content={
                    "task": item["task"],
                    "knowledge_level": item["knowledge_level"],
                    "known_knowns": list(item["known_knowns"]),
                    "known_unknowns": list(item["known_unknowns"]),
                    "limitations": list(item["limitations"]),
                    "recommended_next_step": item["recommended_next_step"],
                },
                refs=collect_item_refs(item),
                confidence=float(item["confidence"]),
            )
            ids.append(item["id"])
    lines = []
    if notice:
        lines.append(f"Advisory: {notice}")
    lines.extend(
        [
            _session_tool_line(parent, info, mode, "self_assess"),
            f"Items: {len(ids)}",
            "Item IDs: " + ", ".join(ids),
            "Status: assessed",
        ]
    )
    return "\n".join(lines)


async def reason_graph(
    thought: str,
    action: str = "think",
    session_id: str | None = None,
    parent_id: str | None = None,
    node_id: str | None = None,
    children: list[dict] | None = None,
    refs: list[str] | None = None,
    connects_to: list[str] | None = None,
    ctx: _MCPContext | None = None,
) -> str:
    """[ELABORATE] Reason on a graph canvas using short nodes only."""
    from aismartbuddy.tools.think import think_graph

    _validate_enum(action, _REASON_GRAPH_ACTIONS, "action")
    _, parent, info = await run_sync(
        lambda: _resolve_reason_session(
            session_id, ctx, required_backends=["think"], default_mode="analyze"
        )
    )
    engine = _engine(info)
    mode = _mode_for(info, parent)
    enforcement = _enforcement_for(info, parent)
    notice = _phase_guard(
        mode=mode,
        phase="ELABORATE",
        enforcement=enforcement,
        engine=engine,
        session_id=info.session_id,
    )
    limit = _max_node_chars_for(info, parent)
    if len(thought) > limit:
        _raise_json(
            "VALIDATION_ERROR", f"reason_graph.thought exceeds max_node_chars={limit}.", "scaffold"
        )

    if action == "connect":
        if not parent_id:
            _raise_json(
                "VALIDATION_ERROR",
                "reason_graph(action='connect') requires parent_id.",
                "reason_graph",
            )
        action = "think"

    out = await think_graph(
        thought=thought,
        action=action,
        session_id=info.session_id,
        parent_id=parent_id,
        node_id=node_id,
        refs=list(dict.fromkeys(list(refs or []) + list(connects_to or []))),
        children=children,
    )
    node_out = out.splitlines()[0]
    node_identifier = ""
    for part in node_out.split(" | "):
        if part.startswith("Node: "):
            node_identifier = part[len("Node: ") :].strip()
            break
    if node_identifier:
        _store_artifact(
            engine,
            artifact_id=node_identifier,
            kind="reason_graph",
            mode=mode,
            phase="ELABORATE",
            content={"thought": thought, "action": action},
            refs=list(dict.fromkeys(list(refs or []) + list(connects_to or []))),
            connects_to=list(connects_to or []),
        )
    if notice:
        return f"Advisory: {notice}\n{out}"
    return out


async def model_system(
    items: list[dict],
    session_id: str | None = None,
    ctx: _MCPContext | None = None,
) -> str:
    """[ELABORATE] Model multi-scale systems and cross-domain interactions."""
    _, parent, info = await run_sync(
        lambda: _resolve_reason_session(
            session_id, ctx, required_backends=["think"], default_mode="analyze"
        )
    )
    engine = _engine(info)
    mode = _mode_for(info, parent)
    enforcement = _enforcement_for(info, parent)
    notice = _phase_guard(
        mode=mode,
        phase="ELABORATE",
        enforcement=enforcement,
        engine=engine,
        session_id=info.session_id,
    )
    validate_items(
        items,
        ["entity", "role", "boundaries", "inputs", "outputs", "interactions", "assumptions"],
        tool="model_system",
    )
    ids: list[str] = []
    normalized: list[dict] = []
    with engine.state_lock:
        for item in items:
            rec = _store_artifact(
                engine,
                artifact_id=item["id"],
                kind="model_system",
                mode=mode,
                phase="ELABORATE",
                content={
                    "entity": item["entity"],
                    "role": item["role"],
                    "boundaries": item["boundaries"],
                    "inputs": list(item["inputs"]),
                    "outputs": list(item["outputs"]),
                    "interactions": list(item["interactions"]),
                    "assumptions": list(item["assumptions"]),
                },
                refs=collect_item_refs(item),
                connects_to=list(item.get("connects_to") or []),
                confidence=item.get("confidence"),
                domain_tags=item.get("domain_tags") or [],
            )
            ids.append(item["id"])
            normalized.append(
                {
                    "id": item["id"],
                    "conclusion": f"{item['entity']}: {item['role']}",
                    "connects_to": list(item.get("connects_to") or []),
                    "_graph_desc": f"{item['entity']}: {item['role']}",
                    "_graph_kind": "model_system",
                    "_created_at": rec.created_at.isoformat(),
                }
            )
    mappings = await _auto_graph_if_enabled(parent, normalized, source_tag="model_system")
    lines = []
    if notice:
        lines.append(f"Advisory: {notice}")
    lines.extend(
        [
            _session_tool_line(parent, info, mode, "model_system"),
            f"Items: {len(ids)}",
            "Item IDs: " + ", ".join(ids),
        ]
    )
    if mappings:
        lines.append("Graph: " + json.dumps(mappings, separators=(",", ":")))
    lines.append("Status: modeled")
    return "\n".join(lines)


async def mine_patterns(
    items: list[dict],
    session_id: str | None = None,
    ctx: _MCPContext | None = None,
) -> str:
    """[ELABORATE] Store pattern, anomaly, cluster, or cohort findings."""
    _, parent, info = await run_sync(
        lambda: _resolve_reason_session(
            session_id, ctx, required_backends=["think"], default_mode="analyze"
        )
    )
    engine = _engine(info)
    mode = _mode_for(info, parent)
    enforcement = _enforcement_for(info, parent)
    notice = _phase_guard(
        mode=mode,
        phase="ELABORATE",
        enforcement=enforcement,
        engine=engine,
        session_id=info.session_id,
    )
    validate_items(items, ["pattern_type", "finding", "evidence"], tool="mine_patterns")
    ids: list[str] = []
    with engine.state_lock:
        for item in items:
            _store_artifact(
                engine,
                artifact_id=item["id"],
                kind="pattern",
                mode=mode,
                phase="ELABORATE",
                content={
                    "pattern_type": item["pattern_type"],
                    "finding": item["finding"],
                    "evidence": item["evidence"],
                },
                refs=collect_item_refs(item),
                connects_to=list(item.get("connects_to") or []),
                confidence=item.get("confidence"),
                domain_tags=item.get("domain_tags") or [],
            )
            ids.append(item["id"])
    lines = []
    if notice:
        lines.append(f"Advisory: {notice}")
    lines.extend(
        [
            _session_tool_line(parent, info, mode, "mine_patterns"),
            f"Items: {len(ids)}",
            "Item IDs: " + ", ".join(ids),
            "Status: mined",
        ]
    )
    return "\n".join(lines)


async def test_interventions(
    items: list[dict],
    session_id: str | None = None,
    ctx: _MCPContext | None = None,
) -> str:
    """[ELABORATE] Store structured intervention analyses."""
    _, parent, info = await run_sync(
        lambda: _resolve_reason_session(
            session_id, ctx, required_backends=["think"], default_mode="analyze"
        )
    )
    engine = _engine(info)
    mode = _mode_for(info, parent)
    enforcement = _enforcement_for(info, parent)
    notice = _phase_guard(
        mode=mode,
        phase="ELABORATE",
        enforcement=enforcement,
        engine=engine,
        session_id=info.session_id,
    )
    validate_items(
        items,
        [
            "target_ref",
            "intervention",
            "expected_effects",
            "risks",
            "compensations",
            "failure_modes",
        ],
        tool="test_interventions",
    )
    ids: list[str] = []
    with engine.state_lock:
        for item in items:
            _require_artifact(engine, item["target_ref"])
            _store_artifact(
                engine,
                artifact_id=item["id"],
                kind="intervention",
                mode=mode,
                phase="ELABORATE",
                content={
                    "target_ref": item["target_ref"],
                    "intervention": item["intervention"],
                    "expected_effects": list(item["expected_effects"]),
                    "risks": list(item["risks"]),
                    "compensations": list(item["compensations"]),
                    "failure_modes": list(item["failure_modes"]),
                },
                refs=list(dict.fromkeys([item["target_ref"], *collect_item_refs(item)])),
                derived_from=[item["target_ref"]],
                confidence=item.get("confidence"),
            )
            ids.append(item["id"])
    lines = []
    if notice:
        lines.append(f"Advisory: {notice}")
    lines.extend(
        [
            _session_tool_line(parent, info, mode, "test_interventions"),
            f"Items: {len(ids)}",
            "Item IDs: " + ", ".join(ids),
            "Status: tested",
        ]
    )
    return "\n".join(lines)


async def compare_models(
    items: list[dict],
    session_id: str | None = None,
    ctx: _MCPContext | None = None,
) -> str:
    """[ELABORATE] Compare competing explanations or models."""
    _, parent, info = await run_sync(
        lambda: _resolve_reason_session(
            session_id, ctx, required_backends=["think"], default_mode="analyze"
        )
    )
    engine = _engine(info)
    mode = _mode_for(info, parent)
    enforcement = _enforcement_for(info, parent)
    notice = _phase_guard(
        mode=mode,
        phase="ELABORATE",
        enforcement=enforcement,
        engine=engine,
        session_id=info.session_id,
    )
    validate_items(items, ["candidate_refs", "criteria", "verdict"], tool="compare_models")
    ids: list[str] = []
    with engine.state_lock:
        for item in items:
            for ref in item["candidate_refs"]:
                _require_artifact(engine, ref)
            _store_artifact(
                engine,
                artifact_id=item["id"],
                kind="comparison",
                mode=mode,
                phase="ELABORATE",
                content={
                    "candidate_refs": list(item["candidate_refs"]),
                    "criteria": list(item["criteria"]),
                    "verdict": item["verdict"],
                },
                refs=list(dict.fromkeys(list(item["candidate_refs"]) + collect_item_refs(item))),
                derived_from=list(item["candidate_refs"]),
                confidence=item.get("confidence"),
            )
            ids.append(item["id"])
    lines = []
    if notice:
        lines.append(f"Advisory: {notice}")
    lines.extend(
        [
            _session_tool_line(parent, info, mode, "compare_models"),
            f"Items: {len(ids)}",
            "Item IDs: " + ", ".join(ids),
            "Status: compared",
        ]
    )
    return "\n".join(lines)


async def reason_trace(
    target_ref: str,
    supporting_refs: list[str],
    reasoning_steps: list[str],
    session_id: str | None = None,
    opposing_refs: list[str] | None = None,
    unresolved_gaps: list[str] | None = None,
    ctx: _MCPContext | None = None,
) -> str:
    """[ASSESS] Produce a grounded trace using existing artifacts only."""
    _, parent, info = await run_sync(
        lambda: _resolve_reason_session(
            session_id, ctx, required_backends=["think"], default_mode="analyze"
        )
    )
    engine = _engine(info)
    _phase_guard(
        mode=_mode_for(info, parent),
        phase="ASSESS",
        enforcement="strict",
        engine=engine,
        session_id=info.session_id,
    )
    _require_artifact(engine, target_ref)
    if not supporting_refs:
        _raise_json("VALIDATION_ERROR", "reason_trace requires supporting_refs.", "reason_index")
    for ref in supporting_refs:
        _require_artifact(engine, ref)
    for ref in opposing_refs or []:
        _require_artifact(engine, ref)
    if not reasoning_steps:
        _raise_json("VALIDATION_ERROR", "reason_trace requires reasoning_steps.", "reason_trace")
    trace_id = uuid.uuid4().hex[:10]
    _store_artifact(
        engine,
        artifact_id=trace_id,
        kind="reason_trace",
        mode=_mode_for(info, parent),
        phase="ASSESS",
        content={
            "target_ref": target_ref,
            "supporting_refs": list(supporting_refs),
            "opposing_refs": list(opposing_refs or []),
            "reasoning_steps": list(reasoning_steps),
            "unresolved_gaps": list(unresolved_gaps or []),
        },
        refs=list(dict.fromkeys([target_ref, *supporting_refs, *(opposing_refs or [])])),
        supports=list(supporting_refs),
        contradicts=list(opposing_refs or []),
        derived_from=[target_ref],
    )
    return (
        f"Session: {(_graph_parent_id(parent, info) or info.session_id)} | Tool: reason_trace\n"
        f"Trace: {trace_id} | Target: {target_ref}\n"
        "Status: traced"
    )


async def synthesize_conclusion(
    items: list[dict],
    session_id: str | None = None,
    ctx: _MCPContext | None = None,
) -> str:
    """[ASSESS] Final grounded synthesis backed by a prior reason trace."""
    _, parent, info = await run_sync(
        lambda: _resolve_reason_session(
            session_id, ctx, required_backends=["think"], default_mode="analyze"
        )
    )
    engine = _engine(info)
    _phase_guard(
        mode=_mode_for(info, parent),
        phase="ASSESS",
        enforcement="strict",
        engine=engine,
        session_id=info.session_id,
    )
    validate_items(
        items, ["conclusion", "supporting_refs", "reason_trace_ref"], tool="synthesize_conclusion"
    )
    ids: list[str] = []
    with engine.state_lock:
        for item in items:
            trace = _require_artifact(engine, item["reason_trace_ref"])
            if trace.kind != "reason_trace":
                _raise_json(
                    "VALIDATION_ERROR",
                    "reason_trace_ref must point to a reason_trace artifact.",
                    "reason_trace",
                )
            for ref in item["supporting_refs"]:
                _require_artifact(engine, ref)
            for ref in item.get("opposing_refs") or []:
                _require_artifact(engine, ref)
            _store_artifact(
                engine,
                artifact_id=item["id"],
                kind="synthesis",
                mode=_mode_for(info, parent),
                phase="ASSESS",
                status="finalized",
                content={
                    "conclusion": item["conclusion"],
                    "supporting_refs": list(item["supporting_refs"]),
                    "opposing_refs": list(item.get("opposing_refs") or []),
                    "reason_trace_ref": item["reason_trace_ref"],
                },
                refs=list(
                    dict.fromkeys(
                        [
                            item["reason_trace_ref"],
                            *item["supporting_refs"],
                            *(item.get("opposing_refs") or []),
                        ]
                    )
                ),
                supports=list(item["supporting_refs"]),
                contradicts=list(item.get("opposing_refs") or []),
                derived_from=[item["reason_trace_ref"]],
                confidence=item.get("confidence"),
            )
            ids.append(item["id"])
    return (
        f"Session: {_graph_parent_id(parent, info) or info.session_id}"
        " | Tool: synthesize_conclusion\n"
        f"Items: {len(ids)} | IDs: {', '.join(ids)}\n"
        "Status: synthesized"
    )


@size_guarded
async def reason_index(
    session_id: str,
    kind: str | None = None,
    phase: str | None = None,
    status: str | None = None,
    ref: str | None = None,
    limit: int = 20,
) -> str:
    """[ELABORATE] List stored artifacts for targeted retrieval."""
    _, parent, info = await run_sync(
        lambda: _resolve_reason_session(
            session_id, None, required_backends=["think"], default_mode="analyze"
        )
    )
    engine = _engine(info)
    artifacts = engine.list_artifacts(kind=kind, phase=phase, ref=ref, status=status)
    payload = {
        "session_id": _graph_parent_id(parent, info) or info.session_id,
        "count": len(artifacts),
        "items": [
            {
                "id": a.id,
                "kind": a.kind,
                "phase": a.phase,
                "status": a.status,
                "summary": _artifact_summary(a),
            }
            for a in artifacts[: max(1, limit)]
        ],
    }
    return json.dumps(payload, indent=2)


@size_guarded
async def reason_get(session_id: str, artifact_id: str) -> str:
    """[ELABORATE] Fetch one artifact and its immediate links."""
    _, parent, info = await run_sync(
        lambda: _resolve_reason_session(
            session_id, None, required_backends=["think"], default_mode="analyze"
        )
    )
    engine = _engine(info)
    artifact = _require_artifact(engine, artifact_id)
    linked_ids = list(
        dict.fromkeys(
            artifact.refs
            + artifact.connects_to
            + artifact.supports
            + artifact.contradicts
            + artifact.derived_from
        )
    )
    payload = {
        "session_id": _graph_parent_id(parent, info) or info.session_id,
        "artifact": _artifact_to_dict(artifact),
        "linked": [
            {
                "id": linked.id,
                "kind": linked.kind,
                "phase": linked.phase,
                "summary": _artifact_summary(linked),
            }
            for linked in [engine.get_artifact(i) for i in linked_ids]
            if linked is not None
        ],
    }
    return json.dumps(payload, indent=2)


@size_guarded
async def reason_refs(session_id: str, artifact_id: str) -> str:
    """[ELABORATE] Query inbound references to an artifact."""
    _, parent, info = await run_sync(
        lambda: _resolve_reason_session(
            session_id, None, required_backends=["think"], default_mode="analyze"
        )
    )
    engine = _engine(info)
    _require_artifact(engine, artifact_id)
    matches = []
    for artifact in engine.list_artifacts(ref=artifact_id):
        matches.append(
            {
                "id": artifact.id,
                "kind": artifact.kind,
                "phase": artifact.phase,
                "summary": _artifact_summary(artifact),
            }
        )
    return json.dumps(
        {
            "session_id": _graph_parent_id(parent, info) or info.session_id,
            "artifact_id": artifact_id,
            "count": len(matches),
            "matches": matches,
        },
        indent=2,
    )


async def session_resume(session_id: str, last_n: int = 5) -> str:
    """[INFRA] Resume a session with compact operational context."""
    mgr = get_session_manager()
    parent = None
    try:
        parent = mgr.get_parent_session(session_id)
        info = mgr.resolve_backend_session(session_id, "think")
    except ValueError:
        info = mgr.get_session(session_id)
    engine = _engine(info)
    with engine.state_lock:
        artifacts = engine.list_artifacts()
        recent_artifacts = engine.recent_artifacts(max(1, last_n))
        by_kind = Counter()
        by_phase = Counter()
        for artifact in artifacts:
            by_kind[artifact.kind] += 1
            by_phase[artifact.phase] += 1

        holon_counts: dict[str, int] = Counter()
        for node in engine.holon_nodes.values():
            for membership in node.memberships:
                holon_counts[membership["holarchy_id"]] += 1

        holarchies = []
        for hid, root_id in engine.holon_holarchies.items():
            root = engine.get_holon(root_id)
            holarchies.append(
                {
                    "holarchy_id": hid,
                    "root": root.name if root else root_id,
                    "holon_count": holon_counts.get(hid, 0),
                }
            )

        evaluations = [
            {
                "id": ev.id,
                "status": ev.status,
                "running_score": ev.running_score,
                "final_score": ev.final_score,
            }
            for ev in engine.get_evaluations()
        ]
        pending_iterations = [
            {
                "iteration_id": iid,
                "goal": rec.goal,
                "best_metric": rec.best_metric,
                "attempts": len(rec.attempts),
            }
            for iid, rec in engine.iterations.items()
            if not rec.is_complete
        ]
    payload = {
        "session": {
            "session_id": session_id,
            "project_id": info.project_id,
            "mode": _mode_for(info, parent),
            "enforcement": _enforcement_for(info, parent),
            "backends": sorted(parent.children.keys()) if parent else [info.session_type],
            "created_at": (parent.created_at if parent else info.created_at).isoformat(),
        },
        "artifact_summary": {
            "by_kind": dict(by_kind),
            "by_phase": dict(by_phase),
        },
        "last_n_artifacts": [
            {
                "id": a.id,
                "kind": a.kind,
                "phase": a.phase,
                "summary": _artifact_summary(a),
            }
            for a in recent_artifacts
        ],
        "active_holarchies": holarchies,
        "active_evaluations": evaluations,
        "pending_iterations": pending_iterations,
    }
    return json.dumps(payload, indent=2)


@size_guarded
async def session_export(session_id: str) -> str:
    """[INFRA] Export the current session state as JSON."""
    mgr = get_session_manager()
    parent = None
    try:
        parent = mgr.get_parent_session(session_id)
        info = mgr.resolve_backend_session(session_id, "think")
    except ValueError:
        info = mgr.get_session(session_id)
    engine = _engine(info)
    payload = {
        "session_id": session_id,
        "mode": _mode_for(info, parent),
        "enforcement": _enforcement_for(info, parent),
        "artifacts": [_artifact_to_dict(a) for a in engine.list_artifacts()],
        "iterations": list(engine.iterations.keys()),
        "holarchies": list(engine.holon_holarchies.keys()),
        "evaluations": list(engine.evaluations.keys()),
    }
    return json.dumps(payload, indent=2)


async def workflow_validate(session_id: str) -> str:
    """[INFRA] Validate mode/phase coverage and sequencing."""
    mgr = get_session_manager()
    parent = None
    try:
        parent = mgr.get_parent_session(session_id)
        info = mgr.resolve_backend_session(session_id, "think")
    except ValueError:
        info = mgr.get_session(session_id)
    engine = _engine(info)
    artifacts = [engine.get_artifact(aid) for aid in engine.iter_artifact_ids(reverse=False)]
    artifacts = [artifact for artifact in artifacts if artifact is not None]
    mode = _mode_for(info, parent)
    current_phase = artifacts[-1].phase if artifacts else "NONE"
    violations: list[dict[str, str]] = []
    missing_steps: list[str] = []
    coverage = Counter(a.phase.lower() for a in artifacts)
    if mode == "analyze":
        saw_scaffold = False
        saw_trace = False
        for art in artifacts:
            if art.phase == "SCAFFOLD":
                saw_scaffold = True
            if art.kind == "reason_trace":
                saw_trace = True
            if art.phase == "ELABORATE" and not saw_scaffold:
                violations.append(
                    {
                        "artifact_id": art.id,
                        "expected_phase": "SCAFFOLD",
                        "actual_phase": art.phase,
                    }
                )
            if art.kind == "synthesis" and not saw_trace:
                violations.append(
                    {
                        "artifact_id": art.id,
                        "expected_phase": "ASSESS(reason_trace)",
                        "actual_phase": art.phase,
                    }
                )
        if not any(a.phase == "SCAFFOLD" for a in artifacts):
            missing_steps.append("No scaffold artifacts found")
        if any(a.kind == "synthesis" for a in artifacts) and not any(
            a.kind == "reason_trace" for a in artifacts
        ):
            missing_steps.append("No reason_trace before synthesize")
    recommendation = "Workflow looks coherent."
    if missing_steps:
        recommendation = missing_steps[0]
    elif violations:
        recommendation = (
            "Consider restructuring with scaffold before elaborate "
            "and reason_trace before synthesis."
        )
    payload = {
        "current_mode": mode,
        "current_phase": current_phase,
        "phase_violations": violations,
        "missing_steps": missing_steps,
        "coverage": {
            "scaffold": coverage.get("scaffold", 0),
            "elaborate": coverage.get("elaborate", 0),
            "assess": coverage.get("assess", 0),
        },
        "recommendation": recommendation,
    }
    return json.dumps(payload, indent=2)


async def extract_findings_from_sql(
    session_id: str,
    query: str,
    finding_kind: str = "sql_finding",
) -> str:
    """[ELABORATE] Run SQL and wrap each row as a finding artifact."""
    mgr = get_session_manager()
    try:
        parent = mgr.get_parent_session(session_id)
        think_info = mgr.resolve_backend_session(session_id, "think")
        sql_info = mgr.resolve_backend_session(session_id, "sql")
    except ValueError:
        _raise_json(
            "VALIDATION_ERROR",
            "extract_findings_from_sql requires a unified session with think and sql backends.",
            "session_create",
        )
    engine = _engine(think_info)
    notice = _phase_guard(
        mode=_mode_for(think_info, parent),
        phase="ELABORATE",
        enforcement=_enforcement_for(think_info, parent),
        engine=engine,
        session_id=think_info.session_id,
    )
    table, _ = await run_with_lock(
        sql_info,
        lambda: sql_info.engine.execute_windowed(query, limit=mgr.max_rows),
    )
    row_dicts = [] if table is None else table.to_pylist()
    ids: list[str] = []
    with engine.state_lock:
        for row_dict in row_dicts:
            artifact_id = uuid.uuid4().hex[:10]
            _store_artifact(
                engine,
                artifact_id=artifact_id,
                kind=finding_kind,
                mode=_mode_for(think_info, parent),
                phase="ELABORATE",
                content={str(key): value for key, value in row_dict.items()},
                provenance={"backend": "sql", "query": query},
            )
            ids.append(artifact_id)
    lines = []
    if notice:
        lines.append(f"Advisory: {notice}")
    lines.extend(
        [
            f"Session: {session_id} | Tool: extract_findings_from_sql",
            f"Rows: {len(row_dicts)} | Artifacts: {len(ids)}",
            "Item IDs: " + ", ".join(ids[:20]) + (" ..." if len(ids) > 20 else ""),
            "Status: extracted",
        ]
    )
    return "\n".join(lines)


async def extract_findings_from_graph(
    session_id: str,
    query: str,
    finding_kind: str = "graph_finding",
) -> str:
    """[ELABORATE] Run Cypher and wrap each row as a finding artifact."""
    mgr = get_session_manager()
    try:
        parent = mgr.get_parent_session(session_id)
        think_info = mgr.resolve_backend_session(session_id, "think")
        graph_info = mgr.resolve_backend_session(session_id, "graph")
    except ValueError:
        _raise_json(
            "VALIDATION_ERROR",
            "extract_findings_from_graph requires a unified session with think and graph backends.",
            "session_create",
        )
    engine = _engine(think_info)
    notice = _phase_guard(
        mode=_mode_for(think_info, parent),
        phase="ELABORATE",
        enforcement=_enforcement_for(think_info, parent),
        engine=engine,
        session_id=think_info.session_id,
    )
    table, _ = await run_with_lock(
        graph_info,
        lambda: graph_info.engine.execute_windowed(query, limit=mgr.max_rows),
    )
    row_dicts = [] if table is None else table.to_pylist()
    ids: list[str] = []
    with engine.state_lock:
        for row_dict in row_dicts:
            artifact_id = uuid.uuid4().hex[:10]
            _store_artifact(
                engine,
                artifact_id=artifact_id,
                kind=finding_kind,
                mode=_mode_for(think_info, parent),
                phase="ELABORATE",
                content={str(key): value for key, value in row_dict.items()},
                provenance={"backend": "graph", "query": query},
            )
            ids.append(artifact_id)
    lines = []
    if notice:
        lines.append(f"Advisory: {notice}")
    lines.extend(
        [
            f"Session: {session_id} | Tool: extract_findings_from_graph",
            f"Rows: {len(row_dicts)} | Artifacts: {len(ids)}",
            "Item IDs: " + ", ".join(ids[:20]) + (" ..." if len(ids) > 20 else ""),
            "Status: extracted",
        ]
    )
    return "\n".join(lines)


async def brainstorm(
    items: list[dict],
    session_id: str | None = None,
    topic: str | None = None,
    ctx: _MCPContext | None = None,
) -> str:
    """[DIVERGE] Generate divergent ideas without early convergence."""
    _, parent, info = await run_sync(
        lambda: _resolve_reason_session(
            session_id, ctx, required_backends=["think"], default_mode="diverge"
        )
    )
    engine = _engine(info)
    mode = _mode_for(info, parent)
    enforcement = _enforcement_for(info, parent)
    notice = _phase_guard(
        mode=mode,
        phase="DIVERGE",
        enforcement=enforcement,
        engine=engine,
        session_id=info.session_id,
    )
    if not items:
        _raise_json("VALIDATION_ERROR", "brainstorm.items must be a non-empty list.")
    ids: list[str] = []
    with engine.state_lock:
        for i, item in enumerate(items):
            if not item.get("idea"):
                _raise_json(
                    "VALIDATION_ERROR", f"brainstorm.items[{i}] missing idea.", "brainstorm"
                )
            artifact_id = item.get("id") or uuid.uuid4().hex[:10]
            _store_artifact(
                engine,
                artifact_id=artifact_id,
                kind="brainstorm",
                mode=mode,
                phase="DIVERGE",
                content={
                    "idea": item["idea"],
                    "spark": item.get("spark", ""),
                    "topic": topic or item.get("topic", ""),
                },
                refs=collect_item_refs(item),
                confidence=item.get("confidence"),
            )
            ids.append(artifact_id)
    lines = []
    if notice:
        lines.append(f"Advisory: {notice}")
    lines.extend(
        [
            _session_tool_line(parent, info, mode, "brainstorm"),
            f"Items: {len(ids)}",
            "Item IDs: " + ", ".join(ids),
            "Status: brainstormed",
        ]
    )
    return "\n".join(lines)


async def iterate(
    items: list[dict],
    session_id: str | None = None,
    goal: str | None = None,
    higher_is_better: bool = True,
    ctx: _MCPContext | None = None,
) -> str:
    """[ITERATE] Track build-test-learn attempts with an optional metric ratchet."""
    _, parent, info = await run_sync(
        lambda: _resolve_reason_session(
            session_id, ctx, required_backends=["think"], default_mode="iterate"
        )
    )
    engine = _engine(info)
    mode = _mode_for(info, parent)
    enforcement = _enforcement_for(info, parent)
    notice = _phase_guard(
        mode=mode,
        phase="ITERATE",
        enforcement=enforcement,
        engine=engine,
        session_id=info.session_id,
    )
    if not items:
        _raise_json("VALIDATION_ERROR", "iterate.items must be a non-empty list.")
    iteration_id = uuid.uuid4().hex[:10]
    best_metric: float | None = None
    metric_name: str | None = None
    metric_history: list[float] = []
    attempts: list[dict] = []
    results: list[dict] = []
    with engine.state_lock:
        for i, item in enumerate(items):
            for field in ("approach", "result", "learning"):
                if not item.get(field):
                    _raise_json(
                        "VALIDATION_ERROR", f"iterate.items[{i}] missing {field}.", "iterate"
                    )
            entry = {
                "approach": item["approach"],
                "result": item["result"],
                "learning": item["learning"],
            }
            if item.get("metric_value") is not None:
                mv = float(item["metric_value"])
                metric_name = item.get("metric_name") or metric_name or "metric"
                if best_metric is None:
                    best_metric = mv
                    is_improvement = True
                else:
                    is_improvement = mv > best_metric if higher_is_better else mv < best_metric
                    if is_improvement:
                        best_metric = mv
                metric_history.append(mv)
                stagnation = False
                if len(metric_history) >= 3:
                    window = metric_history[-3:]
                    if higher_is_better:
                        stagnation = all(v < (best_metric or float("-inf")) for v in window)
                    else:
                        stagnation = all(v > (best_metric or float("inf")) for v in window)
                suggested_action = (
                    "radical_change" if stagnation else ("keep" if is_improvement else "adjust")
                )
                entry.update(
                    {
                        "metric_name": metric_name,
                        "metric_value": mv,
                        "best_so_far": best_metric,
                        "is_improvement": is_improvement,
                        "stagnation_detected": stagnation,
                        "suggested_action": suggested_action,
                    }
                )
            else:
                entry.update(
                    {
                        "best_so_far": best_metric,
                        "is_improvement": False,
                        "stagnation_detected": False,
                        "suggested_action": "continue",
                    }
                )
            attempts.append(entry)
            results.append(entry)
        engine.iterations[iteration_id] = IterationRecord(
            iteration_id=iteration_id,
            goal=goal or "iterate",
            attempts=attempts,
            metric_name=metric_name,
            best_metric=best_metric,
            metric_history=metric_history,
            higher_is_better=higher_is_better,
        )
        _store_artifact(
            engine,
            artifact_id=iteration_id,
            kind="iteration",
            mode=mode,
            phase="ITERATE",
            content={"goal": goal or "iterate", "attempts": attempts},
            confidence=None,
        )
    lines = []
    if notice:
        lines.append(f"Advisory: {notice}")
    lines.extend(
        [
            _session_tool_line(parent, info, mode, "iterate"),
            f"Iteration: {iteration_id} | Attempts: {len(items)}",
            "Results: " + json.dumps(results, separators=(",", ":")),
            "Status: recorded",
        ]
    )
    return "\n".join(lines)


async def think_debug(
    items: list[dict],
    session_id: str | None = None,
    ctx: _MCPContext | None = None,
) -> str:
    """[ITERATE] Apply systematic debugging to one or more issues."""
    _, parent, info = await run_sync(
        lambda: _resolve_reason_session(
            session_id, ctx, required_backends=["think"], default_mode="iterate"
        )
    )
    engine = _engine(info)
    mode = _mode_for(info, parent)
    enforcement = _enforcement_for(info, parent)
    notice = _phase_guard(
        mode=mode,
        phase="ITERATE",
        enforcement=enforcement,
        engine=engine,
        session_id=info.session_id,
    )
    validate_items(
        items, ["issue", "approach", "steps", "findings", "resolution"], tool="think_debug"
    )
    ids: list[str] = []
    with engine.state_lock:
        for item in items:
            _validate_enum(item["approach"], _DEBUG_APPROACHES, "approach")
            artifact_id = item["id"]
            _store_artifact(
                engine,
                artifact_id=artifact_id,
                kind="debug",
                mode=mode,
                phase="ITERATE",
                content={
                    "issue": item["issue"],
                    "approach": item["approach"],
                    "steps": list(item["steps"]),
                    "findings": item["findings"],
                    "resolution": item["resolution"],
                },
                refs=collect_item_refs(item),
                confidence=item.get("confidence"),
            )
            ids.append(artifact_id)
    lines = []
    if notice:
        lines.append(f"Advisory: {notice}")
    lines.extend(
        [
            _session_tool_line(parent, info, mode, "think_debug"),
            f"Items: {len(ids)}",
            "Item IDs: " + ", ".join(ids),
            "Status: debugged",
        ]
    )
    return "\n".join(lines)
