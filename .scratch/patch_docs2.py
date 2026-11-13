from pathlib import Path
p = Path(r"E:\Gatongone\GitClone\ToolsWorkflow\publish\README.md")
t = p.read_text(encoding="utf-8")
old = """OpenUPM builds a package from a **tag**, and it takes that tag as the version: it compares
the tag against `package.json` at that commit and refuses the build when they differ
(`E811 package.json version does not match release version`). A release tagged
`0.3.0-base` is `0.3.0-base` to OpenUPM while the version this workflow writes is
`0.3.0`, so every release needs a second, plain tag.

The push step creates it on the commit that carries the version, so nothing has to be
done by hand: the release keeps its `-base` name and `0.3.0` points at the same commit
with the right `package.json`. A repository that already has releases has the same tag
available under its `-base` name — creating `0.3.0` at that commit is all the old builds
need."""
new = """OpenUPM builds a package from a **tag**, and it takes that tag as the version: it compares
the tag against `package.json` at that commit and refuses the build when they differ
(`E811 package.json version does not match release version`). A release is therefore
tagged with the version itself, and the version commit this workflow pushes carries the
same `package.json`, so there is nothing to reconcile.

A tag with a suffix is a prerelease: `1.2.3-preview.1` is published to PeroNPM alone and
is not announced. The suffix in a tag is what says "the same source under a name that
says it is not a release" — everything else is a release.

Releases created under the old `1.2.3-base` convention keep their tags; OpenUPM can be
told to ignore them with `gitTagIgnore: '-base$'` in the package's metadata, and a
`1.2.3` tag on the version commit. New releases need neither."""
assert t.count(old) == 1
p.write_text(t.replace(old, new), encoding="utf-8", newline="\n")
print("patched")
