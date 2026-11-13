"""Local check: a new run is handed a bounded amount of session history.

The session is every earlier run of the pull request. It used to be handed over in
full and only trimmed past 200k tokens, so one-line push #11 paid for every file
push #1..#10 had read — on every step of its own run.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "review"))

import main

CJK = "这是一个被评审过的文件内容，包含代码与注释。"


def session_records(runs=10, per_run_chars=3500):
    """A session shaped like a pull request reviewed ten times."""
    records = []
    for run in range(runs):
        records.append({
            "role": "user",
            "content": f"## 推送 {run}\n" + CJK * (per_run_chars // len(CJK)),
        })
        records.append({
            "role": "assistant", "content": "看几个文件。",
            "tool_calls": [{
                "id": f"c{run}", "type": "function",
                "function": {"name": "read_file", "arguments": '{"path":"a.cs"}'},
            }],
        })
        records.append({
            "role": "tool", "tool_call_id": f"c{run}",
            "content": "FILE " + CJK * (per_run_chars // len(CJK)),
        })
    return records


new_turns = [
    {"role": "user", "content": "## 最新推送\n" + CJK * 40 + main.INCREMENTAL_DIRECTIVE},
    {"role": "assistant", "content": "", "tool_calls": [{
        "id": "n1", "type": "function",
        "function": {"name": "read_file", "arguments": '{"path":"b.cs"}'},
    }]},
    {"role": "tool", "tool_call_id": "n1", "content": "NEW FILE " + CJK * 40},
]

# 1. Ten runs of history: bounded, and the newest run's turns survive untouched.
records = session_records()
full = 1 + len(main.session.to_messages(records)) + len(new_turns)
before = main.messages_tokens(
    [{"role": "system", "content": "SYS"}] + main.session.to_messages(records) + new_turns
)
messages = main.agent_messages("SYS", records, new_turns)
after = main.messages_tokens(messages)
print(f"history {before} tokens -> handed {after} tokens "
      f"({len(messages)} of {full} messages)")
assert before > main.MAX_AGENT_HISTORY_TOKENS, before
assert after <= main.MAX_AGENT_HISTORY_TOKENS + main.estimate_tokens("SYS") + 200, after
assert messages[0] == {"role": "system", "content": "SYS"}
assert "not repeated here" in messages[1]["content"], messages[1]["content"]
# The newest run's own turns are exactly what was passed in, still at the end.
assert messages[-3:] == new_turns, messages[-3:]
# No tool result without the call that produced it.
for index, message in enumerate(messages):
    if message.get("role") == "tool":
        assert any(
            m.get("role") == "assistant" and m.get("tool_calls") for m in messages[:index]
        ), index
print("newest turns intact, older runs replaced by a note, no orphan tool result")

# 2. A short history is handed over whole.
short = session_records(runs=1, per_run_chars=200)
messages = main.agent_messages("SYS", short, new_turns)
assert len(messages) == 1 + len(short) + len(new_turns), len(messages)
assert not any("not repeated here" in (m.get("content") or "") for m in messages)
print("a session that fits is handed over whole")

# 3. A first review has no session at all: nothing to trim.
messages = main.agent_messages("SYS", [], new_turns)
assert len(messages) == 1 + len(new_turns), len(messages)
print("a first review gets exactly its turns")
print("OK")
