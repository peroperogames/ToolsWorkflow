#!/usr/bin/env python3
"""Structural checks on the reusable publish workflow.

Not a linter: it checks the things this workflow is easy to get subtly wrong — a
channel that fails to gate its step, an `if:` that reads a flag nothing writes, a
script the steps call that does not exist, a credential that slipped back in where
OIDC belongs, or a job on a runner that cannot do what the job needs.
"""
import os
import re
import sys

import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORKFLOW = os.path.join(ROOT, ".github", "workflows", "publish-npm.yml")
PUBLISH_DIR = os.path.join(ROOT, "publish")

failures = []


def ok(msg):
    print("ok   " + msg)


def bad(msg):
    print("FAIL " + msg)
    failures.append(msg)


with open(WORKFLOW, encoding="utf-8") as handle:
    text = handle.read()
doc = yaml.safe_load(text)

trigger = doc.get("on", doc.get(True))
if not isinstance(trigger, dict) or "workflow_call" not in trigger:
    bad("the workflow has no workflow_call trigger")
    sys.exit(1)
call = trigger["workflow_call"]
ok("the workflow is callable")

inputs = call["inputs"]
if inputs["channels"]["default"] != "peronpm":
    bad("channels defaults to %r, not 'peronpm'" % (inputs["channels"]["default"],))
else:
    ok("channels defaults to peronpm")
for name in (
    "nuget-project",
    "nuget-user",
    "nuget-source",
    "unity-plugin-project",
    "unity-plugin-configuration",
    "expected-package-prefix",
    "node-version",
    "working-directory",
):
    if name not in inputs:
        bad("the input %s is gone" % name)
if inputs.get("nuget-source", {}).get("default") != "https://api.nuget.org/v3/index.json":
    bad("nuget-source defaults to %r" % (inputs.get("nuget-source", {}).get("default"),))
else:
    ok("nuget-source defaults to nuget.org")

secrets = call["secrets"]
for name, required in (
    ("APP_ID", True),
    ("APP_PK", True),
    ("FEISHU_WEBHOOK", True),
    ("FEISHU_SECRET", True),
    ("NPM_URL", False),
):
    if name not in secrets:
        bad("the secret %s is not declared" % name)
    elif bool(secrets[name].get("required", False)) != required:
        bad("%s is required=%r, wanted %r" % (name, secrets[name].get("required"), required))
ok("the secrets are the ones the self-hosted job needs")

for stale in ("secrets.NPMJS_TOKEN", "secrets.NUGET_API_KEY", "secrets.NPM_TOKEN"):
    if stale in text:
        bad("%s is back — npmjs and nuget authenticate with OIDC, not a token" % stale)
ok("no registry token is declared or read")

jobs = doc["jobs"]
if set(jobs) != {"publish", "external", "notify"}:
    bad("the jobs are %s, expected publish/external/notify" % sorted(jobs))
else:
    ok("the publish is split into the three jobs that need different runners")

self_hosted = jobs["publish"].get("runs-on")
if not isinstance(self_hosted, list) or "build-server" not in self_hosted:
    bad("the publish job no longer runs on the self-hosted runners: %r" % (self_hosted,))
else:
    ok("the PeroNPM and packaging job stays on the self-hosted runners")

# npm trusted publishing does not accept self-hosted runners (npm docs, "Supported
# CI/CD providers"), and nuget.org's exchange expects a GitHub-hosted OIDC identity.
for name in ("external", "notify"):
    runner = jobs[name].get("runs-on")
    if runner != "ubuntu-latest":
        bad("the %s job runs on %r — OIDC publishing needs a GitHub-hosted runner" % (name, runner))
if jobs["external"].get("permissions", {}).get("id-token") != "write":
    bad("the external job does not ask for id-token: write")
else:
    ok("the OIDC job runs on a GitHub-hosted runner and asks for id-token: write")

if jobs["publish"].get("permissions", {}).get("contents") != "write":
    bad("the publish job cannot push the version commit: contents is %r" % (jobs["publish"].get("permissions", {}).get("contents"),))
else:
    ok("the publish job keeps contents: write for the version commit")

