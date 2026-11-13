"""Local check: a settle with nothing left open approves, and does not crash.

Production path from AccessKing PR #3: 41 threads, every one resolved, "No unresolved
bot review threads to consider." → "Approved: nothing left open." → AttributeError,
because `decide_resolved_threads` returned `0` on that path while the caller assigns
into the outcome.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "review"))

import main

APPROVED = []


class FakeGitHub:
    def list_review_threads(self, owner, repo, number):
        return [
            {
                "id": f"T{i}",
                "path": "Core/Event/EventBus/EventBus.cs",
                "line": 10 + i,
                "isResolved": True,
                "comments": {"nodes": [{"author": {"login": "perotoolsbot[bot]"},
                                        "body": "x", "databaseId": i}]},
            }
            for i in range(41)
        ]

    def list_reviews(self, owner, repo, number):
        return []

    def post_review(self, owner, repo, number, body, event="COMMENT"):
        APPROVED.append((event, body))
        return {"id": 1}


pr = {"head": {"sha": "abc123"}, "number": 3}

outcome = main.settle_threads_and_approve(
    None, FakeGitHub(), "o", "r", 3, pr, conversation="", language="cn"
)
print(f"outcome={outcome!r}")
assert isinstance(outcome, main.SettleOutcome), type(outcome)
assert outcome.approved is True, outcome
assert outcome.resolved == 0 and outcome.open == [], outcome
assert APPROVED and APPROVED[0][0] == "APPROVE", APPROVED
print("--- nothing left open: the outcome is a SettleOutcome and the approval is posted")

# The other early exits must be outcomes too, or the same crash comes back by a
# different door.
class BrokenGitHub(FakeGitHub):
    def list_review_threads(self, owner, repo, number):
        raise RuntimeError("boom")


outcome = main.settle_threads_and_approve(
    None, BrokenGitHub(), "o", "r", 3, pr, conversation="", language="cn"
)
assert isinstance(outcome, main.SettleOutcome) and outcome.unknown, outcome
print("--- the thread list failing: an outcome marked unknown, no crash")


class BadDecider:
    def chat(self, messages, temperature=0.0):
        return "not json at all"


class OneOpen(FakeGitHub):
    def list_review_threads(self, owner, repo, number):
        threads = super().list_review_threads(owner, repo, number)
        threads[0]["isResolved"] = False
        return threads


outcome = main.settle_threads_and_approve(
    BadDecider(), OneOpen(), "o", "r", 3, pr, conversation="", language="cn"
)
assert isinstance(outcome, main.SettleOutcome) and outcome.unknown, outcome
print("--- the decider answering nonsense: an outcome marked unknown, no crash")
print("OK")
