"""Local check: the step log says what each call was about."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "review"))

import main

lab = main._tool_call_label

cases = [
    (
        {"function": {"name": "read_file", "arguments": '{"path": "Core/Thing.cs"}'}},
        "read_file(Core/Thing.cs)",
    ),
    (
        {"function": {"name": "read_file", "arguments": '{"path": "Core/Thing.cs", "offset": 201}'}},
        "read_file(Core/Thing.cs@201)",
    ),
    (
        {"function": {"name": "get_file_diff", "arguments": '{"path": "a.cs"}'}},
        "get_file_diff(a.cs)",
    ),
    ({"function": {"name": "finish", "arguments": '{"verdict": "comment"}'}}, "finish"),
    ({"function": {"name": "read_file", "arguments": "not json"}}, "read_file"),
    ({"function": {"name": "list_threads", "arguments": "{}"}}, "list_threads"),
    ({"function": {"name": "resolve_thread", "arguments": '{"thread_id": "T1"}'}}, "resolve_thread(T1)"),
    ({}, "?"),
]

for call, want in cases:
    got = lab(call)
    print(f"  {got:<34} {'ok' if got == want else 'WANT ' + want}")
    assert got == want, (got, want)
print("OK")
