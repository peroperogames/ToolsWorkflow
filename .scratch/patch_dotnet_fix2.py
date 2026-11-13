import io
import sys

PATH = r"E:\Gatongone\GitClone\ToolsWorkflow\review\dotnet_runner.py"
source = io.open(PATH, encoding="utf-8").read()

old = '''        result.tests_reported = trx.exists() or bool(summaries)
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
        if not result.tests_reported:'''

new = '''        result.tests_reported = trx.exists() or bool(summaries)
        result.failed_total = declared_failed
        if result.tests_reported:
            # The exit code is part of the answer: a run whose tests failed exits
            # non-zero even when the surviving report belongs to a project that
            # passed, which is how a solution's 9 failures went unreported.
            result.tests_ok = (
                not result.test_failures and not declared_failed and rc == 0
            )
        if not result.tested:
            pass
        elif result.tests_reported and not result.tests_ok:
            log(f".NET tests: {result._failed_count()} failing case(s) in {took}.")
            for line in build_log.format_test_failures(result.test_failures):
                log(f"  {line}")
            if trx.exists():
                log(f"  report: {trx}")
        elif result.tests_reported:
            log(f".NET tests finished in {took} with no failing case.")
        else:'''

if source.count(old) != 1:
    sys.exit(f"anchor found {source.count(old)} times")
io.open(PATH, "w", encoding="utf-8", newline="\n").write(source.replace(old, new, 1))
print("patched")