if jobs["external"].get("needs") != "publish":
    bad("the external job does not depend on the publish job")
outputs = jobs["publish"].get("outputs") or {}
expected_outputs = {"npmjs": "DO_NPMJS", "nuget": "DO_NUGET"}
for key, flag in expected_outputs.items():
    if outputs.get(key) != "${{ steps.channels.outputs.%s }}" % flag:
        bad("the publish job's %r output is %r" % (key, outputs.get(key)))
resolver = open(os.path.join(PUBLISH_DIR, "resolve_channels.sh"), encoding="utf-8").read()
written_flags = {name for name in re.findall(r"(DO_[A-Z0-9_]+)=", resolver)}
if not set(expected_outputs.values()) <= written_flags:
    bad("resolve_channels.sh does not write %s" % (expected_outputs.values() - written_flags,))
elif "GITHUB_OUTPUT" not in resolver:
    bad("resolve_channels.sh never writes the job outputs the other jobs read")
else:
    ok("the channel flags travel from the resolver to the other jobs as outputs")


def env_flag(gate):
    return re.findall(r"env\.([A-Za-z0-9_]+)", gate or "")


def steps_of(job):
    return [(step.get("name", step.get("uses", "?")), step) for step in jobs[job]["steps"]]


publish_names = [name for name, _ in steps_of("publish")]
order = {name: index for index, name in enumerate(publish_names)}

for required_step in (
    "Resolve the package directory and the NuGet project",
    "Pack the NuGet packages",
    "Change folder name",
    "Package preprocess",
    "Push changes",
    "Give the package the repository's README",
    "Publish to PeroNPM",
    "Collect the packages",
    "Upload the packages",
):
    if required_step not in order:
        bad("the step %r is missing from the publish job" % required_step)
if failures:
    sys.exit(1)
if len(set(publish_names)) != len(publish_names):
    bad("two steps of the publish job share a name")

if not order["Resolve the package directory and the NuGet project"] < min(order["Pack the NuGet packages"], order["Publish to PeroNPM"]):
    bad("a channel step runs before the channels are resolved")
elif not order["Pack the NuGet packages"] < order["Change folder name"]:
    # The packaging renames folders with a `~`, which moves any project inside them.
    bad("the NuGet pack runs after the folders are renamed")
elif not order["Publish to PeroNPM"] < order["Collect the packages"] < order["Upload the packages"]:
    bad("the packages are not collected after the publish and before the upload")
elif publish_names[-1] != "Clean up the ci_cd checkout":
    bad("the last step of the publish job is %r" % publish_names[-1])
else:
    ok("the publish job resolves first, packs before renaming, and uploads last")

for name, step in steps_of("publish"):
    gate = step.get("if") or ""
    for flag in env_flag(gate):
        if flag == "committed":
            continue
        if flag not in written_flags:
            bad("%r waits on env.%s, which resolve_channels.sh never writes" % (name, flag))
    for flag in re.findall(r"steps\.channels\.outputs\.([A-Za-z0-9_]+)", gate):
        if flag not in written_flags:
            bad("%r waits on steps.channels.outputs.%s, which the resolver never writes" % (name, flag))
ok("every gate reads a flag the resolver writes")

gates = {
    "Pack the NuGet packages": "steps.channels.outputs.DO_NUGET",
    "Publish to PeroNPM": "steps.channels.outputs.DO_PERONPM",
    "Check the PeroNPM login": "steps.channels.outputs.DO_PERONPM",
}
for name, want in gates.items():
    step = dict(steps_of("publish"))[name]
    if want not in (step.get("if") or ""):
        bad("%r is gated on %r, wanted %s" % (name, step.get("if"), want))
ok("the self-hosted steps are gated on their own channel")

# A package that ships a precompiled assembly keeps a copy of the version inside it.
# The rebuild has to run after the properties are bumped (or it builds the old
# version) and before the commit (or the refreshed file is never committed).
rebuild = dict(steps_of("publish")).get("Rebuild the assembly the package ships")
if not rebuild:
    bad("nothing rebuilds the assembly a package ships, so its version is whatever was committed last")
