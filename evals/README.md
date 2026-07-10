# Reasoning quality evaluations

`reasoning_quality.json` is the stable 16-task corpus for comparing:

1. the same AI without AISmartBuddy;
2. the current tools without `suggest_reasoning`;
3. the route-aware tools.

Run each condition three times with the same model and sampling settings. Blind
the condition before scoring. Each task lists applicable quality dimensions;
score them from 0–10 and record tool calls, advertised-context size, and output
tokens. The automated test validates routing expectations. Outcome comparison
requires a configured external AI client and is intentionally outside the MCP
runtime.

