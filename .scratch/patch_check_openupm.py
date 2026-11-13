from pathlib import Path
p = Path(r"E:\Gatongone\GitClone\ToolsWorkflow\.scratch\check_publish_workflow.py")
t = p.read_text(encoding="utf-8")
old = '''# A step that says it always runs must not be skipped when the job fails early.'''
new = '''# OpenUPM reads a tag as the version, so the version commit needs a plain tag: the
# release tag `0.3.0-base` is `0.3.0-base` to OpenUPM while package.json says `0.3.0`.
push = dict(steps_of("publish")).get("Push changes", {})
push_body = str(push.get("run") or "")
if 'git tag -f "$NEW_VERSION"' not in push_body or 'git push -f origin "$NEW_VERSION"' not in push_body:
    bad("the version commit is not tagged with the plain version, which OpenUPM reads")
elif '"$NEW_VERSION" != "$TAG"' not in push_body:
    bad("the OpenUPM tag is created even when it is the release tag itself")
else:
    ok("the version commit also carries a plain version tag for OpenUPM")

# A step that says it always runs must not be skipped when the job fails early.'''
assert t.count(old) == 1
p.write_text(t.replace(old, new), encoding="utf-8", newline="\n")
print("patched")
