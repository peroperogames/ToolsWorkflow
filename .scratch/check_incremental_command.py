"""Local check: a review asked for by a comment judges the delta since last time.

These repositories do not run a workflow on push, so the push event's
`before...after` never exists. The session records the commit each review looked at;
the next review compares it with the head.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "review"))

import main

HEAD = "7a940271" + "0" * 32
OTHER = "d39bbbc1" + "0" * 32


def reviewed_before(sha=OTHER):
    """A session that has reviewed the PR before, at `sha`."""
    return [
        main.turn_record("## full diff", "open", sha),
        {"role": "assistant", "content": "ok"},
        main.turn_record("## comment", "comment", sha),
    ]


payload = {"comment": {"body": "@perotoolsbot review"}}

# 1. A session that reviewed an earlier commit: the delta is the review.
assert main._incremental_command_review(reviewed_before(OTHER), HEAD) is True
print("reviewed before at another commit -> incremental")

# 2. Same commit as last time: nothing to diff, so it is a full review.
assert main._incremental_command_review(reviewed_before(HEAD), HEAD) is False
print("head unchanged since the last review -> full")

# 3. No session at all: first review, full.
assert main._incremental_command_review([], HEAD) is False
assert main._incremental_command_review(
    [main.turn_record("## full diff", "push", OTHER)]  # no bootstrap, no review
    , HEAD
) is False
print("first review -> full")

# 4. The escape hatch, and only for the review command.
assert main.review_asked_for_full("issue_comment", {"comment": {"body": "@perotoolsbot review full"}})
assert main.review_asked_for_full("issue_comment", {"comment": {"body": "@perotoolsbot review --full"}})
assert main.review_asked_for_full("issue_comment", {"comment": {"body": "@perotoolsbot review：全部"}})
assert main.review_asked_for_full("issue_comment", {"comment": {"body": "@perotoolsbot review: 全量再看一遍"}})
assert not main.review_asked_for_full("issue_comment", {"comment": {"body": "@perotoolsbot review"}})
assert not main.review_asked_for_full("issue_comment", {"comment": {"body": "@perotoolsbot review(o2)"}})
assert not main.review_asked_for_full("issue_comment", {"comment": {"body": "@perotoolsbot rebuild full"}})
assert not main.review_asked_for_full("pull_request", {"action": "synchronize"})
print("`review full` / `--full` / `全部` / `全量` ask for the whole pull request; nothing else does")

# 5. The delta really is what the model is handed: the session's commit compared
#    with the head, not the whole pull request.
class FakeGitHub:
    def __init__(self):
        self.compared = []

    def compare(self, owner, repo, before, after):
        self.compared.append((before, after))
        return [{"filename": "Core/Command/Operation/CommandOperation.Extensions.cs",
                 "patch": "@@ -54,3 +54,4 @@\n }", "additions": 1, "deletions": 0}]


gh = FakeGitHub()
turns = main.build_review_turns(
    gh, "o", "r", {"head": {"sha": HEAD}}, [], {},
    reviewed_before(OTHER), [], [],
    True, extra_context="", threads="",
)
assert gh.compared == [(OTHER, HEAD)], gh.compared
text = turns[-1]["content"]
assert "CommandOperation.Extensions.cs" in text, text[:400]
assert "Incremental Review Mode" in text, text[:400]
print("the turn is the compare(last reviewed, head) diff with the incremental directive")
print("OK")
