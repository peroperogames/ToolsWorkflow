"""Local check: the transcript budget is a knob, and compaction uses it.

200k is a cost and latency budget, not the model's window: every agent step re-sends
the whole transcript, so the number multiplies by the step count. It is therefore
something a repository may raise for huge pull requests — with a floor (below it,
compaction fires on every step) and a ceiling (above it, the bill is the problem).
"""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "review"))

import main

BASE_ENV = {"GITHUB_TOKEN": "x", "OPENAI_API_KEY": "y"}


def budget(extra=None):
    """load_config with a clean environment — the process may carry the real ones."""
    saved = dict(os.environ)
    try:
        for name in ("AGENT_CONTEXT_TOKENS", "MAX_TOKENS_PER_CHUNK"):
            os.environ.pop(name, None)
        os.environ.update(BASE_ENV)
        os.environ.update(extra or {})
        return main.load_config().agent_context_tokens
    finally:
        os.environ.clear()
        os.environ.update(saved)


assert budget() == 200_000, budget()
print("--- unset: the default 200k")

assert budget({"AGENT_CONTEXT_TOKENS": "800000"}) == 800_000, budget({"AGENT_CONTEXT_TOKENS": "800000"})
print("--- a caller can raise it (800k)")

assert budget({"AGENT_CONTEXT_TOKENS": " 400000 "}) == 400_000
print("--- whitespace is tolerated")

# Below the floor compaction would fire on every step, which is the failure the token
# budget was introduced for.
assert budget({"AGENT_CONTEXT_TOKENS": "5000"}) == main.MIN_AGENT_CONTEXT_TOKENS
print(f"--- below the floor it is clamped to {main.MIN_AGENT_CONTEXT_TOKENS}")

# Above it the bill is the problem; the number is still accepted but bounded.
assert budget({"AGENT_CONTEXT_TOKENS": "9000000"}) == main.MAX_AGENT_CONTEXT_CEILING
print(f"--- above the ceiling it is clamped to {main.MAX_AGENT_CONTEXT_CEILING}")

assert budget({"AGENT_CONTEXT_TOKENS": "lots"}) == 200_000
assert budget({"AGENT_CONTEXT_TOKENS": ""}) == 200_000
print("--- nonsense and empty fall back to the default")

# Compaction honours the budget it is given: the same transcript is compacted at 20k
# and left alone at 200k.
tool_results = [
    {"role": "tool", "tool_call_id": f"c{i}", "content": "x" * 4000}
    for i in range(60)
]
messages = [{"role": "system", "content": "prompt"}] + tool_results

small = main.compact_agent_messages([dict(m) for m in messages], budget_tokens=20_000)
large = main.compact_agent_messages([dict(m) for m in messages], budget_tokens=200_000)
print(f"--- 60 tool results at 20k: stubbed={small['stubbed']} {small['before']} -> {small['after']} tokens")
print(f"--- the same at 200k:      stubbed={large['stubbed']} {large['before']} -> {large['after']} tokens")
assert small["stubbed"] > 0 and small["after"] < small["before"], small
assert large["stubbed"] == 0, large

# And the default argument is still the default constant.
assert main.compact_agent_messages([dict(m) for m in messages])["stubbed"] == 0
print("--- the default argument is unchanged")
print("OK")
