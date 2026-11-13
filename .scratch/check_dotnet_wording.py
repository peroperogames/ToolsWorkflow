"""Local check: what the .NET gate says for each way a run can end."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "review"))

import dotnet_runner


def make(**fields):
    result = dotnet_runner.DotnetResult()
    result.ran = True
    for name, value in fields.items():
        setattr(result, name, value)
    return result


cases = {
    "timed out after 30 min": make(
        tested=True, tests_broke=True,
        test_run={"exit": -1, "timed_out": True, "timeout": 1800},
    ),
    "exited 3 with no report": make(
        tested=True, tests_broke=True,
        test_run={"exit": 3, "timed_out": False, "timeout": 1800},
    ),
    "exited 0 with no report": make(
        tested=True, test_run={"exit": 0, "timed_out": False, "timeout": 1800},
    ),
    "compile errors": make(compiled=False, compile_errors=[{}, {}]),
    "compile timeout": make(compiled=False, build_timed_out=True),
    "green": make(tested=True, tests_reported=True),
    "no test project": make(),
}

for name, result in cases.items():
    print(f"--- {name}")
    print(f"    zh: {result.summary() or '(nothing)'}")
    print(f"    en: {result.outcome() or '(nothing)'}")

timed_out = cases["timed out after 30 min"].summary()
assert "测试没有跑完" not in timed_out, timed_out
assert "超时" in timed_out and "30 分钟" in timed_out, timed_out
assert "退出码" in cases["exited 3 with no report"].summary()
assert "退出码 0" in cases["exited 0 with no report"].summary()
assert "编译超时" in cases["compile timeout"].summary()
assert timed_out.count("，没有产出报告。") == 1, timed_out
print("OK")
