"""Validate the AccessKing caller against what the publish workflow now expects.

Reads the caller workflow and manifest from the repository itself (not a clone), and
the publish workflow from this checkout, so the check fails if either side drifts: a
caller whose channels need inputs it does not pass stops the release at the resolver,
before anything is built.
"""
import json
import os
import subprocess
import sys

import yaml

TOOLS = r"E:\Gatongone\GitClone\ToolsWorkflow"
REPO = "peroperogames/AccessKing"
REF = "master"
WORKFLOW = os.path.join(TOOLS, ".github", "workflows", "publish-npm.yml")
BASH = r"C:\Program Files\Git\bin\bash.exe"

failures = []


def ok(msg):
    print("ok   " + msg)


def bad(msg):
    print("FAIL " + msg)
    failures.append(msg)


def fetch(path):
    result = subprocess.run(
        ["gh", "api", "-H", "Accept: application/vnd.github.raw", f"repos/{REPO}/contents/{path}?ref={REF}"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        raise SystemExit("could not read %s: %s" % (path, result.stderr.strip()))
    return result.stdout


caller = yaml.safe_load(fetch(".github/workflows/publish.yml"))
job = caller["jobs"]["call-publish"]
print("caller: uses", job["uses"])
print("caller: permissions", job.get("permissions"))
print("caller: with", job.get("with"))

workflow = yaml.safe_load(open(WORKFLOW, encoding="utf-8"))
call_inputs = workflow[True]["workflow_call"]["inputs"]
undeclared = [key for key in job.get("with", {}) if key not in call_inputs]
if undeclared:
    bad("the caller passes %s, which the workflow does not declare" % ", ".join(undeclared))
else:
    ok("every input the caller passes is declared by the workflow")

perms = job.get("permissions") or {}
if perms.get("id-token") != "write":
    bad("the caller does not grant id-token: write, so the OIDC job has no token")
elif perms.get("contents") != "write":
    bad("the caller does not grant contents: write, so the version commit cannot be pushed")
else:
    ok("the caller grants both permissions the called workflow needs")

manifest = json.loads(fetch("Unity/package.json"))
repository = (manifest.get("repository") or {}).get("url")
expected = "github.com/peroperogames/AccessKing"
if not repository:
    bad("package.json has no repository.url, which npm refuses a trusted publish without (E422)")
elif expected not in repository:
    bad("repository.url is %r, which does not name %s" % (repository, expected))
else:
    ok("repository.url names the GitHub repository (%s)" % repository)
ok("package.json parses: %s %s" % (manifest.get("name"), manifest.get("version")))

# The pack step must resolve nuget-project from the repository root, because this
# repository keeps its .NET projects beside Unity/, not inside it.
publish_steps = [s for s in workflow["jobs"]["publish"]["steps"]]
pack = [s for s in publish_steps if s.get("name") == "Pack the NuGet packages"][0]
if pack.get("working-directory") != "${{ github.workspace }}":
    bad("the pack step does not run from the repository root")
else:
    ok("a project at Core/ can be named from the repository root")

# ... and the version bump must reach the same place.
for name in ("Update the assembly version properties", "Update the README's version", "Commit version update"):
    step = [s for s in publish_steps if s.get("name") == name][0]
    if step.get("working-directory") != "${{ github.workspace }}":
        bad("%r does not run from the repository root, so Core/ and README.md are out of reach" % name)
if not failures:
    ok("the version bump reaches the repository root, where this repository keeps its project and README")

# What the resolver says to the inputs the caller actually passes.
env = dict(os.environ)
env.update(
    {
        "CHANNELS": (job.get("with") or {}).get("channels", ""),
        "NUGET_PROJECT": (job.get("with") or {}).get("nuget-project", ""),
        "NUGET_USER": (job.get("with") or {}).get("nuget-user", ""),
        "NPM_URL": "https://npm.example.com/",
        "GITHUB_REPOSITORY": REPO,
    }
)
resolver = os.path.join(TOOLS, "publish", "resolve_channels.sh")
resolved = subprocess.run(["bash", resolver], env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", executable=BASH)
print("resolver exit %d:" % resolved.returncode)
for line in (resolved.stdout + resolved.stderr).strip().splitlines():
    print("    " + line)
if resolved.returncode != 0:
    bad("the next release would stop at the resolver")
else:
    ok("the resolver accepts the caller as it stands")

# Each channel owns its prerequisites: take away what nuget needs and the resolver
# says which input, by name, before anything has been built.
env["CHANNELS"] = "nuget"
env["NUGET_PROJECT"] = ""
missing = subprocess.run(["bash", resolver], env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", executable=BASH)
said = missing.stdout + missing.stderr
if missing.returncode != 0 and "nuget-project" in said:
    ok("a channel missing its inputs is refused by name")
else:
    bad("the resolver accepts nuget with no nuget-project (exit %d)" % missing.returncode)

print()
if failures:
    print("%d check(s) failed" % len(failures))
    sys.exit(1)
print("all AccessKing caller checks passed")
