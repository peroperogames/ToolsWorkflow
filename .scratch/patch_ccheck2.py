from pathlib import Path
p = Path(r"E:\Gatongone\GitClone\ToolsWorkflow\.scratch\check_channels.sh")
t = p.read_text(encoding="utf-8")

old = """# 9. A prerelease version reaches PeroNPM and nothing else, whatever the caller asked
#    for: a version number on npmjs.org or nuget.org cannot be taken back."""
new = """# 9. A base release is the tag a person creates; it reaches PeroNPM and nothing else,
#    whatever the caller asked for."""
assert t.count(old) == 1
t = t.replace(old, new)

old2 = """# The old `-base` convention is a suffix like any other now.
out=$(resolve GITHUB_REF_NAME=0.3.0-base CHANNELS=peronpm,npmjs NUGET_PROJECT="" NUGET_USER="" NPM_URL=https://npm.example.com/ GITHUB_REPOSITORY=$repo); rc=$?
verify "a -base tag is a prerelease too" "$rc" 0 "$out" "DO_NPMJS=false\""""
new2 = """out=$(resolve GITHUB_REF_NAME=0.3.0-base CHANNELS=peronpm,npmjs NUGET_PROJECT="" NUGET_USER="" NPM_URL=https://npm.example.com/ GITHUB_REPOSITORY=$repo); rc=$?
verify "a -base tag is published to PeroNPM only" "$rc" 0 "$out" "base release"
contains_line "the base release is not published to npmjs" "$out" "DO_NPMJS=false"

# A release — no suffix at all — is the one shape that reaches the other registries.
out=$(resolve GITHUB_REF_NAME=0.3.0 CHANNELS=peronpm,npmjs NUGET_PROJECT="" NUGET_USER="" NPM_URL=https://npm.example.com/ GITHUB_REPOSITORY=$repo); rc=$?
verify "a release reaches npmjs" "$rc" 0 "$out" "DO_NPMJS=true\""""
assert t.count(old2) == 1
t = t.replace(old2, new2)
p.write_text(t, encoding="utf-8", newline="\n")
print("patched")
