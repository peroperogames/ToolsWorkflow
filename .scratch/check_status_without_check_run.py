"""Local check: a green build's result is visible even without a check run.

PeroLog PR #10 compiled and passed both test suites, and the pull request said nothing
about it: the check run (the tick, with the summary) was refused because the App lacks
`Checks: write`, and a green build posts no comment. The log line promised "the comment
still carries the result" while nothing carried it.

So when the check run cannot be created and nothing has been posted, the summary goes
into a comment — one living comment, updated on a re-run rather than stacked.
"""

import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "review"))

import main

failures = []


def ok(msg):
    print("ok   " + msg)


def bad(msg):
    print("FAIL " + msg)
    failures.append(msg)


class Result:
    """The bits of UnityResult report_build_result reads."""

    def __init__(self, ok=True, tests_reported=True, tests_broke=False):
        self.ok = ok
        self.tests_reported = tests_reported
        self.tests_broke = tests_broke
        self.test_failures = []
        self.platform_runs = []
        self.hung_alone = False
        self.test_tail = ""
        self.test_log_path = ""
        self.compile_errors = []
        self.skipped = []
        self.details = []

    def summary(self):
        return "| Platform | Result |\n| --- | --- |\n| EditMode | 42 passed |"

    def outcome(self):
        return "Unity: compiled and tested."


class GitHub:
    def __init__(self, check_allowed=True, existing=None):
        self.check_allowed = check_allowed
        self.comments = list(existing or [])
        self.posted = []
        self.updated = []
        self.check_runs = 0

    def create_check_run(self, owner, repo, head_sha, name, conclusion, title, summary):
        self.check_runs += 1
        return {"id": 1} if self.check_allowed else None

    def list_comments(self, owner, repo, number):
        return list(self.comments)

    def post_comment(self, owner, repo, number, body):
        self.posted.append(body)
        return {"id": 99}

    def update_comment(self, owner, repo, comment_id, body):
        self.updated.append((comment_id, body))
        return {"id": comment_id}


config = types.SimpleNamespace(dry_run=False)
files = [{"filename": "a.cs", "patch": "+x"}]


def report(gh, result):
    main.report_build_result(gh, "o", "r", 10, files, config, "abc123", result)


# 1. Green, check run allowed: the tick is the report, and no comment is posted.
gh = GitHub(check_allowed=True)
report(gh, Result())
if gh.check_runs == 1 and gh.posted == []:
    ok("a green build with a working check run stays silent")
else:
    bad(f"green+check: check_runs={gh.check_runs}, posted={len(gh.posted)}")

# 2. Green, check run refused: the result goes into the comment instead.
gh = GitHub(check_allowed=False)
report(gh, Result())
if gh.check_runs == 1 and len(gh.posted) == 1:
    body = gh.posted[0]
    print("--- the fallback comment:")
    print("   ", body.replace("\n", " | ")[:140])
    if "EditMode" in body and main.build_status_marker("Unity") in body:
        ok("a green build without a check run posts its summary, marked")
    else:
        bad("the fallback comment is missing the summary or its marker")
else:
    bad(f"green+no-check: check_runs={gh.check_runs}, posted={len(gh.posted)}")

# 3. A failing build posts its comment as it always did, and not a second one when the
#    check run is refused too.
gh = GitHub(check_allowed=False)
report(gh, Result(ok=False))
if len(gh.posted) == 1:
    ok("a failing build posts exactly one status comment")
else:
    bad(f"failing build posted {len(gh.posted)} comment(s)")

# 4. The comment lives: an earlier one with the marker is edited, not duplicated.
earlier = {"id": 7, "body": "old summary\n\n" + main.build_status_marker("Unity"),
           "user": {"login": "perotoolsbot[bot]"}}
gh = GitHub(check_allowed=False, existing=[earlier])
report(gh, Result())
if gh.updated and not gh.posted:
    ok("a re-run edits the earlier status comment instead of adding another")
else:
    bad(f"re-run: updated={len(gh.updated)}, posted={len(gh.posted)}")

# 5. Somebody else's comment is never touched, even if it carries the marker.
foreign = {"id": 8, "body": "mine\n\n" + main.build_status_marker("Unity"), "user": {"login": "tanyyt"}}
gh = GitHub(check_allowed=False, existing=[foreign])
report(gh, Result())
if gh.posted and not gh.updated:
    ok("a human comment with the marker is left alone")
else:
    bad(f"foreign comment: updated={len(gh.updated)}, posted={len(gh.posted)}")

# 6. A run that produced no report is "neutral", and still says so in the comment.
gh = GitHub(check_allowed=False)
report(gh, Result(tests_reported=False))
if len(gh.posted) == 1:
    ok("a build with no test report still reports (neutral) through the comment")
else:
    bad("no-report run posted nothing")

print()
if failures:
    print("%d check(s) failed" % len(failures))
    sys.exit(1)
print("OK")
