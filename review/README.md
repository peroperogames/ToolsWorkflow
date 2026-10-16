# GitHub AI Code Review

An AI-powered GitHub pull request reviewer. It fetches a pull request's diff via the GitHub REST API, sends it to an OpenAI-compatible chat completions endpoint, and posts the review back to the pull request as a comment (or as a review when `SILENT_MODE=false`).

## Usage (GitHub Action)

Consumers reuse the `code-review.yml` reusable workflow (existing callers keep working unchanged). Internally it delegates to the `review` composite action, so there is no repository clone:

```yaml
# .github/workflows/ai-code-review.yml
name: AI Code Review
on:
  pull_request:
    types: [opened, synchronize, reopened, closed]
  issue_comment:
    types: [created]

jobs:
  review:
    uses: peroperogames/ToolsWorkflow/.github/workflows/code-review.yml@main
    with:
      openai-model: 'deepseek-v4-flash'
      openai-base-url: 'https://tokenhub.tencentmaas.com/plan/v3'
      review-language: 'cn'
      project-prompt-path: '.github/ai-review.md'
    secrets:
      OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
      APP_ID: ${{ secrets.APP_ID }}
      APP_PK: ${{ secrets.APP_PK }}
```

The GitHub App token is generated in `code-review.yml` via `actions/create-github-app-token` and passed to the composite action as `github-token`. Per-PR state lives in the runner's working directory (not inside the action): each pull request owns one directory named `<repo>-PR<number>` that holds both its session and its Unity project, and the whole directory is removed when the PR closes.

## Requirements

