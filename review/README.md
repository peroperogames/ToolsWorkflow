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

The GitHub App token is generated in `code-review.yml` via `actions/create-github-app-token` and passed to the composite action as `github-token`. **It lives for one hour**, and the clock starts when the token is minted, not when the gate starts: a run that spends longer than that testing and analysing (two thirty-minute test timeouts are enough) reaches the reporting step with nothing left to authenticate with, and GitHub answers `401 Bad credentials`. That is not a comment worth retrying — the log says so in as many words — and it is a reason to make the gate finish in minutes rather than a reason to post harder. Per-PR state lives in the runner's working directory (not inside the action): each pull request owns one directory named `<repo>-PR<number>` that holds both its session and its Unity project, and the whole directory is removed when the PR closes.

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
| `resharper-ignore-rules` | `INSPECT_IGNORE_RULES` | *(empty)* | Comma-separated ReSharper naming rules whose findings are dropped, e.g. `Unity serialized field`. For a rule the analyser reports and the team's IDE cannot display or silence — see [The analyser and the IDE disagree](#the-analyser-and-the-ide-disagree). |
| — | `UNITY_TIMEOUT` / `DOTNET_TIMEOUT` | `1800` | Seconds either build step may take before it is ended — the tool and everything it started — and reported as skipped. |
| — | `UNITY_TEST_TIMEOUT` | `600` | Seconds the Unity test run may take, separately from the build — a hanging suite then costs only its own deadline. Every suite seen here finishes in seconds, so ten minutes is already generous: a run still going is stuck, not slow. |

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
| `review` | Review the pull request now — everything: clone, build, tests, static analysis. |
| `review(o1)` / `review(o2)` / `review(o3)` | The same review at a chosen level: the diff alone, with the build and the tests, or with everything. `o3` is what a bare `review` means. |
| `rebuild` | Re-run the build, test and static-analysis steps only — no review, no approval. |

The words live in one registry (`COMMANDS` in `main.py`): each entry names the command, what the text after it means, and its handler, and the parsing, the logging and the precedence all come from there rather than from a separate parser and branch per command.

- **Improve the prompt** — `@perotoolsbot prompt: <what to change>` rewrites review criteria and opens a pull request with the result. Nothing lands without a human merging that PR, and the bot's token needs write access to the target repository (it already has it for ToolsWorkflow). The command picks the target, and the colon is optional in either form (`:` and `：` both work):
  - `@perotoolsbot prompt: ...` and `@perotoolsbot prompt(this): ...` — the reviewed repository's own criteria file (`PROJECT_PROMPT_PATH`, written fresh if it does not exist yet). The PR is opened against that repository, so a project's feedback cannot change how other projects are reviewed.
  - `@perotoolsbot prompt(base): ...` — the shared prompt in ToolsWorkflow, the single reusable source of the review prompt. The PR is opened against ToolsWorkflow.
  - This command is the **only** way a prompt change happens. A comment that merely asks for a different review style ("be stricter", "别报样式问题") is never guessed into one — the bot replies pointing at the command instead.

- **Code changes** — e.g. `@perotoolsbot fix src/foo.py`. The bot reads the current file contents, generates code changes, and submits a PR to the current repository's feature branch.

