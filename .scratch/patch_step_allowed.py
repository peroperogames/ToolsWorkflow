from pathlib import Path
p = Path(r"E:\Gatongone\GitClone\ToolsWorkflow\.github\workflows\publish-npm.yml")
t = p.read_text(encoding="utf-8")
old = """          NUGET_PROJECT="$HINT_NUGET"
          if [ -z "$NUGET_PROJECT" ] && printf '%s' "$CHANNELS" | tr ',' ' ' | grep -qiw nuget; then"""
new = """          # What this tag is allowed to publish to. A base release and a prerelease
          # go to PeroNPM alone, so they must not need a project they will not pack.
          allowed=$(bash "$tools/channels_for_tag.sh" "$CHANNELS" "${GITHUB_REF_NAME:-}") || exit 1
          NUGET_PROJECT="$HINT_NUGET"
          if [ -z "$NUGET_PROJECT" ] && printf '%s' "$allowed" | tr ',' ' ' | grep -qiw nuget; then"""
assert t.count(old) == 1
p.write_text(t.replace(old, new), encoding="utf-8", newline="\n")
print("step patched")
