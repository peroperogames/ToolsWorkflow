import io
import sys

DOTNET = r"E:\Gatongone\GitClone\ToolsWorkflow\review\dotnet_runner.py"
LOG = r"E:\Gatongone\GitClone\ToolsWorkflow\review\build_log.py"

dotnet = io.open(DOTNET, encoding="utf-8").read()
build_log = io.open(LOG, encoding="utf-8").read()


def rep(old, new, count=1, where="dotnet"):
    global dotnet, build_log
    text = dotnet if where == "dotnet" else build_log
    if text.count(old) != count:
        sys.exit(f"[{where}] anchor found {text.count(old)} times: {old[:70]!r}")
    text = text.replace(old, new, count)
    if where == "dotnet":
        dotnet = text
    else:
        build_log = text


# --------------------------------------------------------------------------- #
# 1. The per-assembly totals `dotnet test` prints — the only place a solution's
#    totals all survive.
# --------------------------------------------------------------------------- #
rep(
    '''def parse_trx_failures(''',
    '''# `Passed!  - Failed:     0, Passed:  79, Skipped: 0, Total: 79, ... - X.dll (net10.0)`
TEST_SUMMARY = re.compile(
    r"^(?P<outcome>Passed|Failed)!\\s+-\\s+Failed:\\s*(?P<failed>\\d+),\\s+"
    r"Passed:\\s*(?P<passed>\\d+),\\s+Skipped:\\s*(?P<skipped>\\d+),\\s+"
    r"Total:\\s*(?P<total>\\d+).*?(?P<assembly>[\\w.\\-]+\\.dll)",
    re.M,
)


def parse_dotnet_test_summary(text: str) -> List[Dict[str, Any]]:
    """One row per test assembly from a ``dotnet test`` run's output.

    This is the only place a solution's totals all survive. Every test project in
    a solution writes its TRX to the file named on the command line, so the last
    one to finish overwrites the rest — RhythmAce-Neo PR #112 reported "no failing
    case" for a run whose ``Infrastructure.Desktop`` tests had 9 failures, because
    the TRX left behind belonged to a project that passed.
    """
    out: List[Dict[str, Any]] = []
    for match in TEST_SUMMARY.finditer(text or ""):
        out.append(
            {
                "outcome": match.group("outcome"),
                "failed": int(match.group("failed")),
                "passed": int(match.group("passed")),
                "skipped": int(match.group("skipped")),
                "total": int(match.group("total")),
                "assembly": match.group("assembly"),
            }
        )
    return out


def parse_trx_failures(''',
    where="log",
)

# --------------------------------------------------------------------------- #
# 2. The result counts what the run itself said, not only what one file kept.
# --------------------------------------------------------------------------- #
rep(
    '''        self.test_failures: List[Dict[str, Any]] = []''',
    '''        self.test_failures: List[Dict[str, Any]] = []
        # How many cases the run itself said failed, across every test assembly.
        # `test_failures` is what the report spelled out by name, and a report can
        # be thinner than the run: see `parse_dotnet_test_summary`.
        self.failed_total = 0''',
)
rep(
    '''        if not self.tests_ok:
            parts.append(f"{len(self.test_failures)} 个单元测试失败")''',
    '''        if not self.tests_ok:
            parts.append(f"{self._failed_count()} 个单元测试失败")''',
)
rep(
    '''        if not self.tests_ok:
            parts.append(f"{len(self.test_failures)} test failure(s)")''',
    '''        if not self.tests_ok:
            parts.append(f"{self._failed_count()} test failure(s)")''',
)
rep(
    '''    def _exit_code(self) -> Any:''',
    '''    def _failed_count(self) -> int:
        """Failures to report: at least what the run printed, if more than the file."""
        return max(len(self.test_failures), self.failed_total)

    def _exit_code(self) -> Any:''',
)
rep(
    '''        if trx.exists():
            result.test_failures = build_log.parse_trx_failures(trx)
            result.tests_ok = not result.test_failures
            result.tests_reported = True
            if result.test_failures:
                log(f".NET tests: {len(result.test_failures)} failing case(s) in {took}.")
                for line in build_log.format_test_failures(result.test_failures):
                    log(f"  {line}")
                log(f"  report: {trx}")
            else:
                log(f".NET tests finished in {took} with no failing case.")
        else:''',
    '''        # What the run said about itself, per assembly, and what the report it
        # left behind says. A solution's projects share one report file, so the
        # report can describe only the project that finished last — the totals
        # from the output are then the only account of the others.
        summaries = build_log.parse_dotnet_test_summary(text)
        declared_failed = sum(s["failed"] for s in summaries)
        failing = [s for s in summaries if s["failed"]]
        for s in failing:
            log(
                f"  {s['assembly']}: {s['failed']} failed, {s['passed']} passed, "
                f"{s['total']} total."
            )
        if trx.exists():
            result.test_failures = build_log.parse_trx_failures(trx)
        result.tests_reported = trx.exists() or bool(summaries)
        result.failed_total = declared_failed
        # The exit code is part of the answer: a run that failed its tests exits
        # non-zero even when the surviving report belongs to a project that passed.
        result.tests_ok = not result.test_failures and not declared_failed and rc == 0
        if not result.tests_ok:
            log(
                f".NET tests: {result._failed_count()} failing case(s) in {took}."
            )
            for line in build_log.format_test_failures(result.test_failures):
                log(f"  {line}")
            if trx.exists():
                log(f"  report: {trx}")
        elif result.tests_reported:
            log(f".NET tests finished in {took} with no failing case.")
        if not result.tests_reported:''',
)
rep(
    '''            log(
                f"dotnet test produced no report after {took} "
                f"({_how_it_ended(timed_out, rc)}); not counting it as a failure, and "
                "not reporting the run as tested either."
            )''',
    '''            log(
                f"dotnet test produced no report after {took} "
                f"({_how_it_ended(timed_out, rc)}); not counting it as a failure, and "
                "not reporting the run as tested either."
            )''',
)

io.open(DOTNET, "w", encoding="utf-8", newline="\n").write(dotnet)
io.open(LOG, "w", encoding="utf-8", newline="\n").write(build_log)
print("patched")
