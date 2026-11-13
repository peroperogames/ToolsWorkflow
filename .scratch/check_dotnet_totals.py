"""Local check: a failing test run is reported as failing, whatever the report says.

RhythmAce-Neo PR #112: `dotnet test` printed
`Failed!  - Failed: 9, Passed: 119, ... - RhythmAce.Infrastructure.Desktop.Tests.dll`
and the pipeline said "no failing case", because a solution's test projects all
write their TRX to the one file named on the command line — the last project to
finish overwrote the failing one's report, and only that file was read.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "review"))

import build_log
import dotnet_runner

failures = []


def ok(msg):
    print("ok   " + msg)


def bad(msg):
    print("FAIL " + msg)
    failures.append(msg)


# The real output, three of the nine assemblies.
OUTPUT = """
Test run for /tmp/x/tests/Shared/bin/Debug/net10.0/RhythmAce.Shared.Tests.dll (.NETCoreApp,Version=v10.0)
Passed!  - Failed:     0, Passed:    79, Skipped:     0, Total:    79, Duration: 102 ms - RhythmAce.Shared.Tests.dll (net10.0)
Failed: Unable to load shared library 'mfplat.dll' or one of its dependencies.
Test run for /tmp/x/tests/Infrastructure/Desktop/bin/Debug/net10.0/RhythmAce.Infrastructure.Desktop.Tests.dll (.NETCoreApp,Version=v10.0)
Failed!  - Failed:     9, Passed:   119, Skipped:     2, Total:   130, Duration: 1 s - RhythmAce.Infrastructure.Desktop.Tests.dll (net10.0)
Test run for /tmp/x/tests/Host/Cli/bin/Debug/net10.0/RhythmAce.Host.Cli.Tests.dll (.NETCoreApp,Version=v10.0)
Passed!  - Failed:     0, Passed:    12, Skipped:     0, Total:    12, Duration: 300 ms - RhythmAce.Host.Cli.Tests.dll (net10.0)
"""

rows = build_log.parse_dotnet_test_summary(OUTPUT)
if len(rows) == 3 and sum(r["failed"] for r in rows) == 9:
    ok("the per-assembly totals are read out of the run's own output")
else:
    bad(f"rows={rows!r}")

if any(r["assembly"] == "RhythmAce.Infrastructure.Desktop.Tests.dll" and r["failed"] == 9 for r in rows):
    ok("the failing assembly is named with its count")
else:
    bad(f"rows={rows!r}")

# A result whose only evidence is the output: a report that survived a passing
# assembly must not turn 9 failures into none.
result = dotnet_runner.DotnetResult()
result.ran = True
result.compiled = True
result.tested = True
result.tests_reported = True
result.tests_ok = False
result.failed_total = 9
if "9 个单元测试失败" in result.summary() and "9 test failure(s)" in result.outcome():
    ok("a failing run is described with the count the run printed")
else:
    bad(f"summary={result.summary()!r} outcome={result.outcome()!r}")

# The report and the output agree: the count is not doubled.
result.test_failures = [{"name": f"test{i}", "message": "", "stack": ""} for i in range(9)]
if result._failed_count() == 9:
    ok("the count is the larger of the report and the output, never their sum")
else:
    bad(f"count={result._failed_count()}")

# Nothing reported, nothing claimed: a run that produced no report is not a pass
# and not a failure — the wording has to keep saying so.
empty = dotnet_runner.DotnetResult()
empty.ran = True
empty.compiled = True
empty.tested = True
empty.tests_reported = False
empty.test_run = {"exit": 0}
if "没有产出报告" in empty.summary() and empty.tests_ok:
    ok("a run with no report stays undecided rather than passing or failing")
else:
    bad(f"summary={empty.summary()!r} ok={empty.tests_ok}")

print()
if failures:
    print("%d check(s) failed" % len(failures))
    sys.exit(1)
print("OK")
