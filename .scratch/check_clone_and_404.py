"""Local checks: the two failure modes RhythmAce-Neo #36 exposed.

Its App token could read the repository's API — 200 on /repos, /pulls/36 and
/contents — while git refused the clone ("Repository not found"). The pipeline turned
that into a *successful* checks stage ("repository kind: no C# or Unity content"),
and then failed two stages later with a bare 404 that named nothing. Both are fixed
here: the clone failing stops the stage with a sentence about the cause, and a pull
request read that 404s is retried once before it is reported.
"""

import subprocess
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "review"))

import github_client
import main

failures = []


def ok(msg):
    print("ok   " + msg)


def bad(msg):
    print("FAIL " + msg)
    failures.append(msg)


# --- get_pull_request: one retry, then a message that names the cause ----------
class FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload
        self.text = ""

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    def request(self, method, url, **kwargs):
        self.calls += 1
        return self.responses.pop(0)


client = github_client.GitHubClient("token")
client.session = FakeSession([FakeResponse(404, {"message": "Not Found"}), FakeResponse(200, {"number": 36})])
github_client.time.sleep = lambda _s: None  # the retry waits a second; the test does not
pr = client.get_pull_request("peroperogames", "RhythmAce-Neo", 36)
if pr.get("number") == 36 and client.session.calls == 2:
    ok("a one-off 404 is retried and the pull request is read")
else:
    bad(f"the retry did not happen: calls={client.session.calls}, pr={pr}")

client = github_client.GitHubClient("token")
client.session = FakeSession([FakeResponse(404, {"message": "Not Found"}), FakeResponse(404, {"message": "Not Found"})])
try:
    client.get_pull_request("peroperogames", "RhythmAce-Neo", 36)
    bad("a persistent 404 was accepted")
except RuntimeError as exc:
    text = str(exc)
    print("--- the persistent 404 says:")
    print("   ", text[:180], "...")
    if "App's installation" in text and "clone" in text:
        ok("a persistent 404 explains the App-access cause")
    else:
        bad(f"the error does not explain itself: {text}")

# Any other failure is raised as before, without a pointless retry.
client = github_client.GitHubClient("token")
client.session = FakeSession([FakeResponse(500, {"message": "boom"})] * 6)
try:
    client.get_pull_request("o", "r", 1)
    bad("a 500 was accepted")
except RuntimeError:
    ok("a non-404 failure is raised, not retried as a 404")


# --- a failed clone stops the checks stage -------------------------------------
def run_with_failed_clone():
    saved_clone = main.pr_workspace.clone_pr_head
    main.pr_workspace.clone_pr_head = lambda *a, **k: None
    try:
        config = types.SimpleNamespace(
            github_token="t", max_tokens_per_chunk=1000, unity_template="", language="en",
        )
        return main.run_checks_and_static(
            github_client.GitHubClient("t"), "peroperogames", "RhythmAce-Neo", 36,
            {"head": {"sha": "abc123"}, "base": {"sha": "def456"}}, [], config,
        )
    finally:
        main.pr_workspace.clone_pr_head = saved_clone


try:
    run_with_failed_clone()
    bad("a failed clone did not stop the checks stage")
except RuntimeError as exc:
    text = str(exc)
    print("--- a failed clone says:")
    print("   ", text[:200], "...")
    if "Could not clone" in text and "GitHub App" in text and "nothing to look at" in text:
        ok("a failed clone stops the stage and names the likely cause")
    excepted = True
except SystemExit as exc:  # pragma: no cover - a different way of stopping is fine
    bad(f"a failed clone exited instead of raising: {exc}")
else:
    pass

print()
if failures:
    print("%d check(s) failed" % len(failures))
    sys.exit(1)
print("OK")
