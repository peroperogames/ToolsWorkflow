"""Local check: the editor log's exceptions reach the summary, from a real log.

The log is the PlayMode one from UIQueen PR #3 attempt 3 — the run that exited 6
with no report and left this pipeline with only "Unity exited with code 3 before
reporting results" to say.
"""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE / "review"))

import build_log
import unity_runner

log = HERE / ".scratch" / "artifacts-3" / "out" / "tests-PlayMode.editor.log"
assert log.is_file(), log
diagnosis = build_log.parse_editor_diagnosis(log)
print(diagnosis)

assert diagnosis["kinds"] == 2, diagnosis
assert diagnosis["total"] == 23, diagnosis
first = diagnosis["exceptions"][0]
assert first["message"].startswith("AssertionException: There is no Addressables"), first
assert first["frame"] == "MDSampleInit.Init", first
assert diagnosis["verdict"].startswith("Test run completed. Exiting with code 3 (RunError)")

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
    }
]
result.platform_failures = [
    {
        "platform": "PlayMode",
        "exit": 6,
        "timed_out": False,
        "timeout": 600,
        "diagnosis": diagnosis,
    }
]
print("--- summary() as the pull request sees it")
print(result.summary())
print("--- outcome() for the job log")
print(result.outcome())

text = result.summary()
assert "AssertionException: There is no Addressables Settings in project" in text, text
assert "×16" in text and "×7" in text, text
assert "MDSampleInit.Init" in text, text
assert "Test run completed. Exiting with code 3 (RunError)" in text, text
assert "PlayMode 测试运行失败（Unity 退出码 6）" in text, text
# The first line of the comment already says the run produced no report; the block
# must not say it again, and the verdict line is named for the platform.
assert text.count("没有产出报告") == 1, text
assert "PlayMode 编辑器日志里的异常（23 次、2 类）" in text, text
assert "PlayMode 测试结果：`Test run completed." in text, text
print("OK")
