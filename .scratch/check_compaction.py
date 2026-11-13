"""Local check: compaction gets the transcript under budget, and stays there.

The failure this reproduces is from an AccessKing review: 22 steps, "Context
compacted" on every one, and the prompt sitting at ~500k tokens throughout — i.e.
compaction freed exactly enough for the next step and nothing more.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "review"))

import main

CJK = "这是一段中文评审意见，包含代码符号与标点。"
ASCII = "The quick brown fox jumps over the lazy dog. "


def tokens_ratio():
    chinese = CJK * 100  # 2100 chars
    english = ASCII * 100  # 4500 chars
    zh = main.estimate_tokens(chinese)
    en = main.estimate_tokens(english)
    print(f"chinese {len(chinese)} chars -> {zh} tokens (~{len(chinese) / zh:.1f} chars/token)")
    print(f"english {len(english)} chars -> {en} tokens (~{len(english) / en:.1f} chars/token)")
    # The old rule (4 chars/token) said 100k tokens for a 400k-char Chinese
    # transcript; the real figure is ~400k. That is the whole bug.
    assert zh >= len(chinese) * 0.8, zh
    assert 3.0 <= len(english) / en <= 5.0, en


def session_transcript(previous_turns=48, turn_chars=5000):
    """A transcript shaped like a PR reviewed many times: the session is the base."""
    messages = [{"role": "system", "content": CJK * 500}]
    for index in range(previous_turns):
        messages.append({"role": "user", "content": f"diff {index} " + CJK * (turn_chars // len(CJK))})
        messages.append({"role": "assistant", "content": "ok", "tool_calls": [
            {"id": f"c{index}", "type": "function",
             "function": {"name": "read_file", "arguments": '{"path":"a.cs"}'}}
        ]})
        messages.append({"role": "tool", "tool_call_id": f"c{index}", "content": "RESULT " + ASCII * 40})
    # The newest request, and the steps the model has taken since.
    messages.append({"role": "user", "content": "current review request " + CJK * 200})
    for step in range(3):
        messages.append({"role": "assistant", "content": "", "tool_calls": [
            {"id": f"n{step}", "type": "function",
             "function": {"name": "read_file", "arguments": '{"path":"b.cs"}'}}
        ]})
        messages.append({"role": "tool", "tool_call_id": f"n{step}", "content": "NEW " + ASCII * 400})
    return messages


tokens_ratio()

budget = main.MAX_AGENT_CONTEXT_TOKENS
target = int(budget * main.COMPACT_TARGET_RATIO)

# 1. A long-lived session: the base alone is over budget, so stubbing results
#    cannot be enough — the older turns have to go.
messages = session_transcript()
before = main.messages_tokens(messages)
report = main.compact_agent_messages(messages)
print(f"1. {before // 1000}k -> {report['after'] // 1000}k tokens "
      f"({report['stubbed']} stubbed, {report['dropped']} dropped)")
assert before > budget, before
assert report["dropped"] > 0, report
assert report["after"] <= target, (report, target)
# Progressive, not all-or-nothing: some of the older turns are still there.
assert any("diff " in (m.get("content") or "") for m in messages), "every earlier turn was dropped"
assert messages[0]["role"] == "system"
assert messages[1]["role"] == "user", messages[1]
assert "earlier conversation omitted" in messages[1]["content"], messages[1]["content"]
# The newest request and the model's last reads survive: it is mid-investigation.
assert any("current review request" in (m.get("content") or "") for m in messages)
assert any((m.get("content") or "").startswith("NEW ") for m in messages)
# No tool result was left without the call that produced it.
for index, message in enumerate(messages):
    if message.get("role") == "tool":
        assert any(
            m.get("role") == "assistant" and m.get("tool_calls") for m in messages[:index]
        ), index
print("   the newest request and its reads survive, no orphan tool result")

# 2. The user's complaint: after a compaction the next step must not compact
#    again. Three more steps of reading cost ~10k tokens each at most.
for step in range(3):
    messages.append({"role": "assistant", "content": "", "tool_calls": [
        {"id": f"x{step}", "type": "function",
         "function": {"name": "read_file", "arguments": '{"path":"c.cs"}'}}
    ]})
    messages.append({"role": "tool", "tool_call_id": f"x{step}", "content": "MORE " + ASCII * 500})
    again = main.compact_agent_messages(messages)
    print(f"2. step +{step + 1}: {again['before'] // 1000}k tokens, "
          f"stubbed={again['stubbed']} dropped={again['dropped']}")
    assert again["stubbed"] == 0 and again["dropped"] == 0, again
print("   three further steps, no compaction at all")

# 3. A transcript that fits is left alone.
small = [
    {"role": "system", "content": "sys"},
    {"role": "user", "content": "diff"},
    {"role": "assistant", "content": "", "tool_calls": [
        {"id": "a", "type": "function", "function": {"name": "read_file", "arguments": "{}"}}
    ]},
    {"role": "tool", "tool_call_id": "a", "content": "some file"},
]
report = main.compact_agent_messages(small)
assert report == {"stubbed": 0, "dropped": 0, "before": report["before"],
                  "after": report["before"]}, report
print("3. a transcript that fits is untouched")

# 4. Chunking uses the same estimate: two 70k-character patches are 140k tokens of
#    Chinese but 35k tokens of English, so only the first pair has to be split.
chinese_diff = [{"filename": "a.cs", "patch": CJK * 3400}, {"filename": "b.cs", "patch": CJK * 3400}]
ascii_diff = [{"filename": "a.cs", "patch": ASCII * 1700}, {"filename": "b.cs", "patch": ASCII * 1700}]
zh_chunks = main.chunk_files(chinese_diff, main.DEFAULT_MAX_TOKENS_PER_CHUNK)
en_chunks = main.chunk_files(ascii_diff, main.DEFAULT_MAX_TOKENS_PER_CHUNK)
print(f"4. chinese diff -> {len(zh_chunks)} chunk(s), ascii diff -> {len(en_chunks)} chunk(s)")
assert len(zh_chunks) == 2, len(zh_chunks)
assert len(en_chunks) == 1, len(en_chunks)
print("OK")
