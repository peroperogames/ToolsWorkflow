from pathlib import Path
p = Path(r"E:\Gatongone\GitClone\ToolsWorkflow\.scratch\check_version_tag.sh")
t = p.read_text(encoding="utf-8")

old = """check_version '0.3.0' '0.3.0' 0
check_version 'v0.3.0' '0.3.0' 0
check_version 'V10.20.30' '10.20.30' 0
check_version '0.3.0-preview.1' '0.3.0-preview.1' 0
check_version '0.3.0-android-variant' '0.3.0-android-variant' 0
check_version '0.3.0-base' '0.3.0-base' 0
check_version 'nightly' '' 1
check_version '0.3' '' 1
check_version '0.3.0-' '' 1

check_release '0.3.0' 0
check_release 'v0.3.0' 0
check_release '0.3.0-base' 1
check_release '0.3.0-preview.1' 1
check_release '0.3.0-ios-variant' 1
"""
new = """check_version '0.3.0' '0.3.0' 0
check_version 'v0.3.0' '0.3.0' 0
check_version 'V10.20.30' '10.20.30' 0
check_version '0.3.0-base' '0.3.0' 0
check_version 'v0.3.0-base' '0.3.0' 0
check_version '0.3.0-preview.1' '0.3.0-preview.1' 0
check_version '0.3.0-android-variant' '0.3.0-android-variant' 0
check_version 'nightly' '' 1
check_version '0.3' '' 1
check_version '0.3.0-' '' 1

# A release (no suffix) is the only shape that reaches npmjs and nuget; a base release
# is a release cut from the base branch, and it is announced.
check_release '0.3.0' 0
check_release 'v0.3.0' 0
check_release '0.3.0-base' 1
check_release '0.3.0-preview.1' 1
check_release '0.3.0-ios-variant' 1

check_base() { # tag, expected 0 (base) or 1
  local tag="$1" want="$2" got
  if is_base_tag "$tag"; then got=0; else got=1; fi
  if [ "$got" = "$want" ]; then
    ok "is_base_tag $tag -> $([ "$got" = 0 ] && echo base || echo not-base)"
  else
    bad "is_base_tag $tag -> $got, wanted $want"
  fi
}
check_base '0.3.0-base' 0
check_base 'v0.3.0-base' 0
check_base '0.3.0' 1
check_base '0.3.0-ios-variant' 1

# Notify, as the workflow's own condition reads it: a release and a base release are
# announced, a variant is not.
for tag in 0.3.0 0.3.0-base; do
  case "$tag" in
    *-*) if is_base_tag "$tag"; then ok "notify: $tag is announced"; else bad "notify: $tag would be silent"; fi ;;
    *) ok "notify: $tag is a release"; ;;
  esac
done
"""
assert t.count(old) == 1
t = t.replace(old, new)

old2 = """compare_preprocess '0.3.0 on com.prpr' 'com.prpr.accessking' '0.3.0' '0.3.0'"""
new2 = """compare_preprocess '0.3.0 on com.prpr' 'com.prpr.accessking' '0.3.0' '0.3.0'
compare_preprocess '0.3.0-base on com.prpr' 'com.prpr.accessking' '0.3.0-base' '0.3.0'"""
assert t.count(old2) == 1
t = t.replace(old2, new2)
p.write_text(t, encoding="utf-8", newline="\n")
print("patched")