- Python 3.8+
- [`requests`](https://pypi.org/project/requests/) ≥ 2.31 — the only third-party dependency.

```bash
pip install "requests>=2.31.0"
```

The runner is expected to carry these already; the action installs nothing. It also needs the tools for whatever it is asked to check — `unity`, `jb`, `dotnet` — but nothing has to be told where they are: see [Nothing asks where a tool is](#nothing-asks-where-a-tool-is).

## Usage

The tool reads all configuration from environment variables — no command-line arguments are required:

```bash
python main.py            # all three stages, in order, in one process
python main.py checks     # build and test only
python main.py static     # static analysis only, over what `checks` left behind
python main.py review     # the model's review and the thread settling
python main.py cleanup    # delete a closed pull request's working directory
```

The action passes one stage per step; running `main.py` bare does the three that make a review, which is what a manual run wants. A single stage is how you re-run just that part against a pull request that is already checked out, and an unknown stage name exits `2` rather than guessing. `cleanup` is not part of a review and is not in `all`: it is what a closed pull request gets instead of one.

Every setting is reachable three ways: the `with:` input when calling the reusable workflow, the same input when using the composite action directly, and the environment variable when running `main.py` yourself. The table lists all three so they cannot drift apart.

| `with:` input (workflow and action) | Environment variable | Default | Description |
| --- | --- | --- | --- |
| — (from `secrets`) | `GITHUB_TOKEN` | required | GitHub token with `pull-requests: write` on the target repo. Supplied by `code-review.yml` from the App secrets. |
| — (from `secrets`) | `OPENAI_API_KEY` | required | OpenAI (or compatible) API token. Supplied by `code-review.yml` from the App secrets. |
| `openai-model` | `OPENAI_API_MODEL` | `deepseek-v4-flash` | Model to use. |
| `openai-fallback-model` | `OPENAI_API_MODEL_FALLBACK` | `glm-5.3-flash` | Fallback model used if the primary's request fails (connection error or 429/5xx). |
| `openai-base-url` | `OPENAI_API_BASE_URL` | `https://tokenhub.tencentmaas.com/plan/v3` | API base URL. |
| `openai-timeout` | `OPENAI_TIMEOUT` | `15` | Seconds to wait for the connection to the API. How long the model takes to answer is not limited. |
| `openai-max-retries` | `OPENAI_MAX_RETRIES` | `5` | Retry count for connection errors and 429/5xx responses. |
| `review-language` | `REVIEW_LANGUAGE` | `cn` | Review output language — codes (`en`, `zh`, `cn`, `ja`, `ko`, `es`, `fr`, `de`, `ru`, `pt`) or full names. It applies to what the bot writes **on the pull request**; the job log is English throughout, because that is what an operator greps and a lone sentence of something else reads as a mistake. |
| `max-tokens-per-chunk` | `MAX_TOKENS_PER_CHUNK` | `131072` | Max tokens of diff per review call. |
| `silent-mode` | `SILENT_MODE` | `true` | Post a comment instead of a review. Set to `0`/`false` to post a review with `APPROVE`/`REQUEST_CHANGES`. Only affects the prose-fallback path — the normal tool-driven review posts inline comments regardless. |
| `dry-run` | `DRY_RUN` | `false` | Print the review without posting anything. Useful for trying the bot out on a pull request. |
| `state-dir` | `REVIEW_WORK_DIR` | `<tmp>/ai-code-review` | Root for the per-PR working directories. Each PR owns exactly one, named `<repo>-PR<number>`, holding its agent session and its Unity project. (`REVIEW_STATE_DIR` is still read as the older name for this setting.) |
| `project-prompt-path` | `PROJECT_PROMPT_PATH` | `.github/ai-review.md` | Path, relative to the repository under review, of that repository's own review criteria. Read from the PR head and added to the built-in prompt; empty uses the built-in prompt alone. |
| `unity-editor-version` | `UNITY_EDITOR_VERSION` | `2022.3.62f3` | Editor version each PR's project is created for. The CLI resolves that same version back out of the project when it runs it, so the two cannot drift. |
| `unity-template` | `UNITY_TEMPLATE` | `com.unity.template.3d` | Template package each PR's project is created from. |
| `unity-sync-method` | `UNITY_SYNC_METHOD` | `UnityEditor.SyncVS.SyncSolution` | `-executeMethod` used in batch mode to regenerate the sln/csproj. |
| `resharper-dotnet-sdk` | `INSPECT_DOTNET_SDK` | *(auto-detected)* | Pin the .NET SDK whose MSBuild `jb inspectcode` uses (`--dotnetcoresdk`). Empty lets it pick, which means the **newest** installed SDK — and a preview or half-installed one fails the build before any report is written. |
| `resharper-build` | `INSPECT_BUILD` | `false` | Let `jb inspectcode` build the solution before inspecting it. Off by default: the pipeline already compiled the code, and Unity's generated projects do not build cleanly under a generic MSBuild, which fails the step with no report at all. |
| — | `UNITY_TIMEOUT` / `DOTNET_TIMEOUT` | `1800` | Seconds either build step may take before it is ended — the tool and everything it started — and reported as skipped. |
| — | `UNITY_TEST_PLATFORMS` | `EditMode` | Comma list of Unity test platforms to run. |

`code-review.yml` also needs the `APP_ID`, `APP_PK` and `OPENAI_API_KEY` secrets; `main.py` additionally reads `GITHUB_REPOSITORY`, `GITHUB_EVENT_NAME` and `GITHUB_EVENT_PATH` (set by Actions) or `GITHUB_PR_NUMBER` for a manual run.

### Nothing asks where a tool is

There is no setting for the path of `unity`, `jb` or `dotnet`, and there will not be one. Where a tool happens to live on a particular machine is not something a caller of this workflow knows or should have to find out; a path in the configuration would be a value that is wrong for every runner but one, and that has to be updated by hand whenever the tool is.

Each tool is instead looked for once per run, in order:

| Tool | Looked for in |
| --- | --- |
| `unity` | `PATH`, then `~/.local/bin`, `/usr/local/bin`, `/opt/unity/bin` |
| `jb` | `PATH`, then `~/.dotnet/tools`, `~/.local/bin`, `/usr/local/bin` |
| `dotnet` | `PATH` |

The per-user directories are in that list because that is where these tools install themselves and because a CI service account's `PATH` never contains them: `dotnet tool install -g` writes to `~/.dotnet/tools`, and a runner started by `run.sh` or a service unit inherits a minimal `PATH`. A tool that works when typed by hand and is invisible to a job is that gap and nothing else, so it is closed here rather than left to each runner's configuration.

The log says which one was used, once, as a fact rather than a warning — `Unity CLI: /home/actions/.local/bin/unity (in ~/.local/bin; not on PATH here)` — so a build that behaves differently on the runner than it does by hand starts with the answer to "which one ran". A step whose tool is missing says so and stands down; it never fails the review.

**Not found, and not this user's to run, are reported differently**, because they need different fixes and look identical from the outside. A tool installed for *another* user — under `/root`, which a service account cannot even traverse — is invisible to `shutil.which` in exactly the way an uninstalled tool is, and the whole value of `whereis` finding it while the job cannot is the log saying which of the two happened:

```
ReSharper CLI ('jb') was not found. Checked PATH and: /home/actions/.dotnet/tools/jb,
/home/actions/.local/bin/jb, /usr/local/bin/jb. Also: /root/.dotnet/tools cannot be read
by this user. Install it for the user the runner runs as — `dotnet tool install -g
JetBrains.ReSharper.GlobalTools` — and make sure that user's PATH has it.
```

`tool_path.py` is what does this: it looks in `PATH` and then in the fallback directories, and on a miss it also checks whether anything on that path exists but is out of reach — an unreadable directory, or a file without the execute bit. Install tools **as the runner's user** (`sudo -u actions …`): copying them in from another user's home keeps that user's ownership, which is how a runner ends up with a tool it can see and not use.

If a runner keeps a tool somewhere genuinely unusual, the fix belongs in the runner's environment (put it on `PATH`, or link it into `~/.local/bin`), where it applies to every job rather than to this one — and for a one-off manual run, `UNITY_CLI`, `INSPECT_JB` and `DOTNET_PATH` are read from the environment as a break-glass override.

### Project review criteria

A repository can add its own review criteria in a file — `.github/ai-review.md` by default, overridable with `project-prompt-path` / `PROJECT_PROMPT_PATH`. It can be written by hand, or changed by asking the bot to ([`@perotoolsbot prompt: ...`](#special-commands)). It is read **from the pull request's head**, so a repository can iterate on its criteria in the same PR that it reviews, and it is appended to the built-in prompt as a `## Project-Specific Review Criteria` section. It is added to both the review prompt and the reply prompt, so an @-mention answer follows the same conventions a review would.

It supplements the built-in prompt; it never replaces it. The section is scoped so it cannot change the tool contract, the output format, or the decision to approve, and any contradiction with the built-in prompt is reported as a finding rather than obeyed. An empty string turns the feature off. If the file is missing, a directory, too large for the contents API to inline (over 1 MB, which it answers with `encoding: none`) or not UTF-8 text, the run degrades to the built-in prompt and logs why. Anything over 20,000 characters is truncated at a line boundary, and the log line names the blob SHA the text came from so a surprising review can be traced back to the exact revision that produced it.

### Pull request resolution

Inside GitHub Actions, the PR is resolved from the environment:

- `GITHUB_REPOSITORY` → owner/repo
- `GITHUB_EVENT_PATH` → PR number (from `pull_request`, `pull_request_target`, or an `issue_comment` on a PR)

For manual runs, set `GITHUB_REPOSITORY` and `GITHUB_PR_NUMBER`:

```bash
GITHUB_TOKEN=... OPENAI_API_KEY=... \
GITHUB_REPOSITORY=octocat/hello-world GITHUB_PR_NUMBER=42 DRY_RUN=1 \
python main.py
```

### Reply mode (answering comments)

The bot answers comments in two places, which arrive as two different events:

- **PR conversation** (`issue_comment`) — GitHub exposes no thread relationship there, so the comment must **@-mention the bot**.
- **Inline review comments** (`pull_request_review_comment`) — replying inside one of the bot's own threads is enough; no @-mention needed. A brand-new inline comment still has to mention it.

Comments on non-PR issues, bot comments, and comments that address neither the bot nor one of its threads are ignored. When the trigger came from an inline thread, the bot replies inside that same thread. If the model decides a comment needs no answer, it stays silent — nothing is posted, and the reason it gives is printed in the run log (`Ignored the comment: …`).

#### Special commands

Some things a comment can ask for are too consequential to guess at, so they are **commands**: `@perotoolsbot` followed by one of the words below, matched on the word right after the mention so "reviews are noisy" is not a command. A command never reaches the intent classifier — that is what makes it deterministic. Everything else (questions, discussion, a request phrased some other way) still does, exactly as before.

| Command | What it does |
| --- | --- |
| `prompt(this):` / `prompt(base):` | Rewrite review criteria and open a PR with the result. |
| `review` | Review the pull request now. |
| `rebuild` | Re-run the build, test and static-analysis steps only — no review, no approval. |

The words live in one registry (`COMMANDS` in `main.py`): each entry names the command, what the text after it means, and its handler, and the parsing, the logging and the precedence all come from there rather than from a separate parser and branch per command.

- **Improve the prompt** — `@perotoolsbot prompt: <what to change>` rewrites review criteria and opens a pull request with the result. Nothing lands without a human merging that PR, and the bot's token needs write access to the target repository (it already has it for ToolsWorkflow). The command picks the target, and the colon is optional in either form (`:` and `：` both work):
  - `@perotoolsbot prompt: ...` and `@perotoolsbot prompt(this): ...` — the reviewed repository's own criteria file (`PROJECT_PROMPT_PATH`, written fresh if it does not exist yet). The PR is opened against that repository, so a project's feedback cannot change how other projects are reviewed.
  - `@perotoolsbot prompt(base): ...` — the shared prompt in ToolsWorkflow, the single reusable source of the review prompt. The PR is opened against ToolsWorkflow.
  - This command is the **only** way a prompt change happens. A comment that merely asks for a different review style ("be stricter", "别报样式问题") is never guessed into one — the bot replies pointing at the command instead.

- **Code changes** — e.g. `@perotoolsbot fix src/foo.py`. The bot reads the current file contents, generates code changes, and submits a PR to the current repository's feature branch.

- **Review request** — `@perotoolsbot review` starts a review without consulting the intent classifier, so a repository that only ever reviews on demand cannot have its request read as something else. The word must be `review` right after the mention, and whatever follows becomes a note: `@perotoolsbot review this PR for me.` and `@perotoolsbot review: 关注并发` are both the command. Any other way of asking (`@perotoolsbot 帮忙看下`) still goes through the classifier.

  A review started this way runs **exactly what an automatic one runs** — the clone, the Unity/.NET build and test gates, and ReSharper — before the model sees anything, so a broken build cannot be approved just because nobody pushed. The one difference is scope: it covers the whole pull request, not the latest push.

- **Rebuild** — `@perotoolsbot rebuild` runs the same gates and nothing else: clone, classify, Unity/.NET build and test, ReSharper. It answers "does it compile now?" without paying for a review, and it cannot approve — only a review's verdict does that. Compile errors still land as inline comments, and one comment reports what ran.

Replying requires the GitHub App to have **`Issues: Read and write`** permission (issue comments use the Issues API, which is separate from `Pull requests`).

### Reviewing only on demand

A repository can skip `pull_request` entirely and review only when asked. Wire the caller to `issue_comment` and nothing else:

```yaml
on:
  issue_comment:
    types: [created]
```

Every review behaviour is then unchanged — the on-demand path shares the same session, the same gates and the same approval rules — except that nothing happens until someone writes `@perotoolsbot review`.

**Do also subscribe to `pull_request: [closed]`.** Closing is what deletes a PR's directory (its session, its Unity project and the clone), and nothing else can trigger that cleanup — a repository that never hears about the close accumulates one directory per pull request on the runner forever:

```yaml
on:
  pull_request:
    types: [closed]
  issue_comment:
    types: [created]
```

## Review pipeline

The work is grouped into three steps of one job — `checks` (5–7), `static` (8) and `review` (1–4, 9–10) — which is why the numbering here does not follow the step order: the session and the prompts are only needed by the step that talks to the model. See [Three stages, one job](#three-stages-one-job) for what the split buys and the one ordering rule it must not break.

1. Fetch PR metadata; if the PR is closed, delete the PR's whole working directory and stop — see [One directory per pull request](#one-directory-per-pull-request). Merges from `release/*` back to `master`/`main` are skipped. The PR's **first** pass gets the full review; later `synchronize` pushes get a light incremental pass covering only what the new commits introduced. Once a PR is known to need reviewing, the repository's own criteria are fetched from its head and merged into the prompt — see [Project review criteria](#project-review-criteria).
2. Load the PR's **session** — one append-only message log per pull request, the model's accumulated memory of everything it has seen and produced here: turns, its own replies, tool calls and results. Reviews, conversation comments **and inline review comments** are fetched from GitHub, and whatever was posted since the last run is appended as new turns. A missing or damaged session is rebuilt from GitHub (it is an optimization, not state the bot depends on), and it is deleted with the rest of the PR's directory when the PR closes. Later runs therefore continue the conversation instead of re-sending the prompt and the whole diff: a push appends just its own diff, and the model keeps the files it read and the reasoning it did.
3. Build the diff payload from the per-file patches — every line is prefixed with its absolute line number so the model can quote a line instead of computing line numbers itself.
4. If the payload still exceeds `MAX_TOKENS_PER_CHUNK`, review it in chunks and then merge the chunk reviews back into a **single** review body.
5. **Clone the pull request's head once, then classify it.** Everything downstream reads the same clone, and the classification decides which of the next two steps has anything to do. Four kinds exist, and they are told apart from the clone's contents alone — no extra API calls, nothing guessed:
   - **Unity package** (`package.json`) → compiled and tested in a per-PR Unity project; ReSharper runs over Unity's solution.
   - **Pure C# project** (`sln`/`slnx`/`csproj`) → built and tested with the .NET SDK; ReSharper runs over the repository's own solution.
   - **Mixed** (a C# project that also contains a UPM package, e.g. one shipping a SourceGenerator) → the package goes through Unity **and** the repository's own solution through the .NET SDK; ReSharper runs over **both** solutions, because the generator lives in the repository's own one and the UnityEngine references only in Unity's.
   - **Anything else** → neither step runs; the review happens without a build gate.
6. **Build & test a Unity package in the PR's own project.** UPM packages have no compilable project of their own, so each pull request that contains one gets a Unity project of its own — created with the Unity CLI (`unity projects create`) as `<repo>-PR<number>` under the working root (`state-dir`), from `UNITY_TEMPLATE` for `UNITY_EDITOR_VERSION`. The project is pointed at the organization's package feeds (see [Scoped registries](#scoped-registries)), so the package can resolve its own dependencies. It is pulled in as a `file:` dependency and registered in `testables` (see [Running the package's own tests](#running-the-packages-own-tests)) so Unity compiles the package's test assemblies too; the CLI then regenerates the real sln/csproj in batch mode and compiles, and runs the tests. Compile errors land as inline comments on the changed line (or a status comment otherwise); test failures land in that status comment. Later pushes reuse the project and the synced clone; the project is unregistered from the Hub and the whole directory is deleted when the PR closes. Self-skips when the Unity CLI cannot be found — see [Everything Unity goes through the CLI](#everything-unity-goes-through-the-cli).
7. **Build the repository's own solution with the .NET SDK.** This is the Unity step's counterpart for the C# side, and it runs for any repository that ships a solution — a pure C# project, and also the C# project around a UPM package. `dotnet build` always, and `dotnet test` only when that solution actually references a test project. Reports the same way (compile errors inline on the changed line, everything else in a status comment), and **also blocks approval**. Self-skips when `dotnet` is not on `PATH` or the repository has no solution of its own.
8. **Run ReSharper** (`jb inspectcode`) over everything that covers the clone — the package's own generated projects, the repository's own solution, and Unity's solution when neither of those exists — honouring the repository's own `.editorconfig`, and post each `WARNING`/`ERROR` on a changed line as its own inline comment prefixed `ReSharper:`. This is the deterministic, project-specific analysis (naming, style, redundancies, correctness) the model is told **not** to duplicate. Findings from several targets are merged and de-duplicated, since they share most of their sources. The generated Unity solution is repaired first — see [The generated solution is repaired before use](#the-generated-solution-is-repaired-before-use). Self-skips when the runner has no `jb` or there is nothing to inspect.
9. Let the model drive the review through tools (`read_file`, `get_file_diff`, `post_inline_comment`, `list_threads`, `resolve_thread`, `finish`); the build/test status is given to it as context. `list_threads` reports resolved threads alongside open ones, and every inline comment in the conversation is marked with its thread state (`thread resolved` / `thread open`), so a finding that is already settled is not raised a second time.
10. Retire what earlier rounds raised, then approve if nothing is left open. This runs after **every** review — a review is the bot looking at the current state of the pull request, so it is also the moment a thread the code has since dealt with gets resolved. A repository that reviews only on demand would otherwise never retire anything.
    - After a push, the threads are judged against the diff of **that push alone** (`before...after` from the event). After any other review, against the whole pull request.
    - In a thread, a concern answered by discussion counts as settled even when no code changed.
    - Once no unresolved thread remains and the review came back clean, the bot submits an `APPROVE` review. Thread resolution uses the GraphQL API — the REST API cannot do it.
    - A failed build or test retires threads but never approves.

### Three stages, one job

The action runs the pipeline as three steps, one Python process each:

| Step | What it does |
| --- | --- |
| `main.py checks` | clone, classify, build, test — and write down what the rest needs |
| `main.py static` | `jb inspectcode` over what the checks stage left behind |
| `main.py review` | the model's review, then settle the threads and approve |

**A closed pull request gets one step, not those three.** `github.event.action == 'closed'` selects `cleanup`, which deletes what the pull request left behind and nothing else, and skips the three; every other event is the other way round. Without it the run for a *close* announced "Build and test the pull request", "Run the static analysis" and "Review and settle the threads" and then did none of them — three steps named for work they were not going to do, which is the same lie the pipeline refuses elsewhere. The step names in the calling workflow are chosen the same way, by an expression, so the one step reads *Forget the closed pull request* or *Review the pull request* depending on why it is running.

The stage is still the authority: a closed pull request that arrives some other way — a comment on it, a day later — is forgotten by the first stage regardless of what the workflow skipped. `cleanup` on an open pull request says so and deletes nothing.

**No step sets a timeout, because a composite action's steps cannot.** `timeout-minutes` is rejected outright — "Unexpected value 'timeout-minutes'" — and the runner refuses the whole manifest, so no step runs at all. The ceiling is therefore the job's, set to 150 minutes in `code-review.yml` rather than GitHub's 360-minute default, and everything under it is bounded by the deadlines the stages put on their own subprocesses.

**A deadline ends the tool, not just the process that started it.** `subprocess.run(timeout=...)` kills its direct child, which is the CLI — and leaves everything the CLI started running: the editor `unity run` launched, MSBuild's worker nodes, `inspectcode`'s JVM. On a runner reused across jobs those accumulate, and an editor left behind holds the PR's Unity project lock. `subproc.py` gives the child a session of its own and signals the whole process group — SIGTERM, then SIGKILL after a grace period — so the deadline leaves nothing behind. Measured on Linux, for a tool that starts a helper and hangs: both return at the deadline, and only `subproc.run` returns with the helper gone.

**The order is a constraint, not a preference.** `review` settles the open threads and approves, and it is what decides whether anything may be approved at all. A static analysis that posted a finding *after* that step would leave the pull request approved with a fresh unresolved thread on it. So the analysis always runs before the review, and `review` is always last.

**A finding does not fail a step; a crash does.** No step is `continue-on-error`. A broken build, failing tests, a missing analyzer — each is posted as a comment and the step still exits 0, so the steps after it run. A crash stops the run and turns the job red, exactly as it does in one process. The split must not turn a loud failure into a green job whose review quietly had no build results; that is the failure mode this pipeline has spent the most effort on.

**The model's key is not in the step that runs the pull request's code.** `checks` and `static` execute arbitrary code from the pull request — MSBuild targets, Unity editor code, test assemblies, the repository's own analyzers. Neither needs to call the model, so neither is given `OPENAI_API_KEY`; `load_config(require_openai=False)` is what enforces it. Each step also declares only the environment its own stage reads, so the shared configuration surface is two variables instead of twenty.

**A comment only reaches the build step when it asks for one.** `@perotoolsbot review` and `@perotoolsbot rebuild` want the gates, and a command is deterministic — the person who wrote it knows what they meant — so the checks and static stages run for it exactly as they do for a push, and the review step reads their results instead of building again. A comment that asks for nothing (`prompt:`, or a question) stands them both down; building for every comment that mentions the bot would mean a Unity build for "why did you flag this?". **A review asked for in prose** is the one case that cannot be routed this way: recognising the request is the classifier's job, and that is a model call inside the review step, so those runs build and analyse *there* — in the step that also holds the model's key. The log says which happened, in both directions:

```
Using the build and test results the checks stage left for this run.
The checks stage did not run for this one; running the build, the tests and the static analysis here instead.
```

**What the later stages need is written to `.ai-review/checks-<run>.json`**, because processes cannot share memory: the clone, the classification, the generated projects to inspect, whether the build blocked approval, the two build/test summaries, and whether the static analysis posted anything. The section the model is shown is derived from those summaries rather than stored beside them, so there is one spelling of it whichever step produced it. The file is named after the run, so two runs of one pull request (a push and an @-mention a minute later) each read their own results rather than whichever finished last, and it is validated on load against both the run and the head SHA. No state is not an error: the static analysis says it has no clone to analyse and stands down, and a review that finds no state runs the gates itself, saying so.

`main.py all` runs the three in order in one process. That is what a manual run on the runner wants, and it is the fallback if the split ever has to be undone. `main.py <stage>` alone is the other half of the same idea: with a PR already checked out, `python3 main.py static` re-runs just the analysis against the same clone.

### One directory per pull request

A pull request owns exactly one directory on the runner, named `<repo>-PR<number>` (e.g. `ToolsWorkflow-PR42`) under `<state-dir>/<owner>/`. Everything a review of it needs lives inside:

```
<state-dir>/<owner>/ToolsWorkflow-PR42/
    Assets/ ProjectSettings/ Packages/ …   the Unity project — the folder name is the Unity project name
    .ai-review/session.jsonl               the agent session log
    .ai-review/pkg/                        the PR head clone the project references as a file: package
    .ai-review/editor.log                  Unity's batch-mode log
    .ai-review/resharper-*.xml             ReSharper's reports, one per solution inspected
    .ai-review/checks-<run>.json           what the checks stage found, for the stages after it
```

The session and the Unity project therefore share one lifecycle: both are created on the PR's first review, both are reused by every later review of that PR (the clone is `git`-synced to the new head, the session is appended to rather than rebuilt), and both are deleted together when the PR closes. The owner is a path component above the per-PR directory rather than part of its name, so the leaf keeps the name the PR is known by while two organizations sharing a repository name still get separate directories.

A repository that is not a UPM package has no Unity project, so its directory holds only `.ai-review/` — same layout, same lifecycle, nothing to unregister.

`.ai-review` is dot-prefixed, so Unity's asset database ignores it: the log, the clone, the session and the reports are never imported as assets and cannot end up in a build.

The clone briefly waits in a sibling staging directory (`.<repo>-PR<number>.staging`) on a PR's first review: the Unity CLI refuses to lay a project into a path that already exists, and the PR directory *is* the project, so the project is created first and the clone is then renamed into place. The rename is within one directory, so it costs nothing, and the staging directory is swept at cleanup if a run dies in between.

Changing the layout means the first run after an upgrade finds no session for an open PR and rebuilds it from GitHub — the session is an optimization, so that costs one fuller review and nothing else. Directories left behind by the older shared-host layout are swept away at the same time.

### Everything Unity goes through the CLI

The Unity CLI is the only Unity thing the runner needs. It creates each PR's project, resolves the editor from that project's own `ProjectVersion.txt`, and runs the build and the tests:

| Step | Command |
| --- | --- |
| layout the project | `unity projects create <name> --path <parent> --editor-version <v> --template <t> --no-cloud` |
| regenerate + compile | `unity run <project> --log-file <f> --no-tail --timeout <s> -- -executeMethod UnityEditor.SyncVS.SyncSolution` |
| run tests | `unity test <project> --mode EditMode --output <nunit.xml> --timeout <s>` |

There is no editor path to configure, and none to fall out of step with the project: the CLI reads the version back out of the project it is running. The editor binary is never looked for.

Two things that do not work, and why:

- **`-quit` cannot be forwarded to `unity run`.** The CLI owns `-batchmode`, `-nographics`, `-quit`, `-projectPath` and `-logFile`, and rejects any of them after `--`. Only the arguments meant for the Editor itself go there.
- **`unity run -runTests` produces no report.** The CLI always passes `-quit`, and the editor quits before the test run has written anything — which reads as "no tests, no failures" and is exactly the silent pass this pipeline avoids elsewhere. `unity test` exists for this and writes the NUnit report itself; a failing run exits non-zero *and* leaves the report, and the failures are read from it.

The CLI must be executable by the user the runner runs as, and so must the editor that the CLI resolves (a Hub under `/root` is not visible to a runner running as anyone else). Where the CLI itself lives is found rather than configured — see [Nothing asks where a tool is](#nothing-asks-where-a-tool-is).

The action also normalises `XDG_RUNTIME_DIR` before running: a CI service account has no login session, so it is either unset or inherited from whoever started the runner — another user's directory — and the CLI's auth broker needs one it can create a socket in. Getting that wrong surfaces much later as a licence failure, so it is fixed here rather than left to each runner's configuration.

### Scoped registries

Every per-PR Unity project is pointed at the organization's package feeds, so a package under review can resolve dependencies (UniTask, Nifty, NuGet-for-Unity, …) that are not in the Unity registry — without them the build fails on a package Unity simply cannot find:

| Name | URL | Scopes |
| --- | --- | --- |
| `Peropero` | `https://unitypkg.peropero.net` | `com.prpr` |
| `OpenUPM` | `https://package.openupm.com` | `com.niftyhat`, `com.cysharp`, `org.nuget.castle`, `org.nuget.system`, `org.nuget.google`, `org.nuget.microsoft`, `org.nuget.zlinq`, `com.neuecc` |

The list is `SCOPED_REGISTRIES` in `unity_runner.py`. It is written into the project's `Packages/manifest.json` and **merged, never overwritten**: a registry a previous run or the template already declared keeps its own scopes and URL, and a registry of the same name keeps every scope it had — the wanted ones are added to it. It is re-applied on every run, including the reuse path, so a project created before a registry was added is brought up to date instead of staying stale.

### Running the package's own tests

The package under review is also registered in the project's `testables` (next to its `file:` dependency), which is what makes Unity compile its test assemblies and run them. A package that is only a dependency has its tests **ignored, not failed** — the test run reports nothing at all, so a package with broken tests would look like a clean pass. Like the registries, the entry is written idempotently and re-applied on every run, so a project created before this existed is fixed rather than left silently untested.

The project's `com.unity.test-framework` is raised to 1.3.4 if it is missing or older. The 3D template pulls an older one in through `com.unity.feature.development`, and a test assembly written against the newer TestRunner API does not compile against it. It is raised, never lowered: an explicit newer version, or a `file:`/git reference, is left alone.

One consequence of compiling the tests at all: a package whose tests do not compile gets **no project files generated for it**, so ReSharper cannot inspect that package in that run. The compile errors themselves are still posted on the changed lines, so the pull request is told what is wrong — but the static analysis is blind until they are fixed.

### The generated solution is repaired before use

Unity writes one solution entry per generated project, and it generates both `<Name>.csproj` and `<Name>.Player.csproj` for the same assembly — labelling both with the same display name. MSBuild rejects such a solution outright (`MSB5004: The solution file has two projects named "Unity.Timeline"`), which stops `jb inspectcode` before it produces any report at all, leaving ReSharper silently doing nothing. The duplicate entries are renamed after their project files, which costs nothing and makes the solution usable.

The repair is applied twice on purpose: once right after generation, and again after the test run — **every Editor launch rewrites the solution**, so the test run brings the duplicates back. The second pass is the last thing that happens before the solution is handed to ReSharper, and nothing after it starts Unity again.

The old project files are deleted before regenerating, for the same reason in reverse. Generation stops as soon as a solution exists — that is how a repository whose project-file method does nothing is caught — but a solution **left over from the previous run** satisfies that check on its own, so the first method was never asked to prove itself, the files were never rewritten, and the analysis ran against a model of a project that no longer matched the code: files this push added were not in it at all, and ReSharper sees no findings in a file it does not know about. Clearing `*.sln` and `*.csproj` from the project root before the first attempt is what makes the question real again. Nothing else is touched — `Library/`, `Temp/`, the manifest and the package reference all stay, so the regeneration is still incremental.

### How inspectcode is invoked

Three things used to stop `jb inspectcode` from writing any report at all, and all three look exactly like "no findings" from the outside. None is visible unless you know to look.

**It is found the way the Unity CLI is.** `jb` is a .NET tool installed per user, so it lands in `~/.dotnet/tools` — a directory that is on an interactive `PATH` and on no service account's. A runner that has `jb` and can run it by hand reported "not found on `PATH`" and silently analysed nothing. It is now resolved once per run across `PATH`, `~/.dotnet/tools`, `~/.local/bin` and `/usr/local/bin` and printed once as a fact — see [Nothing asks where a tool is](#nothing-asks-where-a-tool-is).

**It is told not to build.** inspectcode builds the solution before inspecting it, and Unity's generated projects are written for Unity's own compiler settings — a generic MSBuild run trips over them (obsolete-API warnings promoted to errors, output paths it cannot open), and a failed build means no report. The pipeline has already compiled the code anyway: Unity for a package, the .NET SDK for a C# project. With `--no-build`, inspectcode still evaluates MSBuild for the project model and the file set; an A/B run over the same solution produced **byte-identical findings** with and without the build, so nothing is lost. Set `resharper-build` / `INSPECT_BUILD` to put the build back if a solution's real sources only appear after one.

**Its MSBuild is pinned.** inspectcode picks the **newest** .NET SDK it can find, so a half-installed preview wins and the build fails (`MSB4236`, `NETSDK1045`). `resharper-dotnet-sdk` / `INSPECT_DOTNET_SDK` passes `--dotnetcoresdk=<version>` instead. The pinned SDK must be able to build what the repository targets — an SDK cannot target a newer framework than it ships, so pinning `10.0.x` against a `net11.0` project just moves the error. The log prints this hint whenever a missing report shows SDK-resolution symptoms.

Warnings-as-errors is switched off in both modes, so that turning the build back on does not immediately reintroduce the first failure.

### What ReSharper is pointed at

A UPM package is inspected through **its own generated projects**. Unity writes one `.csproj` per assembly into the project root, and a package's asmdefs get their own — so the package is a target ReSharper accepts directly, and the analysis is about the reviewed code and nothing else: five findings over a handful of files, where the whole solution yields forty-eight thousand, nearly all of them in Unity's own packages.

Those projects are also what makes a run survive a missing solution. `jb inspectcode` takes a csproj where a solution is missing or unusable, which is exactly the case that used to end as "no solution for this repository" and no static analysis at all. The solution is kept as the fallback, for anything the package's own projects do not cover.

Three lines in the log say what was covered, and they only mean something together:

```
Package assemblies: Demo, Tests
Generated projects for the package: Demo.csproj, Tests.csproj
Other generated projects, not the package's: Assembly-CSharp.csproj
```

The first is what the package's asmdefs say it is, the second what Unity generated for it, and the third what else exists — because an assembly in the first line with no counterpart in the second is a package that is only *partly* inspected, and a partial inspection reports no findings, exactly like a clean one. Unity names a generated project after its asmdef, so the comparison is a name match and a platform-limited or constraint-gated asmdef may legitimately have no project of its own.

For a repository that ships its own solution, that solution stays a target as well — see [Review pipeline](#review-pipeline).

### When ReSharper names the fix

The naming inspection does not just object, it says what it wants instead — and the report carries no structured fix, only the sentence:

```xml
<Issue TypeId="InconsistentNaming" File="Runtime/TestScript.cs" Line="5"
       Message="Name 'wrongMethodFormat' does not match rule 'Methods'.
                Suggested name is 'WrongMethodFormat'." />
```

So the sentence is read, and when the rename is the whole fix it becomes a GitHub suggestion — the author gets a **Commit suggestion** button instead of a description of one:

> ⚠️ **ReSharper**: Name 'wrongMethodFormat' does not match rule 'Methods'. Suggested name is 'WrongMethodFormat'.
>
> ```suggestion
>     private void WrongMethodFormat() { }
> ```

Three conditions, because a suggestion is an *edit* one click from being committed, and a wrong one is worse than no suggestion at all:

- **The identifier has to be on the line, exactly once, as a whole word.** `Test` inside `TestRunner` is not the name the report meant, and a line mentioning it twice does not say which one to change. A member access (`this.wrongMethodFormat`) is not rewritten either — the suggestion replaces the declaration, not a call.
- **The block holds the whole line**, indentation included, because that is what the click substitutes.
- **Nothing else in the clone may use the name.** This is the one that matters: a suggestion edits the single line it is anchored to, and a rename is usually more than one line. The clone is searched once for every name being renamed, and the search is not naive about declarations — an occurrence on a line ReSharper flagged with the *same* naming finding is a declaration of its own symbol, so the two `wrongMethodFormat` methods in CITest's two classes can each be renamed independently. Those flagged lines come from the whole inspection and not from the findings being posted: the twin declaration is usually on a line the pull request did not write, and it is exactly the one that makes the rename safe. Anything that is neither the anchored line nor such a declaration is a use:

```
ReSharper: not suggesting a rename of 'wrongMethodFormat' at Runtime/TestScript.cs:3 —
it is used elsewhere (first at Caller.cs:1), and a suggestion would edit this line only.
```

That occurrence is deliberately more permissive than the rewrite: `s.wrongMethodFormat()` — a preceding dot — is exactly the use that makes a one-line rename wrong, so the search counts it. A repository too large to walk in `RENAME_SCAN_FILES` files quietly loses its suggestions rather than costing the run. When none of this holds the comment is posted as it always was: the message already carries ReSharper's own "Suggested name is …", so the information is never withheld, only the button.

### A file no assembly compiles

Unity compiles what an asmdef declares and nothing else. A `.cs` file sitting in a directory — or under a parent directory — with no asmdef is imported as an asset and compiled by no assembly at all, so the build succeeds, the tests pass, and the static analysis reports nothing: **three green results about code nothing has read.** It is also the answer to the question a reviewer asks when the analysis ran and said nothing about their file.

So the changed files are checked against what the generated projects actually compile, and a file in neither is reported on the pull request, once:

```
⚠️ 以下改动文件没有被任何程序集编译，因此本次编译、单元测试和静态分析
都没有覆盖它们——三项全绿，但关于这些文件的结论没有依据。

- `Runtime/TestScript.cs`
```

The comparison is exact — the `<Compile Include>` items of the package's own generated projects against the pull request's changed `.cs` files under the package root. Files under a `~` directory (`Samples~`, `Documentation~`) are excluded, because Unity ignores those on purpose, as are files the pull request deleted and files outside the package. Nothing is claimed when the package's projects are not known: an unanalysable repository must not look like one with an uncovered file.

This is the one check that could not have been written as "did the step fail". It reports a *pass* that does not mean what it looks like.

### ReSharper findings are not repeated

The static-analysis step posts on its own, without going through the model, so it does not inherit the model's three defences against repeating itself (it only sees the latest push's diff, it remembers what it posted, and it reads the thread states). It has its own two:

- **Lines are scoped to the push, and to the lines the push wrote.** On a later `synchronize`, the lines considered are the ones *that push* touched (`before...after`), not every line in the pull request. Within a file it is the added lines — the `+` ones — and not the context around them: a hunk carries three lines of the surrounding code either side, and counting those as changed had the analysis reporting on the class *above* the addition, in a pull request that never touched it. A first review still covers the whole diff. The build and test steps keep the full file list on purpose: a broken build is a broken build, whichever push caused it.
- **A finding already open is not raised again.** Before posting, the PR's inline comments and their thread states are read, and a finding whose identical comment (same path, same text — the bodies are deterministic) is already in an **unresolved** thread is skipped. A finding whose thread was **resolved** and is reported again is posted: that is either a regression or a resolution that was wrong, and both are worth seeing. If the thread states cannot be read, nothing is suppressed — a repeated comment is a smaller failure than a dropped one.

Every finding is anchored by the changed line's text rather than a line number, so it can only land on a line that is actually in the diff. The line number from the report goes with it as a hint, because the text alone is ambiguous whenever the same statement appears twice in one hunk — a class copied below another, a moved block — and without the hint the anchor takes the *first* occurrence: two findings collapse onto one line, and neither is where the report said. Findings that cannot be anchored are dropped rather than posted somewhere approximate.

If solutions were available but `inspectcode` produced no report for any of them — a broken toolchain, a solution it cannot build — the PR gets **one** note saying the static analysis did not run, rather than silence that looks like a clean pass. It is posted once per PR, not once per push. A repository with no solution at all says nothing: there was nothing to analyse.

### There is no summary

Every finding is a `post_inline_comment` call. There is deliberately **no overall summary and no review body** — the bot only ever speaks through inline comments and the approval.

A finding that is not about a particular line — missing tests, a missing changelog or documentation entry, a design or process concern — is anchored to the closest changed line it relates to rather than dropped. A finding that is never attached to a line is a finding that never reaches the pull request.

Praise is not a finding. A comment that only compliments a change — however technically detailed — is never posted; the approval is the only positive signal, so a clean PR stays silent.

`finish(verdict)` states `approve`, `comment` or `block`; `approve` is what approves the PR. A clean PR therefore produces no comments at all — the approval is the report. The review takes as many steps as it needs: when the transcript outgrows its budget the oldest tool results are stubbed out (the diff and the conversation are never touched), so a long investigation neither overflows the model's window nor makes every later step expensive. The step cap is only a runaway guard, and the final step tells the model to finish on time; if it still ends without `finish`, nothing is posted and nothing is approved, and the log says why (`Ignored the review: …`). No labels are applied. If the model answers in prose instead of calling the tools, the run falls back to parsing that text into a review body, which is the only path that posts one (and the only path `SILENT_MODE` still affects).

## Files

- `main.py` — entry point and orchestration.
- `action.yml` — composite action definition.
- `github_client.py` — GitHub REST API client.
- `ai_client.py` — OpenAI-compatible chat completions client.
- `repo_kind.py` — what the cloned repository is (UPM package / C# project / mixed / other) and which solutions it ships.
- `unity_runner.py` — per-PR Unity project creation, build, unit tests and project-file generation.
- `dotnet_runner.py` — the `.NET` build/test gate for repositories that ship their own solution.
- `build_log.py` — shared parsing of MSBuild compiler errors, NUnit and TRX test reports.
- `inspect_code.py` — ReSharper static analysis (`.editorconfig`-driven, multi-solution).
- `pr_workspace.py` — the one directory per PR: session, Unity project and package clone together, plus the PR head clone.
- `stage_state.py` — what the checks stage hands to the static and review stages, as a per-run JSON file inside the PR's directory.
- `tool_path.py` — finding `unity`, `jb` and `dotnet` without being told where they are, and telling "not installed" apart from "not this user's to run".
- `subproc.py` — running an external tool under a deadline that ends the whole process group, so a killed build leaves no editor, MSBuild node or JVM behind.
- `session.py` — per-PR session log (append-only JSONL, inside the PR's directory).
- `prompt.md` — default review prompt (auto-improveable via natural language).