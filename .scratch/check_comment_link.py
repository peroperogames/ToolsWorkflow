"""Local check: the rebuild comment carries the report link when a run wrote none.

This is the case from the screenshot — PlayMode exited 6 and produced no report —
rendered through the real `report_build_result`, with the comment captured instead
of posted.
"""

import os
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "review"))

import main
import unity_runner

RUN = "39586837484"
os.environ["GITHUB_REPOSITORY"] = "peroperogames/UIQueen"
os.environ["GITHUB_RUN_ID"] = RUN


class FakeGitHub:
    def __init__(self):
        self.comments = []

    def post_comment(self, owner, repo, number, body):
        self.comments.append(body)
        return {"id": 900 + len(self.comments)}

    def create_check_run(self, *args, **kwargs):
        return None


result = unity_runner.UnityResult()
result.ran = True
result.compiled = True
result.tests_reported = False
result.tests_broke = True
result.platform_runs = [
    {
        "platform": "EditMode",
        "summary": {"total": 24, "passed": 24, "failed": 0, "skipped": 0, "duration": 1.3},
        "report": "/tmp/tests-EditMode.xml",
        "skipped_cases": [],
    },
]
result.platform_failures = [
    {"platform": "PlayMode", "exit": 6, "timed_out": False, "timeout": 600}
]
result.test_tail = ["License is not active.", "Exiting without the test run."]
result.test_log_path = "/tmp/ai-code-review/peroperogames/UIQueen-PR3/.ai-review/tests-PlayMode.log"

gh = FakeGitHub()
config = types.SimpleNamespace(dry_run=False, language="zh")
main.report_build_result(
    gh, "peroperogames", "UIQueen", 3, [], config, "ce93c945", result, label="Unity"
)

assert len(gh.comments) == 1, gh.comments
body = gh.comments[0]
print(body)
assert f"https://github.com/peroperogames/UIQueen/actions/runs/{RUN}#artifacts" in body
assert "没有产出报告" in body
print("--- link present in the no-report comment")
