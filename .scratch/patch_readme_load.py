from pathlib import Path
p = Path(r"E:\Gatongone\GitClone\ToolsWorkflow\publish\README.md")
t = p.read_text(encoding="utf-8")
anchor = "## What the caller does not have to say\n"
assert t.count(anchor) == 1
section = """## When a release does not start at all

A reusable workflow that GitHub cannot load produces no jobs and one sentence — "This run
likely failed because of a workflow file issue" — which names neither the file nor the
line. Asking the workflow to load itself says the rest: add a `workflow_dispatch` job that
`uses: ./.github/workflows/publish-npm.yml` in the workflow's own repository and dispatch
it, and GitHub prints the parse errors before anything runs:

```
(Line: 293, Col: 13): Unexpected value ''
(Line: 454, Col: 13): Unexpected value ''
```

That was an `env:` left with nothing under it. The other load-time mistake seen here was a
`#` line inside an `if: >-` block, where YAML keeps the `#` as part of the expression.
`check_publish_workflow.py` refuses both.

"""
t = t.replace(anchor, section + anchor)
p.write_text(t, encoding="utf-8", newline="\n")
print("readme patched")