elif "inputs.unity-plugin-project != ''" not in (rebuild.get("if") or ""):
    bad("the rebuild is not gated on unity-plugin-project: %r" % rebuild.get("if"))
elif rebuild.get("working-directory") != "${{ github.workspace }}":
    bad("the rebuild does not run from the repository root")
elif not order["Update the assembly version properties"] < order[
    "Rebuild the assembly the package ships"
] < order["Commit version update"]:
    bad("the rebuild is not between the version bump and the version commit")
elif "unity-plugin-configuration" not in str(rebuild.get("env", {})):
    bad("the rebuild does not let the caller name the configuration")
else:
    ok("the shipped assembly is rebuilt after the version bump and before the commit")

# A release can be run twice. The second run checks out the same pre-bump commit, so
# committing the bump again would have to rebase onto a branch where the rebuilt
# assembly is a binary both sides changed — and the registry already has the version.
commit_step = dict(steps_of("publish"))["Commit version update"]
commit_body = str(commit_step.get("run", ""))
if "release_target_branch.sh" not in commit_body:
    bad("the version commit does not look at the branch before committing")
elif "already carries" not in commit_body:
    bad("the version commit does not skip a version the branch already has")
elif "committed=true" in commit_body and "exit 0" not in commit_body:
    bad("the version commit's skip path does not return")
else:
    ok("a re-run skips the version commit the branch already carries")

for name, where in (
    ("Publish to PeroNPM", "publish"),
    ("Publish to npmjs", "external"),
):
    body = str(dict(steps_of(where)).get(name, {}).get("run", ""))
    if "cannot publish over" not in body or "E409" not in body:
        bad("%r fails a re-run on an already published version" % name)
if not failures:
    ok("both npm channels treat an already published version as published")

# `nuget-project` means what the repository shows, so the pack must not run from the
# package subdirectory a caller may have set as working-directory.
pack = dict(steps_of("publish"))["Pack the NuGet packages"]
if pack.get("working-directory") != "${{ github.workspace }}":
    bad("the pack step runs from %r, not the repository root" % pack.get("working-directory"))
else:
    ok("the pack step resolves nuget-project from the repository root")

# npm shows the README inside the tarball, so a README at the repository root has to
# be copied into the package — after the version commit, before anything is packed.
copy = dict(steps_of("publish")).get("Give the package the repository's README")
if not copy:
    bad("the publish never gives the package the repository's README")
elif copy.get("working-directory") != "${{ github.workspace }}":
    bad("the README copy does not run from the repository root")
elif not order["Push changes"] < order["Give the package the repository's README"] < min(
    order["Publish to PeroNPM"], order["Collect the packages"]
):
    bad("the README copy is not between the version push and the packing")
elif "PACKAGE_DIR" not in str(copy.get("run") or "") and "PACKAGE_DIR" not in str(copy.get("env", {})):
    bad("the README copy does not know which directory the package is in")
else:
    ok("the repository README is copied into the package after the commit, before packing")

external_names = [name for name, _ in steps_of("external")]
external = dict(steps_of("external"))
for name, want in {
    "Publish to npmjs": "needs.publish.outputs.npmjs",
    "NuGet login": "needs.publish.outputs.nuget",
    "Push the NuGet packages": "needs.publish.outputs.nuget",
}.items():
    if name not in external:
        bad("the external job has no step %r" % name)
    elif want not in (external[name].get("if") or ""):
        bad("%r is gated on %r, wanted %s" % (name, external[name].get("if"), want))
ok("the external steps are gated on the channels the publish job reports")

# The OIDC job authenticates with the job's identity. The one secret it may see is
# the bootstrap token, which exists because npm cannot create a package through OIDC
# at all — the first release of a new name would otherwise need a human at a terminal.
external_text = "\n".join(str(step) for _, step in steps_of("external"))
secrets_used = set(__import__("re").findall(r"secrets\.([A-Z_]+)", external_text))
if secrets_used - {"NPMJS_BOOTSTRAP_TOKEN"}:
    bad("secrets reach the external (OIDC) job: %r" % sorted(secrets_used))
else:
    ok("the only secret the external job reads is the npm bootstrap token")
