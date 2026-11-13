"""Local check: a Unity project's report loses its nullability findings.

AccessKing PR #3 reported `o?.GetHashCode() ?? 0` twice on one line —
`ConstantConditionalAccessQualifier` and `ConstantNullCoalescingCondition` — as
WARNING, while the author's Rider reported neither. Unity compiles without nullable
reference types, so a verdict that comes from nullable annotations is a verdict about
a contract the project does not have.
"""

import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "review"))

import inspect_code

REPORT = """\
<?xml version="1.0" encoding="utf-8"?>
<Report ToolsVersion="2024.3">
  <Information>
    <Solution>Demo.sln</Solution>
  </Information>
  <IssueTypes>
    <IssueType Id="ConstantConditionalAccessQualifier" Category="Redundancies in Code" Severity="WARNING" />
    <IssueType Id="ConstantNullCoalescingCondition" Category="Redundancies in Code" Severity="WARNING" />
    <IssueType Id="ConditionIsAlwaysTrueOrFalseAccordingToNullableAPIContract" Category="Potential Code Quality Issues" Severity="WARNING" />
    <IssueType Id="SuspiciousTypeConversion.Global" Category="Potential Code Quality Issues" Severity="WARNING" />
  </IssueTypes>
  <Issues>
    <Project Name="Demo">
      <Issue TypeId="ConstantConditionalAccessQualifier" File="Unity/Runtime/UnityOwnerLifetime.cs" Offset="1-2" Line="35" Message="Conditional access qualifier expression is known to be not null" />
      <Issue TypeId="ConstantNullCoalescingCondition" File="Unity/Runtime/UnityOwnerLifetime.cs" Offset="3-4" Line="35" Message="'??' left operand is never 'null'" />
      <Issue TypeId="ConditionIsAlwaysTrueOrFalseAccordingToNullableAPIContract" File="Unity/Runtime/A.cs" Offset="1-2" Line="7" Message="Expression is always true" />
      <Issue TypeId="SuspiciousTypeConversion.Global" File="Unity/Runtime/B.cs" Offset="1-2" Line="9" Message="Suspicious comparison" />
    </Project>
  </Issues>
</Report>
"""

path = Path(tempfile.mkdtemp(prefix="resharper-")) / "report.xml"
path.write_text(REPORT, encoding="utf-8")
issues = inspect_code.parse_report(str(path))
assert len(issues) == 4, issues

# The predicate, including the suffixed variant ReSharper ships.
assert inspect_code.is_nullable_inspection("ConstantConditionalAccessQualifier")
assert inspect_code.is_nullable_inspection("ConstantNullCoalescingCondition")
assert inspect_code.is_nullable_inspection(
    "ConditionIsAlwaysTrueOrFalseAccordingToNullableAPIContract"
)
assert not inspect_code.is_nullable_inspection("SuspiciousTypeConversion.Global")
assert not inspect_code.is_nullable_inspection("")
print("the predicate names the nullability inspections, including suffixed variants")

kept, dropped = inspect_code.drop_nullable_issues(issues)
print("kept:", [i["type"] for i in kept])
print("dropped:", dropped)
assert [i["type"] for i in kept] == ["SuspiciousTypeConversion.Global"], kept
assert dropped == {
    "ConstantConditionalAccessQualifier": 1,
    "ConstantNullCoalescingCondition": 1,
    "ConditionIsAlwaysTrueOrFalseAccordingToNullableAPIContract": 1,
}, dropped
print("a Unity report keeps the real findings and drops the nullability ones")

# Nothing to drop: the list comes back whole, so a non-Unity project is unaffected.
assert inspect_code.drop_nullable_issues(kept) == (kept, {})
print("OK")
