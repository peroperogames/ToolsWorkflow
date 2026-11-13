"""Local check: the prompt says what a finding is, and what a duplicate is.

PeroSerde #11 (2026-11-06) is the reason both sentences exist: 14 comments on 1,215
added lines, half of them preferences with no victim, and one defect posted twice —
the second time in English, on another line, fourteen minutes after the first.
"""

import sys
from pathlib import Path

prompt = Path(__file__).resolve().parent.parent / "review" / "prompt.md"
text = prompt.read_text(encoding="utf-8")

failures = []


def ok(msg):
    print("ok   " + msg)


def bad(msg):
    print("FAIL " + msg)
    failures.append(msg)


def has(fragment):
    return " ".join(fragment.split()) in " ".join(text.split())


if has("A finding needs a victim: what breaks, for whom, and when."):
    ok("guideline 10 asks for the victim before the comment")
else:
    bad("the prompt has no bar for what counts as a finding")

for preference in (
    "could take a `CancellationToken`",
    "`ConfigureAwait(false)` on a library `await`",
    "XML documentation on new members",
    "ten near-identical methods worth refactoring",
    "raises the minimum compiler version",
):
    if has(preference):
        ok(f"a preference is named as one: {preference[:40]}")
    else:
        bad(f"the prompt lost the preference example {preference!r}")

if has("**A defect that repeats is one finding.**"):
    ok("a repeated defect is one comment, not one per place")
else:
    bad("nothing stops one comment per symptom")

if has("not in another language") and has("Write in the review language only"):
    ok("a duplicate in another language is still a duplicate")
else:
    bad("the prompt lets a translation through the duplicate check")

if has("a second instance of the same defect is not a different form"):
    ok("a resolved thread covers the defect wherever it recurs")
else:
    bad("a resolved thread only covers its own line")

if has("Missing tests for code whose risk is concrete"):
    ok("the anchor rule asks for concrete risk, not a wish list")
else:
    bad("the anchor rule still invites a design wish list")

for number in ("10. **A finding needs a victim", "4. **Never state the same finding twice**"):
    if number in " ".join(text.split()):
        ok(f"the numbered rule survives: {number.split('**')[1][:40]}")
    else:
        bad(f"missing numbered rule: {number!r}")

print()
if failures:
    print("%d check(s) failed" % len(failures))
    sys.exit(1)
print("OK")
