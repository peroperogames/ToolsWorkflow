"""Local check: nothing before the review may skip the review.

RhythmAce-Neo #89: the artifact upload was refused ("Artifact storage quota has been
hit"), the upload step failed, and the review step — which came after it and was gated
on the implicit `success()` — logged `outcome=skipped`. The build, the tests and the
static analysis had already run.
"""

import sys
from pathlib import Path

import yaml

action = Path(__file__).resolve().parent.parent / "review" / "action.yml"
steps = yaml.safe_load(action.read_text(encoding="utf-8"))["runs"]["steps"]
by_name = {step.get("name"): step for step in steps}

failures = []


def ok(msg):
    print("ok   " + msg)


def bad(msg):
    print("FAIL " + msg)
    failures.append(msg)


review = by_name.get("Review and settle the threads")
if not review:
    bad("the review step is gone")
else:
    condition = str(review.get("if") or "")
    print("--- review step if:", condition)
    if condition.startswith("!cancelled()"):
        ok("the review runs whatever happened before it, except on a cancelled run")
    else:
        bad(
            "the review step is gated on the steps before it: a failed upload skips "
            "the review (that is #89)"
        )
    if "closed" in condition:
        ok("a closed pull request is still not reviewed")

upload = by_name.get("Upload the reports")
if not upload:
    bad("the upload step is gone")
else:
    if upload.get("continue-on-error") is True:
        ok("a refused artifact upload does not fail the job")
    else:
        bad("the upload can fail the whole job, which reads as 'the review broke'")

# The stages are the three way split; none of them may be continue-on-error, so a
# crash still stops the run.
for name in ("Build and test the pull request", "Run the static analysis"):
    step = by_name.get(name)
    if step and step.get("continue-on-error"):
        bad(f"{name!r} is continue-on-error, so a crash would pass for a result")
    else:
        ok(f"{name!r} fails the run when it crashes")

print()
if failures:
    print("%d check(s) failed" % len(failures))
    sys.exit(1)
print("OK")
