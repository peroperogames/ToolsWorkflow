"""One-off: the publish-workflow check still asks for the `-base` rule and the extra tag."""

from pathlib import Path

check = Path(__file__).resolve().parent / "check_publish_workflow.py"
text = check.read_text(encoding="utf-8")


def replace(old: str, new: str) -> None:
    global text
    assert text.count(old) == 1, (text.count(old), old[:60])
    text = text.replace(old, new)


# The extra OpenUPM tag existed because a release tag was not a version. It is one now.
start = text.index("# OpenUPM reads a tag as the version, so the version commit needs a plain tag: the")
end = text.index("# A step that says it always runs must not be skipped when the job fails early.")
text = text[:start] + '''# The version IS the tag now, so there is no second tag to create: a check that the
# push step does not invent one keeps the old shape from coming back.
push_body = str(dict(steps_of("publish")).get("Push changes", {}).get("run") or "")
if "tag -f \\"$NEW_VERSION\\"" in push_body:
    bad("the push step creates a second tag; the release tag is the version")
else:
    ok("the release tag is the version: no second tag to create")

''' + text[end:]

replace(
    '''elif "needs.publish.result == 'success'" not in notify_gate or "endsWith(github.ref_name, '-base')" not in notify_gate:
    bad("the notify job is not gated on a successful, -base release: %r" % notify_gate)''',
    '''elif "needs.publish.result == 'success'" not in notify_gate or "!contains(github.ref_name, '-')" not in notify_gate:
    bad("the notify job is not gated on a successful release: %r" % notify_gate)''',
)

check.write_text(text, encoding="utf-8", newline="\n")
print("patched")