declared = secrets.get("NPMJS_BOOTSTRAP_TOKEN") or {}
if declared.get("required") is False:
    ok("the bootstrap token is optional, so a release that does not need it needs none")
else:
    bad("NPMJS_BOOTSTRAP_TOKEN is not declared as optional")

# nuget.org's key comes from the login action, not from a secret.
push = external.get("Push the NuGet packages", {})
if "steps.nuget_login.outputs.NUGET_API_KEY" not in str(push):
    bad("the NuGet push does not use the key nuget.org issued to this job")
else:
    ok("the NuGet push uses the short-lived key from NuGet/login")

if "NuGet/login@" not in text:
    bad("the workflow never exchanges its identity for a nuget.org key")
else:
    ok("the NuGet channel logs in with NuGet/login (OIDC)")

npmjs = external.get("Publish to npmjs", {})
npmjs_body = str(npmjs.get("run", ""))
if "--registry https://registry.npmjs.org/" not in npmjs_body:
    bad("the npmjs step does not name the public registry")
elif 'tarball="$(pwd)/${tarball}"' not in npmjs_body:
    bad("the tarball path is relative, which npm reads as the GitHub shorthand owner/repo")
elif "npm publish \"$tarball\"" not in npmjs_body:
    bad("the npmjs step does not publish the packed tarball")
elif "11.5.1" not in npmjs_body:
    bad("the npmjs step does not check for the npm trusted publishing needs")
elif "--userconfig" not in npmjs_body or "_authToken" not in npmjs_body:
    bad("the npmjs step has no bootstrap path for a package that does not exist yet")
elif 'if [ -n "${NPMJS_BOOTSTRAP_TOKEN:-}" ]' not in npmjs_body:
    bad("the bootstrap token is used without being guarded by a non-empty check")
elif 'rm -f "$userconfig"' not in npmjs_body:
    bad("the temporary npmrc carrying the token is not removed")
else:
    ok("npmjs publishes through OIDC, with a guarded one-time bootstrap for a new package")

# The two jobs have to agree on the artifact.
upload = dict(steps_of("publish")).get("Upload the packages", {})
download = external.get("Download the packages", {})
upload_name = upload.get("with", {}).get("name")
download_name = download.get("with", {}).get("name")
if not upload_name or upload_name != download_name:
    bad("the upload artifact %r and the download artifact %r differ" % (upload_name, download_name))
elif "publish-artifacts" not in str(upload.get("with", {}).get("path", "")):
    bad("the upload does not point at the collected packages")
else:
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

# Where the package is and what the nuget channel packs are found by the workflow, not
# passed by the caller: a caller that omits them is right for every repository here.
job_defaults = (jobs["publish"].get("defaults") or {}).get("run") or {}
if job_defaults.get("working-directory") != "${{ github.workspace }}":
    bad("the publish job still runs in the caller's working-directory: %r" % job_defaults)
else:
    ok("the publish job runs at the repository root")

resolve_step = dict(steps_of("publish")).get("Resolve the package directory and the NuGet project") or {}
resolve_body = str(resolve_step.get("run") or "")
for needed in ("package_dir.sh", "nuget_project.sh", "channels_for_tag.sh", "resolve_channels.sh"):
    if needed not in resolve_body:
        bad("the resolve step does not call %s" % needed)
if "${{ inputs.working-directory }}" in str(resolve_step.get("env") or {}):
    ok("the working-directory input is only a hint")
else:
    bad("the resolve step ignores the caller's working-directory")

for step_name in ("Package preprocess", "Publish to PeroNPM", "Collect the packages"):
    body = str((dict(steps_of("publish")).get(step_name) or {}).get("run") or "")
    if "$PACKAGE_ROOT" not in body:
        bad("%r does not move into the package directory" % step_name)

nuget_user = (call["inputs"].get("nuget-user") or {}).get("default")
if nuget_user != "Peropero":
    bad("nuget-user defaults to %r, not this organisation's profile" % nuget_user)
else:
    ok("nuget-user defaults to Peropero")

pack = dict(steps_of("publish")).get("Pack the NuGet packages") or {}
if "inputs.nuget-project" in str(pack.get("env") or {}):
    bad("the pack step still reads the nuget-project input, which overrides the resolved one")
