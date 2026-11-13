"""One-off: also tag the version commit with the plain version, which is what OpenUPM reads.

OpenUPM builds a package from a tag and takes that tag as the version, so a release
tagged `0.3.0-base` is `0.3.0-base` to OpenUPM while package.json says `0.3.0` — every
build of every release fails with E811, "package.json version does not match release
version".
"""

from pathlib import Path

root = Path(__file__).resolve().parent.parent
workflow = root / ".github" / "workflows" / "publish-npm.yml"
readme = root / "publish" / "README.md"

text = workflow.read_text(encoding="utf-8")


def replace(old: str, new: str) -> None:
    global text
    assert text.count(old) == 1, (text.count(old), old[:70])
    text = text.replace(old, new)


replace(
    """        env:
            TAG: ${{ github.event.release.tag_name }}
            TARGET_HINT: ${{ github.event.release.target_commitish }}""",
    """        env:
            TAG: ${{ github.event.release.tag_name }}
            TARGET_HINT: ${{ github.event.release.target_commitish }}
            PACKAGE_DIR: ${{ inputs.working-directory }}""",
)

replace(
    """           git push https://x-access-token:${{ steps.generate_token.outputs.token }}@github.com/${{ github.repository }} HEAD:"$TARGET"
           git tag -f "$TAG"
           git push -f origin "$TAG\"""",
    """           git push https://x-access-token:${{ steps.generate_token.outputs.token }}@github.com/${{ github.repository }} HEAD:"$TARGET"
           git tag -f "$TAG"
           git push -f origin "$TAG"

           # OpenUPM builds a package from a tag and takes the tag as the version, so
           # a release tagged `0.3.0-base` is `0.3.0-base` to OpenUPM while the
           # package.json this release just wrote says `0.3.0`: every build fails with
           # E811 "package.json version does not match release version". The release
           # keeps its own name; this is the tag OpenUPM reads, on the commit that
           # carries the version.
           NEW_VERSION=$(grep '"version"' "$PACKAGE_DIR/package.json" | head -1 \\
             | sed 's/.*"version": *"\\([^"]*\\)".*/\\1/')
           if [ -n "$NEW_VERSION" ] && [ "$NEW_VERSION" != "$TAG" ]; then
             echo "tagging $NEW_VERSION for OpenUPM (the release itself is $TAG)"
             git tag -f "$NEW_VERSION"
             git push -f origin "$NEW_VERSION"
           fi""",
)

workflow.write_text(text, encoding="utf-8", newline="\n")

doc = readme.read_text(encoding="utf-8")
anchor = "## What goes where\n"
assert doc.count(anchor) == 1
section = """## OpenUPM

OpenUPM builds a package from a **tag**, and it takes that tag as the version: it compares
the tag against `package.json` at that commit and refuses the build when they differ
(`E811 package.json version does not match release version`). A release tagged
`0.3.0-base` is `0.3.0-base` to OpenUPM while the version this workflow writes is
`0.3.0`, so every release needs a second, plain tag.

The push step creates it on the commit that carries the version, so nothing has to be
done by hand: the release keeps its `-base` name and `0.3.0` points at the same commit
with the right `package.json`. A repository that already has releases has the same tag
available under its `-base` name — creating `0.3.0` at that commit is all the old builds
need.

"""
readme.write_text(doc.replace(anchor, section + anchor), encoding="utf-8", newline="\n")
print("patched")
