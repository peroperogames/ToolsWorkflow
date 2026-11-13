"""One-off: the two invariants the bootstrap token changes.

"A credential must not reach the OIDC job" becomes "the OIDC publish must not use a
credential, and the one token that exists is a guarded, one-time fallback".
"""

from pathlib import Path

check = Path(__file__).resolve().parent / "check_publish_workflow.py"
text = check.read_text(encoding="utf-8")


def replace(old: str, new: str) -> None:
    global text
    assert text.count(old) == 1, (text.count(old), old[:70])
    text = text.replace(old, new)


replace(
    '''# A credential must not reach the OIDC job: it authenticates with the job's identity.
external_text = "\\n".join(str(step) for _, step in steps_of("external"))
if "${{ secrets." in external_text:
    bad("a secret is passed into the external (OIDC) job")
else:
    ok("no secret is passed into the external job")''',
    '''# The OIDC job authenticates with the job's identity. The one secret it may see is
# the bootstrap token, which exists because npm cannot create a package through OIDC
# at all — the first release of a new name would otherwise need a human at a terminal.
external_text = "\\n".join(str(step) for _, step in steps_of("external"))
secrets_used = set(__import__("re").findall(r"secrets\\.([A-Z_]+)", external_text))
if secrets_used - {"NPMJS_BOOTSTRAP_TOKEN"}:
    bad("secrets reach the external (OIDC) job: %r" % sorted(secrets_used))
else:
    ok("the only secret the external job reads is the npm bootstrap token")
declared = workflow[True]["workflow_call"]["secrets"].get("NPMJS_BOOTSTRAP_TOKEN") or {}
if declared.get("required") is False:
    ok("the bootstrap token is optional, so a release that does not need it needs none")
else:
    bad("NPMJS_BOOTSTRAP_TOKEN is not declared as optional")''',
)

replace(
    '''elif "--userconfig" in npmjs_body or "_authToken" in npmjs_body:
    bad("the npmjs step carries a credential")
else:
    ok("npmjs publishes the tarball with no credential, on an npm new enough")''',
    '''elif "--userconfig" not in npmjs_body or "_authToken" not in npmjs_body:
    bad("the npmjs step has no bootstrap path for a package that does not exist yet")
elif 'if [ -n "${NPMJS_BOOTSTRAP_TOKEN:-}" ]' not in npmjs_body:
    bad("the bootstrap token is used without being guarded by a non-empty check")
elif 'rm -f "$userconfig"' not in npmjs_body:
    bad("the temporary npmrc carrying the token is not removed")
else:
    ok("npmjs publishes through OIDC, with a guarded one-time bootstrap for a new package")''',
)

check.write_text(text, encoding="utf-8", newline="\n")
print("patched")
