"""Local check: two gates keep two status comments.

PeroSerde #9 is a solution and a UPM package, so the checks stage runs both gates.
Both reported through one living comment, and the second edit erased the first: the
pull request showed ".NET: 编译通过，单元测试通过。" while the Unity result — 64 EditMode
tests, platform table and all — existed only in that comment's edit history.
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
    def __init__(self, line):
        self.ok = True
        self.tests_reported = True
        self.tests_broke = False
        self.test_failures = []
        self.platform_runs = []
        self.hung_alone = False
        self.test_tail = ""
        self.test_log_path = ""
        self.compile_errors = []
        self.skipped = []
        self.details = []
        self.line = line

    def summary(self):
        return self.line

    def outcome(self):
        return self.line


class GitHub:
    """A pull request whose App cannot create check runs."""

    def __init__(self):
        self.comments = []
        self.posted = 0
        self.updated = 0

    def create_check_run(self, *args, **kwargs):
        return None

    def list_comments(self, owner, repo, number):
        return [dict(comment) for comment in self.comments]

    def post_comment(self, owner, repo, number, body):
        self.posted += 1
        self.comments.append(
            {"id": len(self.comments) + 1, "body": body,
             "user": {"login": "perotoolsbot[bot]"}}
        )
        return {"id": len(self.comments)}

    def update_comment(self, owner, repo, comment_id, body):
        self.updated += 1
        self.comments[comment_id - 1]["body"] = body
        return {"id": comment_id}


config = types.SimpleNamespace(dry_run=False)
files = [{"filename": "a.cs", "patch": "+x"}]


def report(gh, result, label):
    main.report_build_result(
        gh, "o", "r", 9, files, config, "abc123", result, label=label
    )


gh = GitHub()
report(gh, Result("| 平台 | 用例 |\n| EditMode | 64 |"), "Unity")
report(gh, Result(".NET: compiled and 64 tests passed."), ".NET")

bodies = [comment["body"] for comment in gh.comments]
print("--- comments:", [b.splitlines()[0][:40] for b in bodies])
if gh.posted == 2:
    ok("each gate's result gets its own comment")
else:
    bad(f"two gates produced {gh.posted} comment(s), expected 2")

if len(bodies) == 2 and "EditMode" in bodies[0] and ".NET:" in bodies[1]:
    ok("the second gate does not edit the first gate's comment away")
else:
    bad(f"one gate overwrote the other: {bodies!r}")

markers = [main.build_status_marker(label) for label in ("Unity", ".NET")]
if all(marker in body for marker, body in zip(markers, bodies)):
    ok("each comment carries the marker of its own label")
else:
    bad(f"markers do not match their comments: {bodies!r}")

# A re-run of both gates edits both comments, and posts nothing.
gh = GitHub()
gh.comments = [
    {"id": 1, "body": "old unity\n\n" + markers[0], "user": {"login": "perotoolsbot[bot]"}},
    {"id": 2, "body": "old dotnet\n\n" + markers[1], "user": {"login": "perotoolsbot[bot]"}},
]
report(gh, Result("| EditMode | 65 |"), "Unity")
report(gh, Result(".NET: 65 tests."), ".NET")
if gh.posted == 0 and gh.updated == 2:
    ok("a re-run edits both gates' comments and adds none")
else:
    bad(f"re-run: posted={gh.posted}, updated={gh.updated}")

if "65" in gh.comments[0]["body"] and "65" in gh.comments[1]["body"]:
    ok("both comments carry this run's numbers")
else:
    bad(f"stale bodies: {[c['body'][:40] for c in gh.comments]!r}")

print()
if failures:
    print("%d check(s) failed" % len(failures))
    sys.exit(1)
print("OK")
