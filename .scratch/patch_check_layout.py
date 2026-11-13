from pathlib import Path
p = Path(r"E:\Gatongone\GitClone\ToolsWorkflow\.scratch\check_publish_workflow.py")
t = p.read_text(encoding="utf-8")
old = """# The version IS the tag now, so there is no second tag to create: a check that the
# push step does not invent one keeps the old shape from coming back."""
new = """# Where the package is and what the nuget channel packs are found by the workflow, not
# passed by the caller: a caller that omits them is right for every repository here.
job_defaults = (jobs["publish"].get("defaults") or {}).get("run") or {}
if job_defaults.get("working-directory") != "${{ github.workspace }}":
    bad("the publish job still runs in the caller's working-directory: %r" % job_defaults)
else:
    ok("the publish job runs at the repository root")

resolve_step = dict(steps_of("publish")).get("Resolve the package directory and the NuGet project") or {}
resolve_body = str(resolve_step.get("run") or "")
for needed in ("package_dir.sh", "nuget_project.sh", "channels_for_tag.sh", "resolve_channels.sh"):
    if needed not in resolve_body:
        bad("the resolve step does not call %s" % needed)
if "${{ inputs.working-directory }}" in resolve_body:
    ok("the working-directory input is only a hint")
else:
    bad("the resolve step ignores the caller's working-directory")

for step_name in ("Package preprocess", "Publish to PeroNPM", "Collect the packages"):
    body = str((dict(steps_of("publish")).get(step_name) or {}).get("run") or "")
    if "$PACKAGE_ROOT" not in body:
        bad("%r does not move into the package directory" % step_name)

nuget_user = (call["inputs"].get("nuget-user") or {}).get("default")
if nuget_user != "Peropero":
    bad("nuget-user defaults to %r, not this organisation's profile" % nuget_user)
else:
    ok("nuget-user defaults to Peropero")

pack = dict(steps_of("publish")).get("Pack the NuGet packages") or {}
if "inputs.nuget-project" in str(pack.get("env") or {}):
    bad("the pack step still reads the nuget-project input, which overrides the resolved one")
else:
    ok("the pack step uses the resolved project")

# The version IS the tag now, so there is no second tag to create: a check that the
# push step does not invent one keeps the old shape from coming back."""
assert t.count(old) == 1
p.write_text(t.replace(old, new), encoding="utf-8", newline="\n")
print("check patched")