- **Review request** — `@perotoolsbot review` starts a review without consulting the intent classifier, so a repository that only ever reviews on demand cannot have its request read as something else. The word must be `review` right after the mention, and whatever follows becomes a note: `@perotoolsbot review this PR for me.` and `@perotoolsbot review: 关注并发` are both the command. Any other way of asking (`@perotoolsbot 帮忙看下`) still goes through the classifier.

  A review started this way runs **exactly what an automatic one runs** — the clone, the Unity/.NET build and test gates, and ReSharper — before the model sees anything, so a broken build cannot be approved just because nobody pushed. The one difference is scope: it covers the whole pull request, not the latest push.

  **The level says how much of that to run.** A bare `review` is `review(o3)`:

  | Level | What runs | Approval |
  | --- | --- | --- |
  | `review(o1)` | the model reads the diff and the conversation — no clone, no Unity project, no tests, no ReSharper | **never**: nothing was verified |
  | `review(o2)` | `o1` plus the clone, the Unity/.NET build and the unit tests | as usual, blocked by a failed build or test |
  | `review(o3)` | `o2` plus the static analysis — the same work a push triggers | as usual |

  `o1` is the fast path for a change whose build is expensive or beside the point — documentation, a comment, a config file — and for a first look before deciding whether the change is worth a full pass. It cannot approve, and that is the point rather than an oversight: an approval is this pipeline saying the change compiled and its tests passed, and a review that ran neither has nothing to say about either. Threads are still settled — a concern the new code has dealt with is retired whether or not a build ran.

  `o2` is the middle: the build and the tests, no analysis. The model is told the analysis did not run, because the prompt otherwise promises that style and naming are somebody else's pass — and here there is nobody.

  At `o1` and `o2` the model is told what is missing, in the same `## 构建与测试状态` section the build step writes to, so it never reviews as though the change were verified.

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
   - **Unity package** (`package.json`) → compiled and tested in a per-PR Unity project; ReSharper runs over Unity's solution, filtered to the package's own projects.
   - **Pure C# project** (`sln`/`slnx`/`csproj`) → built and tested with the .NET SDK; ReSharper runs over the repository's own solution.
   - **Mixed** (a C# project that also contains a UPM package, e.g. one shipping a SourceGenerator) → the package goes through Unity **and** the repository's own solution through the .NET SDK; ReSharper runs over **both** solutions, because the generator lives in the repository's own one and the UnityEngine references only in Unity's.
   - **Anything else** → neither step runs; the review happens without a build gate.
6. **Build & test a Unity package in the PR's own project.** UPM packages have no compilable project of their own, so each pull request that contains one gets a Unity project of its own — created with the Unity CLI (`unity projects create`) as `<repo>-PR<number>` under the working root (`state-dir`), from `UNITY_TEMPLATE` for `UNITY_EDITOR_VERSION`. The project is pointed at the organization's package feeds (see [Scoped registries](#scoped-registries)), so the package can resolve its own dependencies. It is pulled in as a `file:` dependency and registered in `testables` (see [Running the package's own tests](#running-the-packages-own-tests)) so Unity compiles the package's test assemblies too; the CLI then regenerates the real sln/csproj in batch mode and compiles, and runs the tests. Compile errors land as inline comments on the changed line (or a status comment otherwise); test failures land in that status comment. Later pushes reuse the project and the synced clone; the project is unregistered from the Hub and the whole directory is deleted when the PR closes. Self-skips when the Unity CLI cannot be found — see [Everything Unity goes through the CLI](#everything-unity-goes-through-the-cli).
7. **Build the repository's own solution with the .NET SDK.** This is the Unity step's counterpart for the C# side, and it runs for any repository that ships a solution — a pure C# project, and also the C# project around a UPM package. `dotnet build` always, and `dotnet test` only when that solution actually references a test project. Reports the same way (compile errors inline on the changed line, everything else in a status comment), and **also blocks approval**. Self-skips when `dotnet` is not on `PATH` or the repository has no solution of its own.
8. **Run ReSharper** (`jb inspectcode`) over everything that covers the clone — the repository's own solution and Unity's, the latter filtered to the package's own generated projects (`--project`) — honouring the repository's own `.editorconfig`, and post each `WARNING`/`ERROR` on a changed line as its own inline comment prefixed `ReSharper:`. This is the deterministic, project-specific analysis (naming, style, redundancies, correctness) the model is told **not** to duplicate. Findings from several targets are merged and de-duplicated, since they share most of their sources. The generated Unity solution is repaired first — see [The generated solution is repaired before use](#the-generated-solution-is-repaired-before-use) — and the package's projects are what the analysis is limited to — see [What ReSharper is pointed at](#what-resharper-is-pointed-at). Self-skips when the runner has no `jb` or there is nothing to inspect.
9. Let the model drive the review through tools (`read_file`, `get_file_diff`, `post_inline_comment`, `list_threads`, `resolve_thread`, `finish`); the build/test status is given to it as context. `list_threads` reports resolved threads alongside open ones, and every inline comment in the conversation is marked with its thread state (`thread resolved` / `thread open`), so a finding that is already settled is not raised a second time.
10. Retire what earlier rounds raised, then approve if nothing is left open. This runs after **every** review — a review is the bot looking at the current state of the pull request, so it is also the moment a thread the code has since dealt with gets resolved. A repository that reviews only on demand would otherwise never retire anything.
    - After a push, the threads are judged against the diff of **that push alone** (`before...after` from the event). After any other review, against the whole pull request.
    - In a thread, a concern answered by discussion counts as settled even when no code changed.
    - **A thread the bot resolves says why.** The judge returns a sentence per thread, and it is posted *inside* the thread before the thread is closed; the model's own `resolve_thread` tool requires the same sentence, and asks for it again when it is missing. A silent resolution looks exactly like a wrong one: the author sees a finding disappear with nothing to argue with.
    - **A thread this run posted is never resolved by this run.** The ids of the comments posted during the review are excluded, because a finding from a minute ago has not been dealt with by anything — being closed by the same pass that posted it is indistinguishable from a review that said nothing.
    - **A thread is settled once, even when runs overlap.** Every comment on a pull request starts its own run, so five replies written within a minute used to be five runs listing the same unresolved threads at the same moment, settling all of them and posting a note for each — the author got four identical `✔️` replies in one conversation. Runs for one pull request now queue behind each other (`concurrency` in `code-review.yml`), and each thread's state is asked again immediately before it is resolved, so a thread another run finished is left alone.
    - Once no unresolved thread remains and the review came back clean, the bot submits an `APPROVE` review. Thread resolution uses the GraphQL API — the REST API cannot do it.
    - A failed build or test retires threads but never approves.
    - "Never approves" is enforced on the posted review as well as on the decision to submit one: `determine_event` reads the model's own prose, so a body containing a ✅ would otherwise become a GitHub `APPROVE` whichever step sent it. When this run may not approve, the same text is posted as a `COMMENT` — the words are the model's, the verdict is not one this run is entitled to give.

### Three stages, one job

The action runs the pipeline as three steps, one Python process each:

| Step | What it does |
| --- | --- |
| `main.py checks` | clone, classify, build, test — and write down what the rest needs |
| `main.py static` | `jb inspectcode` over what the checks stage left behind |
| `main.py review` | the model's review, then settle the threads and approve |

**Two more steps follow the three, and neither is a stage of a review.** `Upload the reports` puts what the stages wrote into the run's artifacts, and `main.py artifact-link` goes back to the comment and points it at the artifact itself (see *Where the reports go*). The upload runs after the static analysis so the analysis is in the artifact too, and both run before the review, which is what approves: a report posted after the approval would be a report nobody is going to open.

**A closed pull request gets one step, not those three.** `github.event.action == 'closed'` selects `cleanup`, which deletes what the pull request left behind and nothing else, and skips the three; every other event is the other way round. Without it the run for a *close* announced "Build and test the pull request", "Run the static analysis" and "Review and settle the threads" and then did none of them — three steps named for work they were not going to do, which is the same lie the pipeline refuses elsewhere. The step names in the calling workflow are chosen the same way, by an expression, so the one step reads *Forget the closed pull request* or *Review the pull request* depending on why it is running.

The stage is still the authority: a closed pull request that arrives some other way — a comment on it, a day later — is forgotten by the first stage regardless of what the workflow skipped. `cleanup` on an open pull request says so and deletes nothing.

**No step sets a timeout, because a composite action's steps cannot.** `timeout-minutes` is rejected outright — "Unexpected value 'timeout-minutes'" — and the runner refuses the whole manifest, so no step runs at all. The ceiling is therefore the job's, set to 150 minutes in `code-review.yml` rather than GitHub's 360-minute default, and everything under it is bounded by the deadlines the stages put on their own subprocesses.

**A deadline ends the tool, not just the process that started it.** `subprocess.run(timeout=...)` kills its direct child, which is the CLI — and leaves everything the CLI started running: the editor `unity run` launched, MSBuild's worker nodes, `inspectcode`'s JVM. On a runner reused across jobs those accumulate, and an editor left behind holds the PR's Unity project lock. `subproc.py` gives the child a session of its own and signals the whole process group — SIGTERM, then SIGKILL after a grace period — so the deadline leaves nothing behind. Measured on Linux, for a tool that starts a helper and hangs: both return at the deadline, and only `subproc.run` returns with the helper gone.

**Whatever is left behind anyway is reaped before the next run starts.** A cancelled job, a runner restart or somebody trying the tests by hand can still leave an editor holding the project, and Unity then refuses to open it — `The project at "…" is already open in a running Editor (PID 295801)` — which costs the build, the tests *and* the static analysis of every later run of that pull request, because the check happens before anything else. `reap_stale_editor` reads the editor's PID from `/proc` before the Unity step begins and ends it, then removes the `Temp/UnityLockfile` it leaves: the project belongs to that pull request and nothing of ours has started yet, so whoever holds it is stale by definition.

**The order is a constraint, not a preference.** `review` settles the open threads and approves, and it is what decides whether anything may be approved at all. A static analysis that posted a finding *after* that step would leave the pull request approved with a fresh unresolved thread on it. So the analysis always runs before the review, and `review` is always last.

**A finding does not fail a step; a crash does.** No step is `continue-on-error`. A broken build, failing tests, a missing analyzer — each is posted as a comment and the step still exits 0, so the steps after it run. A crash stops the run and turns the job red, exactly as it does in one process. The split must not turn a loud failure into a green job whose review quietly had no build results; that is the failure mode this pipeline has spent the most effort on.

**The model's key is not in the step that runs the pull request's code.** `checks` and `static` execute arbitrary code from the pull request — MSBuild targets, Unity editor code, test assemblies, the repository's own analyzers. Neither needs to call the model, so neither is given `OPENAI_API_KEY`; `load_config(require_openai=False)` is what enforces it. Each step also declares only the environment its own stage reads, so the shared configuration surface is two variables instead of twenty.

**A comment only reaches the build step when it asks for one.** `@perotoolsbot review` and `@perotoolsbot rebuild` want the gates, and a command is deterministic — the person who wrote it knows what they meant — so the checks and static stages run for it exactly as they do for a push, and the review step reads their results instead of building again. The level picks how much of that switch is on: `review(o1)` wants the review and not the gates, so both stages stand down and the review step reviews with no build status to read — and, because there is none, with approval off; `review(o2)` turns the checks stage on and leaves the static one off. A comment that asks for nothing (`prompt:`, or a question) stands them both down too; building for every comment that mentions the bot would mean a Unity build for "why did you flag this?". **A review asked for in prose** is the one case that cannot be routed this way: recognising the request is the classifier's job, and that is a model call inside the review step, so those runs build and analyse *there* — in the step that also holds the model's key. The log says which happened, in both directions:

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

- **The Editor flags the CLI owns cannot be forwarded to `unity run`.** `-batchmode`, `-quit`, `-projectPath` and `-logFile` are added by the CLI and rejected after `--`. `-nographics` is not one of them — `unity run` does not add it, which is why the pipeline forwards it: without it the editor dies with `Error opening default X display` before it compiles anything. `unity test` forwards arguments after `--` as well (measured: `unity test . -- -force-glcore` reaches the editor as `-batchmode -runTests … -testPlatform EditMode -force-glcore`), but the pipeline passes none — a test that needs a graphics device needs a display, not a flag.
- **`unity run -runTests` produces no report.** The CLI always passes `-quit`, and the editor quits before the test run has written anything — which reads as "no tests, no failures" and is exactly the silent pass this pipeline avoids elsewhere. `unity test` exists for this and writes the NUnit report itself; a failing run exits non-zero *and* leaves the report, and the failures are read from it.

The CLI must be executable by the user the runner runs as, and so must the editor that the CLI resolves (a Hub under `/root` is not visible to a runner running as anyone else). Where the CLI itself lives is found rather than configured — see [Nothing asks where a tool is](#nothing-asks-where-a-tool-is).

`XDG_RUNTIME_DIR` is corrected once, in `main.py`'s `prepare_environment`, before any stage runs: a CI service account has no login session, so it is either unset or inherited from whoever started the runner — another user's directory, mode `0700`. **Two separate things break on it and both look like something else:**

- The Unity CLI's auth broker cannot create its socket and refuses to serve, which surfaces much later as a **licence failure**.
- ReSharper's Roslyn host cannot read its own working files — the run's log says `lstat("/run/user/0/.dotnet") == EACCES` — and **stops loading analyzers and source generators**. Every member a generator would have referenced is then reported as *never used*: a wrong comment on a pull request, caused by an environment variable.

It is done in Python rather than in the action's shell because every stage needs it, including the review step, which runs the other two stages' work itself when a review was asked for in a comment. One place that every process goes through is the only version that stays true.

### Scoped registries

Every per-PR Unity project is pointed at the organization's package feeds, so a package under review can resolve dependencies (UniTask, Nifty, NuGet-for-Unity, …) that are not in the Unity registry — without them the build fails on a package Unity simply cannot find:

| Name | URL | Scopes |
| --- | --- | --- |
| `Peropero` | `https://unitypkg.peropero.net` | `com.prpr` |
| `OpenUPM` | `https://package.openupm.com` | `com.niftyhat`, `com.cysharp`, `org.nuget.castle`, `org.nuget.system`, `org.nuget.google`, `org.nuget.microsoft`, `org.nuget.zlinq`, `com.neuecc`, `org.nuget.moq` |

The list is `SCOPED_REGISTRIES` in `unity_runner.py`. It is written into the project's `Packages/manifest.json` and re-applied on every run, including the reuse path, so a project created before a registry or a scope was added is brought up to date instead of staying stale.

**The scopes are merged; the URL is not.** A registry of the same name keeps every scope it already had and gains the ones it is missing — a mirror, or an extra scope somebody added, survives. The URL is the configured one, which is what lets a feed that moves reach the projects that already exist rather than only the ones created afterwards; a repoint is logged, because it changes where a project resolves packages from.

### Running the package's own tests

**Both platforms run.** Every review runs the EditMode suite and the PlayMode suite. A package with no PlayMode tests produces no PlayMode cases, which costs seconds and needs no decision; a package whose tests are mostly PlayMode gets them run instead of being reported "tested" without them. Which platform a test runs in is Unity's decision — the assembly it lives in — so the pipeline does not try to predict it, and there is no setting for it.

The package under review is also registered in the project's `testables` (next to its `file:` dependency), which is what makes Unity compile its test assemblies and run them. A package that is only a dependency has its tests **ignored, not failed** — the test run reports nothing at all, so a package with broken tests would look like a clean pass. Like the registries, the entry is written idempotently and re-applied on every run, so a project created before this existed is fixed rather than left silently untested.

The project's `com.unity.test-framework` is raised to **1.4.6** if it is missing or older — not 1.3.4, which hangs on a `[Repeat]` over an `async Task` test (measured: 1.3.4 hangs with `NotImplementedException: Use ExecuteEnumerable`, 1.4.6 runs the same test in 48s). Both need Unity 2019.4 or newer, so the raise cannot strand an older project. The 3D template pulls an older one in through `com.unity.feature.development`, and a test assembly written against the newer TestRunner API does not compile — or run — against it.

`org.nuget.moq` is provided the same way, at 4.21.0, for the same kind of reason and a different cause: a package's test assemblies reference `Moq.dll` — declared in the package's own asmdef under `precompiledReferences` — and the per-PR project starts from the 3D template's manifest, which has never heard of it, so the reference does not resolve and the test assembly does not compile. It comes from OpenUPM, which is why `org.nuget.moq` is in that registry's scopes.

Both follow one rule, in `ensure_minimum_version`: absent → added at the minimum, older → raised, at or above → untouched, and a `file:` or git reference → untouched, because that is the repository's deliberate choice.

**A package that resolves Addressables gets settings, and a play mode script its tests accept.** UIQueen's PlayMode fixtures store their test assets through `com.prpr.resources`, whose adapter asserts `There is no Addressables Settings in project, please create it!` — and a project laid out from the 3D template has none, so every fixture aborted in `IPrebuildSetup` and the whole PlayMode run wrote no report at all. The same fixtures then assert `ActivePlayModeDataBuilderIndex != 0`, because "Use Asset Database (fastest)" bypasses the Addressables runtime, so a project in the default mode is a project they refuse to run in. Both are fixed the same way: the pipeline writes `Assets/Editor/AiReviewProvision.cs`, runs `-executeMethod AiReviewProvision.EnsureAddressableSettings`, and the editor creates the settings and their default groups (`AddressableAssetSettingsDefaultObject.GetSettings(true)`) and switches the play mode script to "Simulate Groups" when it is the fastest one — what a developer's own project already has, not a change to the package under review.

The index is stored in a binary config in `Library`, which this side cannot read, so the method writes `Library/ai-review-provisioned.txt` with what it set. A project whose stamp says a real index is left alone: one launch, once per project, and it goes away with `Library` — exactly when the project needs provisioning again. A project that does not resolve Addressables is not touched, and one that stops resolving it has the script deleted, because a reference to a package that is gone is a compile error in every later run. It never fails the review: if the settings cannot be created, the tests run exactly as they did before.

One consequence of compiling the tests at all: a package whose tests do not compile gets **no project files generated for it**, so ReSharper cannot inspect that package in that run. The compile errors themselves are still posted on the changed lines, so the pull request is told what is wrong — but the static analysis is blind until they are fixed.

### Tests that need a graphics device

Unity creates a real graphics device in batch mode; only `-nographics` takes it away, and `unity test` does not pass it. So a test that builds a UI Toolkit panel — a `UIDocument`, an editor window, anything with a `PanelSettings` — runs on CI exactly as it does locally, **provided the machine has a display to give Unity**. A Linux runner usually does not, and the failure arrives as one line among the test output:

```
[Error] No graphic device is available to initialize the view.
SetUp : Unhandled log message: '[Error] No graphic device is available to initialize the view.'
```

Unity Test Framework fails a test on an *unexpected* error log, so a package whose Editor tests touch UI reports a failure with nothing to do with the pull request. That happened on UIQueen #2: every EditMode run failed on it, and the same machine passed **23 of 23** once a display existed — no `-force-glcore`, no other flag, on 2022.3 with llvmpipe.

**A test that needs a rendered frame cannot run in batch mode — it hangs.** Batch mode never reaches the end of a frame, so `yield return new WaitForEndOfFrame()` inside a `[UnityTest]` never resumes and the run sits there until its deadline. Measured on 2022.3 with a two-line project, all three from the same run: `yield return null` passed in seconds; the same test with `WaitForEndOfFrame` produced **no report** and was killed at its 120-second timeout; replacing the wait and calling `ScreenCapture.CaptureScreenshotAsTexture()` failed at once with `failed to generate texture! Was method called before the 'end of frame' state was reached?` — the same missing frame, said out loud. UIQueen's `MaskableRenderersTests` is that shape, and it is what spent the 30 minutes of a PlayMode deadline: the suite is otherwise 15–30 seconds.

**So PlayMode runs in an editor with a window.** `unity test` always passes `-batchmode` and cannot be talked out of it, so the platform is driven through the editor binary directly — resolved from the CLI's own list (`unity editors --json`) for the version in the project's `ProjectVersion.txt`, so the two cannot drift. The same three tests then pass in 17 seconds, `WaitForEndOfFrame` and the screen capture included, on a virtual display. EditMode keeps the batch route: it needs no frame and it is the cheaper one. A windowed run that stops early without a report — no display, no window, a broken GL stack — is retried in batch mode, which is what the pipeline did before windows existed, so the change cannot take a platform away from a runner that cannot open one.

A pixel test still has to make sense of what it captured: a **player** build is the other way to get real frames, and `Application.isBatchMode` is still the guard to write if the suite has to survive both.

The fix belongs to the runner: the pipeline can hand the editor a display that is already running, but it cannot supply one.

- **Mesa's driver, not just its loader.** `libgl1-mesa-dri` (with `libglx-mesa0`) is what provides `swrast_dri.so`; `libgl1-mesa-glx` on a current distribution is only a transitional package. Without a driver no device can be created even with a display. On a machine whose GPU driver exists but refuses to work, `LIBGL_ALWAYS_SOFTWARE=1` forces llvmpipe.
- **A display that is actually running.** Installing Xvfb does nothing by itself: `Xvfb :99 -screen 0 1920x1080x24 +extension GLX` has to be running — as a systemd unit, since a background job started by hand dies with the step. `DISPLAY` does **not** have to be wired through the workflow: the test step looks for a running X server's socket in `/tmp/.X11-unix` and hands the editor the lowest display it finds, saying so in the log (`Unity: the tests run on the display :99 that is already running.`). A `DISPLAY` that is already set is never overridden — that is the operator's decision, and a guess that disagrees with it is worse than none.
- **A way to see which of the two is missing.** `glxinfo -B` from `mesa-utils` answers it: `OpenGL renderer string: llvmpipe (…)` means the device works, `unable to open display` means Xvfb or `DISPLAY`, and a GLX error with no renderer means the driver.

### A test run that produced no report

*Did the tests pass* and *did the tests run* are two questions, and only the first one was being asked. A run that crashes, hangs until its timeout or dies inside the editor leaves **no report at all**: nothing failed, so nothing turned red, and the step signed off as *compiled and tested* about a suite that never executed. Inside Unity that is a real failure mode, not a hypothetical — a ResourcesManager run spent half an hour in a Mono debugger dump, exited 6, wrote nothing, and was reported as tested.

So each build step records three facts instead of two:

| Fact | Means | Effect |
| --- | --- | --- |
| `tests_ok` | no failing case was read out of the report | blocks approval |
| `tests_reported` | a report was actually written | changes what the step *says*, nothing else |
| `tests_broke` | the run exited non-zero having written nothing | the pull request is told; approval is not blocked |

A run that produced no report does **not** fail the build. A hung processor, a missing licence or a runner without the editor is not evidence that the author's code is wrong, and failing on it would block every pull request for a reason that is not about the change. It is, however, exactly the state whose *reason* nobody can reconstruct afterwards, so the run keeps three things about itself:

- the last **40 lines it printed**, which go into the status comment in a collapsed `<details>` block — an editor that hung said everything it was going to say in its final moments, and that is the diagnosis;
- the **whole captured output**, written to `.ai-review/tests-<platform>.log` beside the PR's other state, for whoever can read the runner;
- both paths in the job log, next to the line that says no report was produced.

`UNITY_TEST_TIMEOUT` and the tail together answer the two halves of "why": how long it was given, and what it said instead. It is not evidence of a passing suite either, so it is not called one: the status line becomes `⚠️ Unity: 编译通过；单元测试没有产出报告，本次未真正运行。` (and the same for `.NET`), which is also what the review model is shown — a reviewer approving under a ⚠️ does so knowingly, which is not true of one who was told the package was tested.

When the run actually died, the exit code says so, and the status comment is posted to the pull request even though the step passed: the only other place that fact appears is the job log, which the author never reads. A deadline and an exit code are different facts, so the sentence keeps them apart — `⚠️ .NET: 编译通过；.NET 测试运行失败（dotnet test 退出码 3），没有产出报告。` and `⚠️ .NET: 编译通过；.NET 测试超时（30 分钟还没跑完，被停掉了），没有产出报告。` — because "测试没有跑完" does not say whether the run is still going, was stopped at a deadline, or exited on its own, and those call for different next steps. The clean-exit case says `（dotnet test 退出码 0）` too, for the same reason.

**The editor log is read, not only uploaded.** A run that dies before writing its NUnit file leaves one line of output — `Unity exited with code 3 before reporting results` — and a 300 KB editor log, and the reason is in the log: the same exception, thrown once per fixture while the runner was setting each of them up. `build_log.parse_editor_diagnosis` groups the exceptions by message, counts them, keeps the outermost frame that is not engine plumbing (the fixture, not `Assert.Fail`) and quotes the runner's own verdict. UIQueen PR #3 is the case that made it worth writing: 23 exceptions in 2 kinds,

```
**PlayMode 编辑器日志里的异常（23 次、2 类）**：
- `AssertionException: There is no Addressables Settings in project, please create it!` ×16 — `MDSampleInit.Init`
- `NullReferenceException: Object reference not set to an instance of an object` ×7 — `DefaultPanelInserterTests.IPrebuildSetup.Setup`

PlayMode 测试结果：`Test run completed. Exiting with code 3 (RunError). Multiple unexpected errors happened while running tests.`
```

The count is what makes it diagnosable rather than merely loud: sixteen of one assertion means every fixture that needs Addressables fails, not that one test is flaky. It goes into `summary()`, so the pull request comment, the job log and the review prompt all see it — the model approving a change is told why the suite did not run.

**A run that printed nothing is bisected down to the test method.** Unity Test Framework writes its report at the end of the platform's run and says nothing per test, so the output of a hung suite cannot name the test — but running *less* of the suite can. The candidates are the test **methods** read out of the package's sources (namespace, class and method; a flat list, no namespace walk and no class-level unit — the answer is one method), and each round runs half of them with a `--filter` built from their full names. A report means that half finished and the hang is in the other half; no report means it is in this one. What is left is a single method, run on its own:

```
Unity: 129 test method(s) to search for the PlayMode hang.
Unity: blame round 1: 64 of 129 candidate(s) ...
Unity: blame round 6: 1 of 2 candidate(s) ...
Unity: the PlayMode run hangs in PeroTools2.UIQueen.Tests.UGUIExtensions.MaskableRenderersTests.ObjectInMaskTest — it produced no report within 10s on its own.
```

The name goes into the status comment (`**测试卡在**：…`) and into the summary line, so the pull request says which test, not just that something did not finish. The limits are in `unity_runner.py`: `BLAME_CASE_SECONDS` (10) for the single case, one second per candidate for a group plus `BLAME_SETUP_SECONDS` for the editor start, and `BLAME_MAX_SECONDS` (900) for the search as a whole — it runs only after a run that already burned its deadline, and it must not become a second one.

Three details are what keep the answer honest. **A report with no cases in it is not a run that finished** — it is a filter that matched nothing, which means the names and the runner disagree; the search stops there rather than following an empty file to a conclusion. **The method is the unit, and the filter matches its name with any class before it.** Two things were hidden from the search by naming classes too strictly: a test declared `async Task` (the pattern only knew `IEnumerator` and `void`), and a test declared `virtual` in an abstract fixture, which the runner reports under each concrete subclass — PeroLog's `StdIoTests` has both, and every probe passed while the suite hung. The pattern is now `(?:.*\.)?<method>(\(.*\))?`, so a test is selected by the name it is actually reported under.

**The class a method belongs to is tracked by braces**, not by the last `class` line seen: `UrlUploadTests` declares a nested `UploadCases`, and every test after it used to be reported under the nested name — a name that exists nowhere, which is exactly how a wrong answer got into a comment. And **no single method is forced to be the answer**: when every method finishes alone but the suite hangs, the smallest group that reproduced it is reported instead (`**测试卡住，但没有单个用例能复现**：最小的组合是 `A + B``), found by dropping members from the last hanging group while it still hangs without them.

Two things it cannot do. The filter is a regular expression over the full test name, so the pattern allows the suffixes the report adds and the sources do not (a generic fixture's `<RectMask2D>`, a `[TestCase]` argument list). And a hang that needs the *whole* suite — not a group small enough to reproduce — is reported as where the search stopped, with the log saying so.

`UNITY_TEST_TIMEOUT` is the same problem seen from the other side. One hung suite spent thirty minutes of a job before the CLI's own timeout ended it, and the only deadline that could be moved was the build's. A test run with a deadline of its own can be cut short without shortening the build, which is the difference between a lever and a re-run. It defaults to **ten minutes**, not the build's thirty: no suite seen here runs longer than a minute, so a test run still going after ten is stuck, and the remaining twenty buy nothing but a longer wait for the answer.

### Where the reports go

The reports live in the pull request's own directory under the system temp directory, which nobody can open after the job. So each stage copies them into the checkout — `ai-review-artifacts/`, at the top of the workspace — and the workflow uploads that as `ai-review-reports-<run id>-<attempt>` for fourteen days. What arrives is the NUnit XML per platform, the captured output of any run that wrote no report, the editor log, ReSharper's report and the stage's `checks-*.json`; the session log, the lock file and the package clone stay where they are.

**The comment gets the artifact's own download URL, not the run's page.** The checks stage writes the comment before anything is uploaded, so the line it can write is the run's artifact *page*; the step after the upload reads `steps.upload-reports.outputs.artifact-url`, and `main.py artifact-link` edits that one comment in place. Two details keep it harmless: only comments that name *this* run's page are touched, so an earlier run's link never moves, and a refused edit is a warning, because the comment already points somewhere useful. A run that uploaded nothing — the reports were never written — leaves the page link alone rather than replacing it with an empty string.

**Every comment that reports a build ends with that line**, because two did not and both were the ones that mattered: the status comment written by the checks stage (which now gets the page URL first and the artifact's URL after the edit) and the **rebuild comment** — the only comment a `@perotoolsbot rebuild` run posts. The rebuild comment is written by the review step, which runs *after* the upload, so `REVIEW_ARTIFACT_URL` is already in its environment and the link it prints is the artifact itself.

**A `rebuild` run posts one comment, not two.** `@perotoolsbot rebuild` runs the checks stage and then answers from the review step, and both used to report the same results: the status comment, then the reply saying the same thing a second time. Now the checks stage recognises the command (`_comment_invocation`, no model call), sees that its reply is the report, and stays quiet — one comment, the one that answers the person who asked. Every other run still gets the status comment, because for those the reply is a review, not a build report.

The directory is **not dot-prefixed**, and that is load-bearing rather than tidy. `upload-artifact` leaves hidden files out unless `include-hidden-files` is true, so a `.ai-review-artifacts` directory is searched, found empty and reported as *No files were found with the provided path* — while the stage's own log says `Copied 8 report file(s)`, in the same twenty-five seconds. It took three runs and two wrong fixes (the path, then the timing) to read those two lines together.

### What a build and a test run print

Every build and every test run says how long it took, on either outcome — `Unity: compiled in 2m 14s.`, `Unity: EditMode tests: 3 failing case(s) in 1m 02s.`, `dotnet test produced no report after 30m 00s (exit 6)`. A step that passed in four seconds and one that hung for thirty minutes are both facts about the pull request; only the second is worth acting on, and neither is visible without a number.

The durations are the run's own, not the step's. The compile is timed around every generation attempt — a method that writes nothing costs a full editor launch, and that attempt is part of what "the build took" means — and each test platform is timed separately, so a suite that is getting slower shows up before it becomes a timeout.

The log is also **live while the step runs**, not only at the end. A tool's own output is echoed as it arrives, and every quiet minute produces a heartbeat — once a minute at most, however often the loop wakes to watch for a crash — naming the elapsed time and the last thing either the tool or the file it writes to said:

```
Unity: generating project files via UnityEditor.SyncVS.SyncSolution ...
Unity PlayMode tests: still running for 12m 00s of its 30m 00s deadline, no output at all since it started.
```

That line is the difference between a slow build and a hung job, which from the outside are the same silence: the twenty-minute compile this pipeline used to produce printed nothing at all until it finished. The editor reports its progress to a log file rather than to the CLI's stdout, so `unity run` hands that file to the deadline as `watch` and the heartbeat reads its last line — see `subproc.run`. The run names itself (`Unity PlayMode tests`, not `unity`), because the same executable runs twice in a row and the interesting question is which of the two has been silent. A run that has never printed anything says so — **no output at all since it started** — rather than repeating the elapsed time as "quiet for", which is the same number twice and hides the fact worth noticing. `HEARTBEAT_SECONDS` (60) is in that module rather than in the configuration: how often a progress line is worth printing is not something a caller should have to decide.

**What a heartbeat cannot say is which test hung.** Unity Test Framework writes its report at the end of the platform's run and prints nothing per test, so a suite that hangs produces thirty minutes of silence from a harness that is working exactly as designed. When a timed-out run printed nothing, the log says so and names the way to find out — `unity test . --mode PlayMode --filter <fixture>`, or `--shard n/m` — because narrowing it is the only thing that answers the question.

Two limits keep that from becoming its own problem. **The test run is captured but not echoed**: `unity test` forwards the editor's log to its own stdout, which is megabytes over a run that hangs, so it runs with `echo=False, preview=True` — silent, except for the heartbeat quoting its last line every minute. And echoing stops after **`ECHO_LIMIT`** (256 KB) for every command, because GitHub truncates a step's log at a few megabytes and the dump a hang produces is exactly the part that must not push the rest out.

**A native crash is a death announcement too.** The editor prints `Native Crash Reporting` / `Caught fatal signal` — a SIGSEGV in the Mono runtime — and then stops responding; the deadline would otherwise be spent waiting for a process that is already gone. Both phrases are in `CRASH_MARKERS`, so the run ends at once.

One thing that produces exactly that, and is worth naming because it looks like a hang: **NUnit's `[Repeat]` on a Unity test is not supported.** The command it wraps calls `Execute`, which the Unity Test Runner only implements as `ExecuteEnumerable`, so it throws `NotImplementedException: Use ExecuteEnumerable` — and on 2022.3 + UTF 1.3.4 that exception took the editor down with a SIGSEGV (measured on PeroLog #8). The pipeline says so in the log when it sees that line; the repair is in the test: a `[Repeat(100)]` becomes a loop inside the test body.

A run that announces its own death is ended there and then. The editor prints `Exiting early due to double fault` — a Mono crash — and then does not exit, so `unity test` waits out its whole deadline on a test host that is already gone: ResourcesManager #10 spent thirty minutes per review on exactly that. `CRASH_MARKERS` in `unity_runner.py` are handed to the deadline as `fatal`, and a line containing one ends the process tree at once; the run then reports as one that produced nothing, which is what it did.

One command is deliberately **not** echoed: `git`. Its remote URL carries the App token and git quotes the URL it could not reach, so that output is captured and never printed, and the part of it that does reach the log — the tail quoted when a fetch or clone fails — has the token replaced first.

A failure prints an error report, not just a count:

| What failed | What the log shows |
| --- | --- |
| compile | one line per error, `path:line: CODE: message` — the same shape the pull request comment uses — capped at twenty with `... and N more` |
| tests | one line per failing case: the name and the first line of its message, then the path of the report file that holds the rest |
| nothing parseable | a single tail of what the tool said, which is the only witness there is when the editor crashed or the timeout ended the run |

The cap is a report, not a census: the pull request comment carries the list the author needs, and a thousand copies of one error in a log help no one. The *reason* a run produced no report at all is a separate case and gets its own treatment — see [A test run that produced no report](#a-test-run-that-produced-no-report), where the last forty lines go to the pull request and the whole output to a file on the runner. The last row is the one that matters most — a run killed at its deadline writes no report, so whatever it managed to print before the kill is the entire diagnosis, and it is the reason that tail is captured rather than assumed lost.

### The generated solution is repaired before use

Unity writes one solution entry per generated project, and it generates both `<Name>.csproj` and `<Name>.Player.csproj` for the same assembly — labelling both with the same display name. MSBuild rejects such a solution outright (`MSB5004: The solution file has two projects named "Unity.Timeline"`), which stops `jb inspectcode` before it produces any report at all, leaving ReSharper silently doing nothing. The duplicate entries are renamed after their project files, which costs nothing and makes the solution usable.

The repair is applied twice on purpose: once right after generation, and again after the test run — **every Editor launch rewrites the solution**, so the test run brings the duplicates back. The second pass is the last thing that happens before the solution is handed to ReSharper, and nothing after it starts Unity again.

The old project files are deleted before regenerating, for the same reason in reverse. Generation stops as soon as a solution exists — that is how a repository whose project-file method does nothing is caught — but a solution **left over from the previous run** satisfies that check on its own, so the first method was never asked to prove itself, the files were never rewritten, and the analysis ran against a model of a project that no longer matched the code: files this push added were not in it at all, and ReSharper sees no findings in a file it does not know about. Clearing `*.sln` and `*.csproj` from the project root before the first attempt is what makes the question real again. Nothing else is touched — `Library/`, `Temp/`, the manifest and the package reference all stay, so the regeneration is still incremental.

**"A solution exists" means one Unity wrote, and the search for it does not enter `.ai-review`.** The clone lives in there, and a repository that ships its own solution therefore used to have that solution mistaken for Unity's output: the search succeeded, the next project-generation method was never tried, no project files were generated at all, and the static analysis was pointed at the whole solution instead of at the package's own projects — 2804 findings where the package's would have been a handful. Nothing is lost by skipping it: a repository's own solution is already a target in its own right, from the classification.

Solution *folders* are not projects, either. Two folders may legally share a name — `Core` under `Editor` and under `Extensibility` — and counting them as projects made a solution look like it had collisions; since a folder's "unique" name is its own name, the repair then gave up on a solution it could have fixed, leaving the `MSB5004` duplicates in place and ReSharper with no report at all.

### How inspectcode is invoked

Three things used to stop `jb inspectcode` from writing any report at all, and all three look exactly like "no findings" from the outside. None is visible unless you know to look.

**It is found the way the Unity CLI is.** `jb` is a .NET tool installed per user, so it lands in `~/.dotnet/tools` — a directory that is on an interactive `PATH` and on no service account's. A runner that has `jb` and can run it by hand reported "not found on `PATH`" and silently analysed nothing. It is now resolved once per run across `PATH`, `~/.dotnet/tools`, `~/.local/bin` and `/usr/local/bin` and printed once as a fact — see [Nothing asks where a tool is](#nothing-asks-where-a-tool-is).

### The analyser and the IDE disagree

A naming rule can exist in the ReSharper engine that `jb inspectcode` runs and not in the ReSharper that the team's IDE ships — the two are separate builds of the same product, and a patch release can add a rule. The Unity plugin is the case that prompted this: a 2026.2 build adds **Unity serialized field**, which asks for `mHp` where the project has decided on `m_Hp`, and the team's Rider has no such rule to change, because its engine is older.

That is a finding nobody can act on: it cannot be reproduced, silenced or argued with where the code is written. `resharper-ignore-rules` is how a repository says so, by name:

```yaml
with:
  resharper-ignore-rules: 'Unity serialized field'
```

Only naming rules are affected, only the ones named, and the job log says how many findings the list dropped — a number in the log is what keeps this a decision rather than the analysis quietly doing less. The alternative is to keep the two engines in step, which is worth doing anyway: the run log names the ReSharper version it used.

The useful rule of thumb: **silence a rule by name only when the tool that disagrees cannot be changed.** A rule the team's IDE can configure belongs in `.editorconfig`, where both engines read it.

**A repository's own ReSharper settings are used.** `jb inspectcode` reads `<solution>.DotSettings` on its own, but the solution it inspects is not always the repository's: for a Unity package it is the project Unity generates in the PR's working directory, which is nowhere near the package. Any `*.DotSettings` in the clone is therefore passed with `--settings`, so a rule the team edited in their IDE applies to the analysis as well. That is the fix for a naming convention the analyser's own preset disagrees with, when the preset is configurable at all — the built-in Unity naming rules are not, and no `.editorconfig` property reaches them.
**It is told not to build.** inspectcode builds the solution before inspecting it, and Unity's generated projects are written for Unity's own compiler settings — a generic MSBuild run trips over them (obsolete-API warnings promoted to errors, output paths it cannot open), and a failed build means no report. The pipeline has already compiled the code anyway: Unity for a package, the .NET SDK for a C# project. With `--no-build`, inspectcode still evaluates MSBuild for the project model and the file set; an A/B run over the same solution produced **byte-identical findings** with and without the build, so nothing is lost. Set `resharper-build` / `INSPECT_BUILD` to put the build back if a solution's real sources only appear after one. A build is also the only thing that would give a *project* target the references it cannot resolve — which is why the target is the solution, see [What ReSharper is pointed at](#what-resharper-is-pointed-at).

**Its MSBuild is pinned.** inspectcode picks the **newest** .NET SDK it can find, so a half-installed preview wins and the build fails (`MSB4236`, `NETSDK1045`). `resharper-dotnet-sdk` / `INSPECT_DOTNET_SDK` passes `--dotnetcoresdk=<version>` instead. The pinned SDK must be able to build what the repository targets — an SDK cannot target a newer framework than it ships, so pinning `10.0.x` against a `net11.0` project just moves the error. The log prints this hint whenever a missing report shows SDK-resolution symptoms.

Warnings-as-errors is switched off in both modes, so that turning the build back on does not immediately reintroduce the first failure.

### What ReSharper is pointed at

A UPM package is inspected **through Unity's own solution, filtered to the package's own projects**. Unity writes one `.csproj` per assembly into the project root, and a package's asmdefs get their own; those are what the analysis should be about, and `--project=<name>` is what keeps the report to them. Everything else in the solution is loaded but not reported on, so the analysis is still about the reviewed code and nothing else — a handful of findings where the whole solution yields forty-eight thousand, nearly all of them in Unity's own packages — while every reference from one of the package's assemblies to another still resolves.

That filter is not a convenience, it is the fix for a class of false finding, and which class depends on how Unity names the package's *other* assemblies in the generated project. There are two ways, and only one of them survives a lone target:

- **`<Reference>` with a `HintPath` into `Library\ScriptAssemblies\`** — the DLL Unity wrote when it compiled the assembly. A lone csproj resolves this whenever that file exists, and it does, because the step that runs the tests compiled the package. Measured: with the DLL in place, the project alone reports the same findings as the solution; with the DLL deleted, neither resolves.
- **`<ProjectReference>`** — resolved from the referenced project's **build output**, and Unity never writes into those paths: it compiles with its own pipeline, so the output paths in the generated projects stay empty. With `--no-build` there is nothing to resolve against, every type from another assembly of the package goes missing — and a `protected override` whose base type is missing reads as a *new* protected member, which is CS0628, "declaring new protected method … in a sealed class", on every override in the class. Measured on a two-project reproduction of exactly that shape:

| pointed at | built first? | CS0628 |
| --- | --- | --- |
| `Tests.csproj` alone | no | **reported** |
| `Tests.csproj` alone | yes | not reported |
| the solution containing both projects | no | not reported |

So the warning was about the analysis, not the code, and no `.editorconfig` could reach it. Pointed at the solution, the referenced project is loaded as source and the reference resolves whether or not anything was built; `--project` is what keeps the findings on the package. This also holds for the first shape (a solution loads the project that the DLL belongs to), so the solution target is right for both — which is why it is the target. The log says which projects were selected:

```
ReSharper: Demo.slnx is inspected for Demo, Demo.Tests only; the rest of the solution is loaded so their references resolve.
```

A project target is still used in the two cases where the solution cannot be: there is no solution at all, or the one there is produced no report (a Unity run can leave it in a state MSBuild refuses). The analysis then runs over the package by itself — the partial kind described above, where a type from another of the package's assemblies is missing, and the only place that says so is the log. Something is better than the nothing the step used to give in that case, and the log makes the difference visible.

A filter naming a project the solution does not have would make inspectcode inspect nothing and write no report at all — which is indistinguishable from a clean pass. That is detected (no report, exit 3) and the whole solution is inspected instead, with a line saying so; a filter that matches *some* of its names is fine, and inspectcode reports the projects it did find.

Three lines in the log say what was covered, and they only mean something together:

```
Package assemblies: Demo, Tests
Generated projects for the package: Demo.csproj, Tests.csproj
Other generated projects, not the package's: Assembly-CSharp.csproj
```

The first is what the package's asmdefs say it is, the second what Unity generated for it, and the third what else exists — because an assembly in the first line with no counterpart in the second is a package that is only *partly* inspected, and a partial inspection reports no findings, exactly like a clean one. Unity names a generated project after its asmdef, so the comparison is a name match and a platform-limited or constraint-gated asmdef may legitimately have no project of its own.

For a repository that ships its own solution, that solution stays a target as well — see [Review pipeline](#review-pipeline).

### When "is never used" is wrong

ReSharper's "is never used" family — `UnusedMember.*`, `UnusedType.*`, `UnusedField.*` — **is** posted, and it was wrong exactly once, in a way worth keeping written down. On a real pull request:

```
⚠️ **ReSharper**: Method 'ImportDefinitionAsync' is never used
```

on a method marked `[RelayCommand]`, used by the command the CommunityToolkit generator emits. It is not that ReSharper cannot see generated code — it can, and `--no-build` does not stop it; a minimal `[RelayCommand]` project reports the method as used either way. The cause was `XDG_RUNTIME_DIR`: the runner's service process had inherited root's runtime directory, ReSharper's Roslyn host could not read its own working files (`lstat("/run/user/0/.dotnet") == EACCES`), and it stopped loading analyzers and source generators. No generator, no `ImportDefinitionCommand`, so the method that generates it looked unused. Reproduced on the runner with `grep -c ImportDefinitionAsync` = 1, and gone once the variable was corrected.

So this family is trustworthy **as long as the environment is**, and the environment is the first thing to suspect if one of these is ever wrong again — that one variable has now caused two failures that each looked like something else entirely. What else can make it right in the IDE and wrong here is what no batch analysis can see: reflection, dependency injection by convention, serialization, XAML bindings. A wrong one is worth investigating rather than assuming.

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

### What language the tools speak

Two of the three tools can be translated, and it is worth knowing which parts of the pipeline depend on the language they answer in.

**`jb inspectcode` cannot be, in this package.** The global tool ships resource folders for thirteen languages, and every one of them contains only Microsoft's satellite assemblies — there is not a single `JetBrains.*.resources.dll` in any of them. Its inspection messages, including the sentence the naming suggestion is read from, are English whatever the runner's locale says. Exactly one feature leans on that, and it is guarded by the one part that cannot be translated: the sentence is only read when the finding's `TypeId` is `InconsistentNaming`. If JetBrains ever does ship a translation, the match simply stops and the finding keeps the plain comment it would have had anyway — the failure is a missing button, never a wrong edit.

**`dotnet build` can be, and follows the runner's locale** (`DOTNET_CLI_UI_LANGUAGE`, or `LANG` on Linux). It makes no difference to what is parsed, because what the compile-error parser reads is `path(line,col): error CS0029` — MSBuild translates the sentence after the code and leaves the code and the severity word alone. Measured against `en`, `zh-CN` and `ja` output: the same file, line and code come out of all three, with the message in whatever language the toolchain chose. Subprocess output is decoded as UTF-8, so a translated message arrives intact rather than mangled.

Nothing forces a language. A Chinese-speaking team seeing its own compiler's Chinese message on its pull request is the outcome working as intended; what would be lost is a translation of it, and the pipeline's own lines stay English regardless — `review-language` governs what the bot writes *on the pull request*, not what the tools say in the log.

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
- **A finding already raised is not raised again.** Before posting, the PR's inline comments are read, and a finding whose identical comment (same path, same text — the bodies are deterministic) is already there is skipped, whatever the thread's state. A resolved finding still in the code is the one the author was told to ignore: re-posting it on every later push leaves a comment they cannot silence short of changing code that does not need changing. The thread is where it belongs — reopen it if it comes back. If the comments cannot be read, nothing is suppressed — a repeated comment is a smaller failure than a dropped one.

Every finding is anchored by the changed line's text rather than a line number, so it can only land on a line that is actually in the diff. The line number from the report goes with it as a hint, because the text alone is ambiguous whenever the same statement appears twice in one hunk — a class copied below another, a moved block — and without the hint the anchor takes the *first* occurrence: two findings collapse onto one line, and neither is where the report said. Findings that cannot be anchored are dropped rather than posted somewhere approximate.

If solutions were available but `inspectcode` produced no report for any of them — a broken toolchain, a solution it cannot build — the PR gets **one** note saying the static analysis did not run, rather than silence that looks like a clean pass. It is posted once per PR, not once per push. A repository with no solution at all says nothing: there was nothing to analyse.

### There is no summary

Every finding is a `post_inline_comment` call. There is deliberately **no overall summary and no review body** — the bot only ever speaks through inline comments and the approval.

A finding that is not about a particular line — missing tests, a missing changelog or documentation entry, a design or process concern — is anchored to the closest changed line it relates to rather than dropped. A finding that is never attached to a line is a finding that never reaches the pull request.

Praise is not a finding. A comment that only compliments a change — however technically detailed — is never posted; the approval is the only positive signal, so a clean PR stays silent.

`finish(verdict)` states `approve`, `comment` or `block`; `approve` is what approves the PR. A clean PR therefore produces no comments at all — the approval is the report. The review takes as many steps as it needs: when the transcript outgrows its budget it is compacted, in three passes, so a long investigation neither overflows the model's window nor makes every later step expensive. The step cap is only a runaway guard, and the final step tells the model to finish on time; if it still ends without `finish`, nothing is posted and nothing is approved, and the log says why (`Ignored the review: …`). No labels are applied. If the model answers in prose instead of calling the tools, the run falls back to parsing that text into a review body, which is the only path that posts one (and the only path `SILENT_MODE` still affects).

**A reply that only acts still settles and approves.** A reply run ends with no text in two different situations, and they are not the same thing. "This comment needs no answer" is the model deciding not to speak: nothing happened, and nothing should be decided from it. "I closed the threads and there is nothing left to say" is the model *acting* — the pull request was just emptied of comments by that very run, and the approval that follows a clean review is what the request was asking for. The empty-reply branch used to `return` before the settle/approve step either way, which is how AccessKing PR #3 ended with **38 threads, 0 unresolved, and no approval** (`reviewDecision: REVIEW_REQUIRED`). Now a reply run that resolved threads or posted comments goes on to `settle_threads_and_approve`; one that did nothing still does not, because approving an unreviewed pull request from an unrelated @-mention is the failure the gate exists to prevent.

 **The budget is in tokens, and the ratio is not four characters.** `MAX_AGENT_CONTEXT_TOKENS` is 200k, `estimate_tokens` counts a CJK character as a token and four ASCII bytes as one, and compaction aims at 60% of the budget rather than at the budget itself. All three came from one AccessKing review whose log reads:

```
  Context compacted: 12 old tool result(s) omitted to stay within budget.
    Tokens: 499673 prompt + 3152 completion = 502825 total
  Context compacted: 2 old tool result(s) omitted to stay within budget.
    Tokens: 503340 prompt + 2096 completion = 505436 total
  … "Context compacted" on all 22 steps …
```

The old budget was 400 000 **characters**, sized as "100k tokens at four characters per token" — an English rule. A transcript of code and Chinese is closer to one character per token, so that budget was really a 500k-token request: it sat at the model's ceiling, compaction freed exactly enough for the next step, and every step compacted again. Stubbing tool results is also not enough on its own, because a pull request reviewed a dozen times carries the earlier runs in its session, and that history is not a tool result. So compaction is three passes — stub the older results, drop the oldest turns one at a time (oldest first, keeping the newest request and as much history as fits), then stub what is left — and each pass reports what it did in tokens:

```
Context compacted: 45 tool result(s) stubbed, 93 earlier message(s) dropped, 290k -> 115k tokens.
```

That leaves ~10 further steps before the next compaction instead of one, which is what "compacted" is supposed to mean.

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