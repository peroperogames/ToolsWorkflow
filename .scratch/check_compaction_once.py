"""Local check: compaction is not retried every step when it cannot help.

RhythmAce-Neo #36 arrived with ~265k tokens against a 200k budget — 164 changed files
whose diff is part of the first request and cannot be compacted away — and ran the
three passes on all six of its steps to free 3k each time. The attempt now happens
once, and only repeats when the transcript has grown a quarter past the level it
could not get under.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "review"))

import main

failures = []


def ok(msg):
    print("ok   " + msg)


def bad(msg):
    print("FAIL " + msg)
    failures.append(msg)


budget = 200_000

# The first request is the diff itself, over budget and not compactable.
huge = "x" * (budget * 4)  # estimate_tokens caps at 4 ASCII chars per token
messages = [
    {"role": "system", "content": "prompt"},
    {"role": "user", "content": huge},
] + [{"role": "tool", "tool_call_id": f"c{i}", "content": "y" * 4000} for i in range(10)]

report, floor = main.compact_for_step(messages, budget, 0)
print(f"--- first attempt: after={report['after'] // 1000}k tokens, floor={floor // 1000}k")
if report is not None and floor > budget:
    ok("the first attempt runs and records how big it could not fix")
else:
    bad(f"the first attempt did not behave: report={report}, floor={floor}")

again, floor = main.compact_for_step(messages, budget, floor)
if again is None:
    ok("the next step skips the attempt instead of repeating it")
else:
    bad("the next step ran the passes again")

# Growth below the retry watermark is still skipped.
messages.append({"role": "tool", "tool_call_id": "c11", "content": "z" * 4000})
again, floor = main.compact_for_step(messages, budget, floor)
if again is None:
    ok("a little more content does not re-trigger it")
else:
    bad("a small growth re-triggered the passes")

# A quarter more than the floor is worth trying again: there is something new.
grown = floor * 5 // 4 + 1000
messages.append({"role": "user", "content": "w" * (grown * 4)})
again, floor = main.compact_for_step(messages, budget, floor)
if again is not None:
    ok("growing a quarter past the floor tries again")
else:
    bad("growth past the floor did not try again")

# A transcript that is merely over budget but compactable still compacts every time.
small = [{"role": "system", "content": "prompt"}, {"role": "user", "content": "diff" * 2000}]
small += [{"role": "tool", "tool_call_id": f"t{i}", "content": "y" * 20000} for i in range(40)]
report, floor = main.compact_for_step(small, 60_000, 0)
if report is not None and report["after"] <= 60_000 and floor == 0:
    ok("a compactable transcript is compacted and needs no floor")
else:
    bad(f"a compactable transcript behaved oddly: {report}, floor={floor}")

print()
if failures:
    print("%d check(s) failed" % len(failures))
    sys.exit(1)
print("OK")
