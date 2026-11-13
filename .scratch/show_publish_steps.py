"""Print the two publish steps this change touched, so the workflow can be read."""

import yaml
from pathlib import Path

workflow = yaml.safe_load(
    Path(".github/workflows/publish-npm.yml").read_text(encoding="utf-8")
)
for step in workflow["jobs"]["publish"]["steps"]:
    if step.get("name") in ("Update the README's version", "Commit version update"):
        print("==", step["name"], "| env:", step.get("env") or {})
        print(step["run"])
        print()
