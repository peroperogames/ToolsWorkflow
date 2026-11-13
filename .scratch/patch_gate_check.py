from pathlib import Path
p = Path(r"E:\Gatongone\GitClone\ToolsWorkflow\.scratch\check_publish_workflow.py")
t = p.read_text(encoding="utf-8")
old = '''else:
    ok("both jobs name the same artifact, uploaded from the collected directory")
'''
new = '''else:
    ok("both jobs name the same artifact, uploaded from the collected directory")

# ... and only when a registry outside PeroNPM is going to read it. A PeroNPM-only
# release published the tarball from the package directory already, so collecting and
# uploading it is paperwork nobody opens — and an account-level refusal (the artifact
# quota) then fails a release that succeeded.
for name in ("Collect the packages", "Upload the packages"):
    gate = (dict(steps_of("publish")).get(name) or {}).get("if") or ""
    if "DO_NPMJS" in gate and "DO_NUGET" in gate:
        ok("%r runs only when the external job needs the files" % name)
    else:
        bad("%r runs on every release, including the ones that read no artifact" % name)
'''
assert t.count(old) == 1
p.write_text(t.replace(old, new), encoding="utf-8", newline="\n")
print("patched")
