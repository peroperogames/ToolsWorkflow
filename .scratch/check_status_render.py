"""Local check: the status comment reads as what it says.

RhythmAce-Neo PR #112's rebuild comment rendered the .NET verdict and the ReSharper
line as rows of the Unity test table, because a line directly under a markdown
table is a row of it. And a table whose columns are 用例/通过/失败/跳过/耗时 has to
carry numbers: the .NET side now brings its own per-assembly rows.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "review"))

import dotnet_runner
import main
import stage_state
import unity_runner

failures = []


def ok(msg):
    print("ok   " + msg)


def bad(msg):
    print("FAIL " + msg)
    failures.append(msg)


def stray_rows(text):
    """Lines that would render as a table row without being one of its columns."""
    lines = text.split("\n")
    out = []
    for index, line in enumerate(lines):
        if not line.startswith("|"):
            continue
        following = lines[index + 1] if index + 1 < len(lines) else ""
        if following and not following.startswith("|") and not following.startswith("```"):
            out.append(following[:60])
    return out


# --- the .NET result, with the real numbers from that run -------------------
dotnet = dotnet_runner.DotnetResult()
dotnet.ran = True
dotnet.compiled = True
dotnet.tested = True
dotnet.tests_reported = True
dotnet.tests_ok = False
dotnet.failed_total = 12
dotnet.assemblies = [
    {"assembly": "RhythmAce.Infrastructure.Desktop.Tests.dll",
     "total": 130, "passed": 119, "failed": 9, "skipped": 2},
    {"assembly": "RhythmAce.Host.Cli.Tests.dll",
     "total": 30, "passed": 27, "failed": 3, "skipped": 0},
]

# --- the Unity result, with no case at all -----------------------------------
unity = unity_runner.UnityResult()
unity.ran = True
unity.compiled = True
unity.tests_reported = True
unity.platform_runs = [
    {"platform": "EditMode", "summary": {"total": 0, "passed": 0, "failed": 0,
                                         "skipped": 0, "duration": 0.0}},
    {"platform": "PlayMode", "summary": {"total": 0, "passed": 0, "failed": 0,
                                         "skipped": 0, "duration": 0.0}},
]

status = stage_state.build_status_context(unity.summary(), dotnet.summary())

if "12 个单元测试失败" in status:
    ok("the .NET verdict carries its count")
else:
    bad(status)

if "| RhythmAce.Infrastructure.Desktop.Tests | 130 | 119 | 9 | 2 |" in status:
    ok("the per-assembly numbers reach the comment as a table")
else:
    bad(status)

if not stray_rows(status):
    ok("no verdict line renders as a row of somebody else's table")
else:
    bad(f"these lines would join a table: {stray_rows(status)!r}")

if "本次没有运行用例" in unity.summary() and "单元测试通过" not in unity.summary():
    ok("a run with no case does not claim the tests passed")
else:
    bad(unity.summary())

# --- the rebuild comment: heading, status, ReSharper, link, all separated ---
comment = main.rebuild_comment_body("Unity package in a C# project (RhythmAce.sln)",
                                    status, 1)
if "ReSharper：新提出 1 条行内意见。" in comment and not stray_rows(comment):
    ok("the rebuild comment keeps the ReSharper line out of the test table")
else:
    bad(f"comment={comment!r} strays={stray_rows(comment)!r}")

# --- a failing run with no case to name must not say "0 failing cases" --------
blank = dotnet_runner.DotnetResult()
blank.ran = True
blank.compiled = True
blank.tested = True
blank.tests_reported = True
blank.tests_ok = False
blank.failed_total = 0
blank.test_run = {"exit": 1}
if "测试运行失败（dotnet test 退出码 1）" in blank.summary() and "0 个单元测试失败" not in blank.summary():
    ok("a run that failed without a case names the failure, not a zero")
else:
    bad(blank.summary())

print()
if failures:
    print("%d check(s) failed" % len(failures))
    sys.exit(1)
print("OK")
