# Plan: Add depends_on to ThoughtNode

## Context
ThoughtNode has parent→child (hierarchy) but no sibling dependencies. Adding `depends_on: list[str]` enables project planning patterns (critical path, backward scheduling) using existing think_graph tools.

## Changes
1. `engines/thinking_engine.py` — Add `depends_on: list[str]` field to ThoughtNode dataclass
2. `tools/think.py` — Add `depends_on` parameter to think_graph function. Add "dependencies" to think_graph_validate check types.
3. `tests/test_think_tools.py` — Test depends_on in think_graph, test dependency cycle detection in validate

## TLDR
Add one field (`depends_on`) to ThoughtNode + dependency validation. No new tools.