else:
    ok("the pack step uses the resolved project")

# Two shapes GitHub refuses to load at all — and a workflow that does not load gives a
# `startup_failure` with no jobs, whose only message is "workflow file issue":
#   * an `env:` with nothing under it is `env: null`, "Unexpected value ''";
#   * a `#` line inside a folded `if: >-` is part of the expression.
for job_name in ("publish", "external", "notify"):
    job = jobs[job_name]
    condition = str(job.get("if") or "")
    if "\n#" in condition or condition.lstrip().startswith("#"):
        bad("the if: of job %r starts with a comment, which YAML folds into it" % job_name)
    for step in job.get("steps") or []:
        name = step.get("name") or step.get("uses")
        env = step.get("env")
        if env is not None and not env:
            bad("step %r has an env: with nothing in it, which GitHub refuses" % name)
        condition = str(step.get("if") or "")
        if "\n#" in condition or condition.lstrip().startswith("#"):
            bad("the if: of step %r starts with a comment" % name)

# The version IS the tag now, so there is no second tag to create: a check that the
# push step does not invent one keeps the old shape from coming back.
push_body = str(dict(steps_of("publish")).get("Push changes", {}).get("run") or "")
if "tag -f \"$NEW_VERSION\"" in push_body:
    bad("the push step creates a second tag; the release tag is the version")
else:
    ok("the release tag is the version: no second tag to create")

# A step that says it always runs must not be skipped when the job fails early.
for name, step in steps_of("publish"):
    if name == "Clean up the ci_cd checkout" and "always()" not in (step.get("if") or ""):
        bad("the cleanup is not gated on always()")

notify = jobs["notify"]
notify_gate = notify.get("if") or ""
if not isinstance(notify.get("needs"), list) or set(notify["needs"]) != {"publish", "external"}:
    bad("the notify job does not wait for both publishing jobs: %r" % (notify.get("needs"),))
elif "needs.publish.result == 'success'" not in notify_gate or "!contains(github.ref_name, '-')" not in notify_gate:
    bad("the notify job is not gated on a successful release: %r" % notify_gate)
elif "needs.external.result == 'skipped'" not in notify_gate:
    # The external job is skipped whenever neither external channel is on.
    bad("the notify job does not allow the skipped external job")
else:
    ok("the notification runs only after a green -base release")

# `gh` needs to be told the repository: this job checks out ToolsWorkflow, so there is
# no local git repository whose remote it could infer it from.
notify_env = {}
for step in notify["steps"]:
    if step.get("name") == "Send Feishu notification":
        notify_env = step.get("env") or {}
if not notify_env:
    bad("the notify job has no Send Feishu notification step")
elif "github.repository" not in str(notify_env.get("GH_REPO", "")):
    bad("the notification runs gh without GH_REPO, in a job with no package checkout")
elif "GITHUB_REPOSITORY" not in text:
    bad("no GH_REPO/GITHUB_REPOSITORY anywhere")
else:
    ok("gh is told which repository to read the release from")

# Every script the steps call has to exist in the ci_cd checkout it is copied from.
called = set(re.findall(r"publish/([A-Za-z0-9_]+\.sh)", text))
missing = [name for name in sorted(called) if not os.path.isfile(os.path.join(PUBLISH_DIR, name))]
if missing:
    bad("the steps call publish/ scripts that do not exist: %s" % ", ".join(missing))
else:
    ok("every publish/ script the steps call exists (%s)" % ", ".join(sorted(called)))

for gone in ("npmjs_auth.sh", "check_npm_oidc.sh"):
    if gone in text:
        bad("%s is still referenced, but the step it belongs to is inline now" % gone)
    if os.path.isfile(os.path.join(PUBLISH_DIR, gone)):
        bad("publish/%s still exists" % gone)
if os.path.isfile(os.path.join(PUBLISH_DIR, "npmjs_auth.sh")):
    bad("publish/npmjs_auth.sh still exists")

print()
if failures:
    print("%d check(s) failed" % len(failures))
    sys.exit(1)
print("all workflow checks passed")
