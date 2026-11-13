from pathlib import Path
p = Path(r"E:\Gatongone\GitClone\ToolsWorkflow\.scratch\check_publish_workflow.py")
t = p.read_text(encoding="utf-8")
old = """# The version IS the tag now, so there is no second tag to create: a check that the
# push step does not invent one keeps the old shape from coming back."""
new = """# Two shapes GitHub refuses to load at all — and a workflow that does not load gives a
# `startup_failure` with no jobs, whose only message is "workflow file issue":
#   * an `env:` with nothing under it is `env: null`, "Unexpected value ''";
#   * a `#` line inside a folded `if: >-` is part of the expression.
for job_name in ("publish", "external", "notify"):
    job = jobs[job_name]
    condition = str(job.get("if") or "")
    if "\\n#" in condition or condition.lstrip().startswith("#"):
        bad("the if: of job %r starts with a comment, which YAML folds into it" % job_name)
    for step in job.get("steps") or []:
        name = step.get("name") or step.get("uses")
        env = step.get("env")
        if env is not None and not env:
            bad("step %r has an env: with nothing in it, which GitHub refuses" % name)
        condition = str(step.get("if") or "")
        if "\\n#" in condition or condition.lstrip().startswith("#"):
            bad("the if: of step %r starts with a comment" % name)

# The version IS the tag now, so there is no second tag to create: a check that the
# push step does not invent one keeps the old shape from coming back."""
assert t.count(old) == 1
p.write_text(t.replace(old, new), encoding="utf-8", newline="\n")
print("check patched")
