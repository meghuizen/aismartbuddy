"""Reasoning-framework catalog and deterministic route selection.

The catalog keeps detailed framework guidance out of MCP tool descriptions.
It does not perform model inference: the calling AI may select an explicit
intent, while ``auto`` produces a transparent keyword-based recommendation
with alternatives.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Final

_FRAMEWORK_ROOT = Path(__file__).resolve().parent / "thinking-frameworks"
_SOURCE_FRAMEWORK_ROOT = Path(__file__).resolve().parents[2] / "thinking-frameworks"


@dataclass(frozen=True, slots=True)
class FrameworkSpec:
    id: str
    name: str
    filename: str
    summary: str
    intents: tuple[str, ...]
    warning: str = ""


@dataclass(frozen=True, slots=True)
class RouteStep:
    phase: str
    tool: str
    purpose: str


@dataclass(frozen=True, slots=True)
class ReasoningRoute:
    intent: str
    depth: str
    frameworks: tuple[str, ...]
    steps: tuple[RouteStep, ...]
    alternatives: tuple[str, ...]
    confidence: float
    rationale: str
    completion_criteria: tuple[str, ...]


_FRAMEWORKS: Final[tuple[FrameworkSpec, ...]] = (
    FrameworkSpec(
        "interference",
        "Interference Protocol",
        "interference.md",
        "Generate novel concepts by forcing incompatible structures into contact.",
        ("generate_novelty",),
        "Do not use for ordinary optimization inside a known frame.",
    ),
    FrameworkSpec(
        "derivation",
        "Derivation Engine",
        "derivation.md",
        "Investigate what is true through claims, sources, and adversarial evidence.",
        ("investigate_truth", "extract_knowledge"),
    ),
    FrameworkSpec(
        "compositional",
        "Compositional Reasoning",
        "compositional.md",
        "Expose a system's structural skeleton and part-whole relationships.",
        ("understand_system",),
    ),
    FrameworkSpec(
        "diagrammatic",
        "Diagrammatic Rewriting",
        "diagrammatic.md",
        "Simplify structure through transformations and irreducible forms.",
        ("understand_system", "solve_problem"),
    ),
    FrameworkSpec(
        "axiomatic",
        "Axiomatic Derivation",
        "axiomatic.md",
        "Test which assumptions are necessary and derive consequences from constraints.",
        ("investigate_truth", "challenge"),
        "Do not substitute axioms for empirical evidence.",
    ),
    FrameworkSpec(
        "strategic-resolution",
        "Strategic Resolution",
        "strategic-resolution.md",
        "Frame, diagnose, solve, and implement a complex real-world problem.",
        ("solve_problem",),
        "Do not select solutions before diagnosis.",
    ),
    FrameworkSpec(
        "kuba",
        "KUBA Communication",
        "kuba.md",
        "Check whether communication supplies knowledge, understanding, belief, and action.",
        ("communicate",),
    ),
    FrameworkSpec(
        "narrative-transfer",
        "Narrative Transfer",
        "narrative-transfer.md",
        "Transfer a mental model through a structured explanatory narrative.",
        ("communicate",),
    ),
    FrameworkSpec(
        "interview-extraction",
        "Extraction Protocol",
        "interview-extraction.md",
        "Recover knowledge, assumptions, and requirements from a person or stakeholder.",
        ("extract_knowledge",),
    ),
    FrameworkSpec(
        "systems-dynamics",
        "Systems Dynamics",
        "systems-dynamics.md",
        "Model feedback, delays, accumulations, and behavior over time.",
        ("understand_system", "solve_problem"),
    ),
    FrameworkSpec(
        "decisions-uncertainty",
        "Decision Under Uncertainty",
        "decisions-uncertainty.md",
        "Choose robustly when probabilities, outcomes, or information are incomplete.",
        ("make_decision",),
    ),
    FrameworkSpec(
        "redteam",
        "Red Team",
        "redteam.md",
        "Attack a claim, plan, or design to reveal failure modes and blind spots.",
        ("challenge",),
    ),
    FrameworkSpec(
        "learning-loop",
        "Learning Loop",
        "learning-loop.md",
        "Turn outcomes and failures into retained improvements and next experiments.",
        ("learn_from_outcome",),
    ),
    FrameworkSpec(
        "architect",
        "Architecture Review",
        "architect.md",
        "Review software structure, interfaces, and leverage.",
        ("understand_system", "challenge"),
    ),
    FrameworkSpec(
        "docs-researcher",
        "Documentation Research",
        "docs-researcher.md",
        "Investigate technical claims from authoritative documentation.",
        ("investigate_truth", "extract_knowledge"),
    ),
    FrameworkSpec(
        "plan-reviewer",
        "Plan Review",
        "plan-reviewer.md",
        "Review a plan for omissions, ordering errors, and unverifiable outcomes.",
        ("challenge", "solve_problem"),
    ),
)


_BASE_ROUTES: Final[dict[str, tuple[RouteStep, ...]]] = {
    "investigate_truth": (
        RouteStep("SCAFFOLD", "think_science", "Separate observations, questions, and hypotheses."),
        RouteStep("ELABORATE", "think_evidence", "Record provenance and support chains."),
        RouteStep("ASSESS", "think_monitor", "Calibrate claims and unresolved uncertainty."),
    ),
    "understand_system": (
        RouteStep(
            "SCAFFOLD", "think_model", "Map structure with first principles or systems dynamics."
        ),
        RouteStep(
            "ELABORATE", "think_topology", "Represent roles, edges, and transferable structure."
        ),
        RouteStep("ASSESS", "think_monitor", "Record scope limits and missing behavior."),
    ),
    "solve_problem": (
        RouteStep("SCAFFOLD", "think_model", "Frame root causes before proposing solutions."),
        RouteStep(
            "ELABORATE", "think_hypothesis", "Compare causal explanations and decisive tests."
        ),
        RouteStep("ELABORATE", "think_decide", "Evaluate solutions against constraints."),
        RouteStep("ASSESS", "think_monitor", "Challenge confidence, limitations, and follow-up."),
    ),
    "make_decision": (
        RouteStep(
            "SCAFFOLD", "think_decide", "Define the decision, options, criteria, and uncertainty."
        ),
        RouteStep(
            "ELABORATE", "think_argue", "Challenge the leading option and synthesize tradeoffs."
        ),
        RouteStep(
            "ASSESS", "think_monitor", "Calibrate recommendation confidence and reversibility."
        ),
    ),
    "generate_novelty": (
        RouteStep(
            "SCAFFOLD", "think_interfere", "Suspend the current frame and introduce source laws."
        ),
        RouteStep("ELABORATE", "think_topology", "Test structural coherence and analogies."),
        RouteStep("ASSESS", "think_monitor", "Separate novelty from unsupported plausibility."),
    ),
    "challenge": (
        RouteStep("SCAFFOLD", "think_model", "Run a pre-mortem or assumptions audit."),
        RouteStep("ELABORATE", "think_argue", "Construct the strongest counter-case."),
        RouteStep("ASSESS", "think_monitor", "Record surviving claims and remaining risks."),
    ),
    "communicate": (
        RouteStep(
            "SCAFFOLD", "think_model", "Select KUBA and define the audience's missing state."
        ),
        RouteStep("ELABORATE", "think_graph", "Build the narrative or action sequence."),
        RouteStep(
            "ASSESS", "think_monitor", "Check ambiguity, belief gaps, and likely misreading."
        ),
    ),
    "extract_knowledge": (
        RouteStep("SCAFFOLD", "think_model", "Expose assumptions and information gaps."),
        RouteStep("ELABORATE", "think_evidence", "Store extracted claims with provenance."),
        RouteStep("ASSESS", "think_monitor", "Distinguish known, inferred, and still unknown."),
    ),
    "learn_from_outcome": (
        RouteStep("SCAFFOLD", "iterate", "Capture the outcome, expectation, and learning target."),
        RouteStep("ELABORATE", "think_model", "Analyze causes and transferable lessons."),
        RouteStep("ASSESS", "think_monitor", "Commit the next test and monitoring criteria."),
    ),
}


_INTENT_KEYWORDS: Final[dict[str, tuple[str, ...]]] = {
    "investigate_truth": (
        "research",
        "evidence",
        "true",
        "verify",
        "investigate",
        "source",
        "claim",
    ),
    "understand_system": (
        "architecture",
        "system",
        "structure",
        "feedback",
        "model",
        "relationship",
    ),
    "solve_problem": ("solve", "problem", "fix", "root cause", "diagnose", "improve"),
    "make_decision": ("decide", "choose", "option", "tradeoff", "uncertain", "risk"),
    "generate_novelty": ("invent", "novel", "creative", "new idea", "innovate", "brainstorm"),
    "challenge": ("review", "attack", "red team", "failure", "weakness", "critique"),
    "communicate": ("explain", "communicate", "persuade", "presentation", "audience", "message"),
    "extract_knowledge": ("interview", "requirements", "extract", "documentation", "stakeholder"),
    "learn_from_outcome": ("retrospective", "postmortem", "learn", "outcome", "experiment"),
}


class FrameworkCatalog:
    """Deep module for framework discovery, guidance, and route selection."""

    def __init__(self) -> None:
        self._by_id = {spec.id: spec for spec in _FRAMEWORKS}

    def list(self) -> tuple[FrameworkSpec, ...]:
        return _FRAMEWORKS

    def get(self, framework_id: str) -> FrameworkSpec:
        normalized = framework_id.strip().lower()
        try:
            return self._by_id[normalized]
        except KeyError as exc:
            allowed = ", ".join(sorted(self._by_id))
            raise ValueError(f"Unknown framework '{framework_id}'. Allowed: {allowed}") from exc

    def guidance(self, framework_id: str) -> str:
        spec = self.get(framework_id)
        for root in (_FRAMEWORK_ROOT, _SOURCE_FRAMEWORK_ROOT):
            path = root / spec.filename
            if path.is_file():
                return path.read_text(encoding="utf-8")
        raise RuntimeError(
            f"Framework guidance '{spec.filename}' is not installed. Reinstall the package."
        )

    def recommend(self, task: str, intent: str = "auto", depth: str = "standard") -> ReasoningRoute:
        clean_task = task.strip()
        if not clean_task:
            raise ValueError("task is required")
        normalized_depth = depth.strip().lower()
        if normalized_depth not in {"quick", "standard", "deep"}:
            raise ValueError("depth must be quick, standard, or deep")

        selected, confidence, alternatives = self._select_intent(clean_task, intent)
        base = _BASE_ROUTES[selected]
        if normalized_depth == "quick":
            steps = (base[0], base[-1]) if len(base) > 1 else base
        elif normalized_depth == "deep":
            red_team = RouteStep(
                "ASSESS",
                "think_argue",
                "Run an adversarial pass before final calibration.",
            )
            steps = (*base[:-1], red_team, base[-1])
        else:
            steps = base

        frameworks = tuple(spec.id for spec in _FRAMEWORKS if selected in spec.intents)
        rationale = (
            f"Intent '{selected}' matches the task and routes through "
            + " -> ".join(step.tool for step in steps)
            + "."
        )
        return ReasoningRoute(
            intent=selected,
            depth=normalized_depth,
            frameworks=frameworks,
            steps=tuple(steps),
            alternatives=alternatives,
            confidence=confidence,
            rationale=rationale,
            completion_criteria=(
                "The task and constraints are explicit.",
                "Important claims are linked to evidence or marked as inference.",
                "At least one competing explanation or counter-case was considered.",
                "Uncertainty, limitations, and the next action are recorded.",
            ),
        )

    def _select_intent(self, task: str, intent: str) -> tuple[str, float, tuple[str, ...]]:
        normalized = intent.strip().lower()
        if normalized != "auto":
            if normalized not in _BASE_ROUTES:
                allowed = ", ".join(("auto", *sorted(_BASE_ROUTES)))
                raise ValueError(f"intent must be one of: {allowed}")
            alternatives = tuple(key for key in _BASE_ROUTES if key != normalized)[:2]
            return normalized, 1.0, alternatives

        text = task.lower()
        scores = {
            key: sum(1 for keyword in keywords if keyword in text)
            for key, keywords in _INTENT_KEYWORDS.items()
        }
        ranked = sorted(scores, key=lambda key: (-scores[key], key))
        selected = ranked[0]
        top_score = scores[selected]
        if top_score == 0:
            selected = "solve_problem"
            alternatives = ("investigate_truth", "understand_system")
            return selected, 0.35, alternatives
        alternatives = tuple(key for key in ranked if key != selected)[:2]
        confidence = min(0.95, 0.55 + 0.1 * top_score)
        return selected, confidence, alternatives


framework_catalog = FrameworkCatalog()


def render_catalog() -> str:
    """Return compact Markdown suitable for an MCP resource."""

    lines = ["# Reasoning Frameworks", ""]
    for spec in framework_catalog.list():
        lines.append(f"- `{spec.id}` — **{spec.name}**: {spec.summary}")
        if spec.warning:
            lines.append(f"  Warning: {spec.warning}")
    lines.append("")
    lines.append("Use suggest_reasoning to select and sequence existing tools.")
    return "\n".join(lines)
