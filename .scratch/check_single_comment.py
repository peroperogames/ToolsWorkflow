"""Local check: a `rebuild` run leaves one comment, not two."""

import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "review"))

import main
import unity_runner


class FakeGitHub:
    def __init__(self):
        self.comments = []

    def post_comment(self, owner, repo, number, body):
        self.comments.append(body)
        return {"id": 1}

    def create_check_run(self, *args, **kwargs):
        return None

    def list_comments(self, owner, repo, number):
        return []


def failed_result():
    result = unity_runner.UnityResult()
    result.ran = True
    result.compiled = True
    result.tests_reported = False
    result.tests_broke = True
    result.platform_failures = [
        {"platform": "PlayMode", "exit": 6, "timed_out": False, "timeout": 600}
    ]
    result.test_tail = ["Error: Test run did not complete."]
    return result


# The command is recognised without the model, which is what makes this decidable
# in the checks stage at all.
payload = {"comment": {"body": "@perotoolsbot rebuild"}}
invocation = main._comment_invocation(payload)
assert invocation and invocation[1].name == "rebuild", invocation
assert not main._comment_invocation({"comment": {"body": "@perotoolsbot review"}})[1].name == "rebuild"

config = types.SimpleNamespace(dry_run=False, language="zh")

# A rebuild run: the review step's reply is the report, so the checks stage keeps
# quiet.
main._COMMAND_POSTS_RESULT = True
gh = FakeGitHub()
main.report_build_result(
    gh, "o", "r", 3, [], config, "sha", failed_result(), label="Unity"
)
assert gh.comments == [], gh.comments
print("rebuild run: no status comment from the checks stage")

# Any other run: it posts, as before.
main._COMMAND_POSTS_RESULT = False
gh = FakeGitHub()
main.report_build_result(
    gh, "o", "r", 3, [], config, "sha", failed_result(), label="Unity"
)
assert len(gh.comments) == 1, gh.comments
print("every other run: the status comment is posted")

# And the reply it is left to does carry the whole report.
main._COMMAND_POSTS_RESULT = True
body = main.rebuild_comment_body(
    "Unity package com.prpr.uiqueen",
    "**构建与测试**\n\n⚠️ Unity: 编译通过；PlayMode 测试运行失败（Unity 退出码 6），没有产出报告。",
    0,
)
assert "Unity 退出码 6" in body and "重新构建与测试" in body, body
print("the reply carries the same result")
print("OK")
