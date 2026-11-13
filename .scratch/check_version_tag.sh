#!/bin/bash
# Checks the one copy of the tag rule, and that package_preprocess.sh still behaves
# the same after it started sourcing that copy instead of holding its own.
#
# The rule is now "the version is the tag": a suffix makes it a prerelease, which is
# published to PeroNPM alone and is not announced. `-base` is gone.
set -uo pipefail

TOOLS=/e/Gatongone/GitClone/ToolsWorkflow
failures=0

ok() { echo "ok   $1"; }
bad() { echo "FAIL $1"; failures=$((failures + 1)); }

source "$TOOLS/publish/version_from_tag.sh"

check_version() { # tag, expected output, expected rc
  local tag="$1" want="$2" want_rc="$3" got rc
  got=$(extract_version "$tag" 2>/dev/null); rc=$?
  if [ "$rc" != "$want_rc" ]; then bad "extract_version $tag: exit $rc, wanted $want_rc"; return; fi
  if [ "$want_rc" = 0 ] && [ "$got" != "$want" ]; then bad "extract_version $tag: '$got', wanted '$want'"; return; fi
  ok "extract_version $tag -> ${got:-<error>}"
}

check_release() { # tag, expected 0 (a release) or 1 (a prerelease)
  local tag="$1" want="$2" got
  if is_release_tag "$tag"; then got=0; else got=1; fi
  if [ "$got" = "$want" ]; then
    ok "is_release_tag $tag -> $([ "$got" = 0 ] && echo release || echo prerelease)"
  else
    bad "is_release_tag $tag -> $got, wanted $want"
  fi
}

check_version '0.3.0' '0.3.0' 0
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

# The error message has to name the bad tag, since it is the only clue in the log.
msg=$(extract_version 'nightly' 2>&1 >/dev/null)
case "$msg" in
  *"invalid version tag 'nightly'"*) ok "the error names the tag" ;;
  *) bad "the error does not name the tag: $msg" ;;
esac

# package_preprocess.sh, run from the package folder but called by absolute path —
# which is how the workflow calls it out of the ci_cd checkout.
fixture=/tmp/preprocess-test
rm -rf "$fixture" && mkdir -p "$fixture"

run_preprocess() { # script, tag, prefix
  ( cd "$fixture" && CI_COMMIT_TAG="$2" EXPECTED_PACKAGE_PREFIX="$3" bash "$1" )
}

# name in the manifest, tag the release, expected version (empty: nothing may change)
compare_preprocess() { # label, manifest name, tag, expected version
  local label="$1" name="$2" tag="$3" want="$4" rc_new new_val version
  printf '{\n  "name": "%s",\n  "displayName": "AccessKing",\n  "version": "0.2.5"\n}\n' "$name" > "$fixture/package.json"
  out=$(run_preprocess "$TOOLS/publish/package_preprocess.sh" "$tag" 'com.prpr' 2>&1); rc_new=$?
  new_val=$(cat "$fixture/package.json")

  version=$(printf '%s' "$new_val" | grep '"version"' | head -1 | sed 's/.*"version": *"\([^"]*\)".*/\1/')
  if [ -n "$want" ] && [ "$version" != "$want" ]; then bad "$label: version '$version', wanted '$want'"; return; fi
  ok "$label (exit $rc_new, version $version)"
}

compare_preprocess '0.3.0 on com.prpr' 'com.prpr.accessking' '0.3.0' '0.3.0'
compare_preprocess '0.3.0-base on com.prpr' 'com.prpr.accessking' '0.3.0-base' '0.3.0'
compare_preprocess '0.3.0-preview.1 on com.prpr' 'com.prpr.accessking' '0.3.0-preview.1' '0.3.0-preview.1'
compare_preprocess '0.3.0-variant on com.example' 'com.example.accessking' '0.3.0-android-variant' '0.3.0-android-variant'
compare_preprocess 'nightly' 'com.prpr.accessking' 'nightly' '0.2.5'

# A tag that names no version stops the run and leaves the manifest alone.
printf '{\n  "name": "com.prpr.accessking",\n  "version": "0.2.5"\n}\n' > "$fixture/package.json"
before=$(cat "$fixture/package.json")
out=$(run_preprocess "$TOOLS/publish/package_preprocess.sh" 'nightly' 'com.prpr' 2>&1); rc=$?
after=$(cat "$fixture/package.json")
[ "$rc" != 0 ] || bad "an invalid tag was accepted"
[ "$before" = "$after" ] && ok "an invalid tag leaves package.json untouched" || bad "an invalid tag rewrote package.json"

# An empty prefix used to make the package name ".com.prpr.accessking" — the empty
# string, a dot, and the whole old name — and that name would have been published.
printf '{\n  "name": "com.prpr.accessking",\n  "version": "0.2.5"\n}\n' > "$fixture/package.json"
before=$(cat "$fixture/package.json")
out=$(run_preprocess "$TOOLS/publish/package_preprocess.sh" '0.3.0' '' 2>&1); rc=$?
after=$(cat "$fixture/package.json")
if [ "$rc" != 0 ] && printf '%s' "$out" | grep -q 'EXPECTED_PACKAGE_PREFIX' && [ "$before" = "$after" ]; then
  ok "an empty expected prefix stops the run instead of publishing '.com.prpr.…'"
else
  bad "an empty prefix gave exit $rc and $(printf '%s' "$after" | tr -d '\n')"
fi

# No scratch files survive a successful run.
run_preprocess "$TOOLS/publish/package_preprocess.sh" '0.4.0' 'com.prpr' > /dev/null 2>&1
leftover=$(ls "$fixture" | grep -v '^package.json$' || true)
[ -z "$leftover" ] && ok "no scratch files left behind" || bad "left behind: $leftover"

rm -rf "$fixture"
echo
if [ "$failures" -eq 0 ]; then echo "all version checks passed"; else echo "$failures check(s) failed"; exit 1; fi
