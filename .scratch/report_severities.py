"""What severity the ReSharper report itself declares for the two inspections."""

import xml.etree.ElementTree as ET
from pathlib import Path

REPORT = Path(
    r"C:\Users\Administrator\AppData\Local\Temp\ak-reports\resharper-2.xml"
)
WANTED = {
    "ConstantConditionalAccessQualifier",
    "ConstantNullCoalescingCondition",
    "UnusedMember.Global",
    "MemberCanBeInternal",
    "RedundantCast",
    "SuspiciousTypeConversion.Global",
    "ClassCanBeSealed.Global",
    "MissingBlankLines",
}

root = ET.parse(REPORT).getroot()
for node in root.iter("IssueType"):
    if node.get("Id") in WANTED:
        print(
            f"severity={node.get('Severity')!r:14} id={node.get('Id')} "
            f"category={node.get('Category')!r}"
        )
