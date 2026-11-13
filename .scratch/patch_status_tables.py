import io
import sys

DOTNET = r"E:\Gatongone\GitClone\ToolsWorkflow\review\dotnet_runner.py"
UNITY = r"E:\Gatongone\GitClone\ToolsWorkflow\review\unity_runner.py"
STATE = r"E:\Gatongone\GitClone\ToolsWorkflow\review\stage_state.py"

dotnet = io.open(DOTNET, encoding="utf-8").read()
unity = io.open(UNITY, encoding="utf-8").read()
state = io.open(STATE, encoding="utf-8").read()


def rep(old, new, count=1, where="dotnet"):
    global dotnet, unity, state
    box = {"dotnet": dotnet, "unity": unity, "state": state}
    text = box[where]
    if text.count(old) != count:
        sys.exit(f"[{where}] anchor found {text.count(old)} times: {old[:70]!r}")
    text = text.replace(old, new, count)
    if where == "dotnet":
        dotnet = text
    elif where == "unity":
        unity = text
    else:
        state = text


# --------------------------------------------------------------------------- #
# 1. Two blocks are two blocks: a table and the line after it must not merge.
# --------------------------------------------------------------------------- #
rep(
    '''    status = "\\n".join(s for s in (unity_summary, dotnet_summary) if s)''',
    '''    status = "\\n\\n".join(s for s in (unity_summary, dotnet_summary) if s)''',
    where="state",
)

# --------------------------------------------------------------------------- #
# 2. The per-assembly totals travel with the result, and become a table.
# --------------------------------------------------------------------------- #
rep(
    '''        self.failed_total = 0''',
    '''        self.failed_total = 0
        # One row per test assembly, as the run printed it: the only per-target
        # numbers a solution's run has, since the projects share one report file.
        self.assemblies: List[Dict[str, Any]] = []''',
)
rep(
    '''        result.tests_reported = trx.exists() or bool(summaries)
        result.failed_total = declared_failed''',
    '''        result.tests_reported = trx.exists() or bool(summaries)
        result.failed_total = declared_failed
        result.assemblies = summaries''',
)
rep(
    '''    def _failed_count(self) -> int:''',
    '''    def _assembly_table(self) -> str:
        """Per-assembly totals as a markdown table, or "" when none were printed."""
        if not self.assemblies:
            return ""
        lines = [
            "",
            "",
            "| 测试程序集 | 用例 | 通过 | 失败 | 跳过 |",
            "| --- | --- | --- | --- | --- |",
        ]
        for row in self.assemblies:
            name = row.get("assembly") or "?"
            if name.endswith(".dll"):
                name = name[: -len(".dll")]
            lines.append(
                f"| {name} | {row.get('total', 0)} | {row.get('passed', 0)} "
                f"| {row.get('failed', 0)} | {row.get('skipped', 0)} |"
            )
        return "\\n".join(lines)

    def _ran_any_case(self) -> bool:
        """Whether the run actually had a case to report, per assembly."""
        return any(row.get("total") for row in self.assemblies)

    def _failed_count(self) -> int:''',
)
rep(
    '''            return "✅ .NET: 编译通过" + ("，单元测试通过。" if self.tested else "。")''',
    '''            if self.tested and self.assemblies and not self._ran_any_case():
                return "⚠️ .NET: 编译通过；本次没有运行用例。" + self._assembly_table()
            return (
                "✅ .NET: 编译通过"
                + ("，单元测试通过。" if self.tested else "。")
                + self._assembly_table()
            )''',
)
rep(
    '''        return "🔴 .NET: " + "；".join(parts) + "。"''',
    '''        return "🔴 .NET: " + "；".join(parts) + "。" + self._assembly_table()''',
)

# --------------------------------------------------------------------------- #
# 3. A Unity run with no case at all does not get to say the tests passed.
# --------------------------------------------------------------------------- #
rep(
    '''            return "✅ Unity: 编译通过，单元测试通过。" + self._platform_table()''',
    '''            if self.platform_runs and not any(
                (run.get("summary") or {}).get("total") for run in self.platform_runs
            ):
                return "⚠️ Unity: 编译通过；本次没有运行用例。" + self._platform_table()
            return "✅ Unity: 编译通过，单元测试通过。" + self._platform_table()''',
    where="unity",
)

io.open(DOTNET, "w", encoding="utf-8", newline="\n").write(dotnet)
io.open(UNITY, "w", encoding="utf-8", newline="\n").write(unity)
io.open(STATE, "w", encoding="utf-8", newline="\n").write(state)
print("patched")
