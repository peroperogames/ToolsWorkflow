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

The GitHub App token is generated in `code-review.yml` via `actions/create-github-app-token` and passed to the composite action as `github-token`. Per-PR session history is stored on the runner (not inside the action), keyed by PR and removed when the PR closes.

## Requirements

- Python 3.8+
- [`requests`](https://pypi.org/project/requests/)

```bash
pip install -r requirements.txt
```

## Usage

The tool reads all configuration from environment variables — no command-line arguments are required:

```bash
python main.py
```

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
| `review-language` | `REVIEW_LANGUAGE` | `cn` | Review output language — codes (`en`, `zh`, `cn`, `ja`, `ko`, `es`, `fr`, `de`, `ru`, `pt`) or full names. |
| `max-tokens-per-chunk` | `MAX_TOKENS_PER_CHUNK` | `131072` | Max tokens of diff per review call. |
| `silent-mode` | `SILENT_MODE` | `true` | Post a comment instead of a review. Set to `0`/`false` to post a review with `APPROVE`/`REQUEST_CHANGES`. Only affects the prose-fallback path — the normal tool-driven review posts inline comments regardless. |
| `dry-run` | `DRY_RUN` | `false` | Print the review without posting anything. Useful for trying the bot out on a pull request. |
| `state-dir` | `REVIEW_STATE_DIR` | `<tmp>/ai-code-review` | Directory for local per-PR history files. |
| `project-prompt-path` | `PROJECT_PROMPT_PATH` | `.github/ai-review.md` | Path, relative to the repository under review, of that repository's own review criteria. Read from the PR head and added to the built-in prompt; empty uses the built-in prompt alone. |

`code-review.yml` also needs the `APP_ID`, `APP_PK` and `OPENAI_API_KEY` secrets; `main.py` additionally reads `GITHUB_REPOSITORY`, `GITHUB_EVENT_NAME` and `GITHUB_EVENT_PATH` (set by Actions) or `GITHUB_PR_NUMBER` for a manual run.

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

Comments on non-PR issues, bot comments, and comments that address neither the bot nor one of its threads are ignored. When the trigger came from an inline thread, the bot replies inside that same thread.

#### Special commands

- **Improve the prompt** — `@perotoolsbot prompt: <what to change>` rewrites review criteria and opens a pull request with the result. Nothing lands without a human merging that PR, and the bot's token needs write access to the target repository (it already has it for ToolsWorkflow). The command picks the target, and the colon is optional in either form (`:` and `：` both work):
  - `@perotoolsbot prompt: ...` and `@perotoolsbot prompt(this): ...` — the reviewed repository's own criteria file (`PROJECT_PROMPT_PATH`, written fresh if it does not exist yet). The PR is opened against that repository, so a project's feedback cannot change how other projects are reviewed.
  - `@perotoolsbot prompt(base): ...` — the shared prompt in ToolsWorkflow, the single reusable source of the review prompt. The PR is opened against ToolsWorkflow.
  - Phrased without the command, anything the intent classifier reads as a prompt change behaves like `prompt(this)`.

- **Code changes** — e.g. `@perotoolsbot fix src/foo.py`. The bot reads the current file contents, generates code changes, and submits a PR to the current repository's feature branch.

- **Review request** — e.g. `@perotoolsbot review this PR for me.`. Runs a full review on demand and posts it.

Replying requires the GitHub App to have **`Issues: Read and write`** permission (issue comments use the Issues API, which is separate from `Pull requests`).

## Review pipeline

1. Fetch PR metadata; if the PR is closed, delete any local history and stop. Merges from `release/*` back to `master`/`main` are skipped. The PR's **first** pass gets the full review; later `synchronize` pushes get a light incremental pass covering only what the new commits introduced. Once a PR is known to need reviewing, the repository's own criteria are fetched from its head and merged into the prompt — see [Project review criteria](#project-review-criteria).
2. Load local per-PR history and fetch prior reviews, conversation comments **and inline review comments**, merging them into the conversation context.
3. Build the diff payload from the per-file patches — every line is prefixed with its absolute line number so the model can quote a line instead of computing line numbers itself.
4. If the payload still exceeds `MAX_TOKENS_PER_CHUNK`, review it in chunks and then merge the chunk reviews back into a **single** review body.
5. **Build & test in a Unity host project.** UPM packages have no compilable project of their own, so the runner keeps one persistent empty Unity project (`UNITY_HOST_PROJECT`). The package under review is pulled in as a `file:` dependency, Unity regenerates the real sln/csproj in batch mode and compiles, then unit tests run. Compile errors land as inline comments on the changed line (or a status comment otherwise); test failures land in that status comment. A failing build or test **blocks approval**. Per PR the package is cloned on first run and `git`-synced on later pushes; the clone and the host dependency are removed when the PR closes. The whole step self-skips when `UNITY_PATH`/`UNITY_HOST_PROJECT` are unset or the repo is not a UPM package.
6. Run **ReSharper** (`jb inspectcode`) over the Unity-generated solution (full UnityEngine references, so no resolve-error noise), honouring the repository's own `.editorconfig`, and post each `WARNING`/`ERROR` on a changed line as its own inline comment prefixed `ReSharper:`. Deterministic, project-specific analysis (naming, style, redundancies, correctness) the model is told **not** to duplicate. For repos that ship their own solution (e.g. a `Projects~/*.sln`), that solution is used directly without a Unity build. Self-skips when the runner has no `jb` or no solution is available.
7. Let the model drive the review through tools (`read_file`, `get_file_diff`, `post_inline_comment`, `list_open_threads`, `resolve_thread`, `finish`); the build/test status is given to it as context.
8. Resolve and approve are re-checked after **both** a later push and a reply in an open thread:
   - On a push, the diff of **that push alone** (`before...after` from the event) is what the model judges against.
   - In a thread, a concern answered by discussion counts as settled even when no code changed.
   - Once no unresolved thread remains and the latest review was clean, the bot submits an `APPROVE` review. Thread resolution uses the GraphQL API — the REST API cannot do it.

### There is no summary

Every finding is a `post_inline_comment` call. There is deliberately **no overall summary and no review body** — the bot only ever speaks through inline comments and the approval.

A finding that is not about a particular line — missing tests, a missing changelog or documentation entry, a design or process concern, a change that was done well — is anchored to the closest changed line it relates to rather than dropped. A finding that is never attached to a line is a finding that never reaches the pull request.

`finish(verdict)` states `approve`, `comment` or `block`; `approve` is what approves the PR. A clean PR therefore produces no comments at all — the approval is the report. No labels are applied. If the model answers in prose instead of calling the tools, the run falls back to parsing that text into a review body, which is the only path that posts one (and the only path `SILENT_MODE` still affects).

## Files

- `main.py` — entry point and orchestration.
- `action.yml` — composite action definition.
- `github_client.py` — GitHub REST API client.
- `ai_client.py` — OpenAI-compatible chat completions client.
- `inspect_code.py` — ReSharper static analysis (`.editorconfig`-driven).
- `unity_runner.py` — Unity host-project build, unit tests and project-file generation.
- `history.py` — local per-PR history persistence (temp files).
- `prompt.md` — default review prompt (auto-improveable via natural language).
- `requirements.txt` — Python dependencies.