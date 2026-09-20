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

The tool reads all configuration from environment variables — no command-line
arguments are required:

```bash
python main.py
```

| Environment variable | Required | Description |
| --- | --- | --- |
| `GITHUB_TOKEN` | yes | GitHub token with `pull-requests: write` on the target repo. |
| `OPENAI_API_KEY` | yes | OpenAI (or compatible) API token. |
| `OPENAI_API_MODEL` | no | Model to use (default `deepseek-v4-flash`). |
| `OPENAI_API_MODEL_FALLBACK` | no | Fallback model used if the primary fails or times out (default `glm-5.3-flash`). |
| `OPENAI_API_BASE_URL` | no | API base URL (default `https://tokenhub.tencentmaas.com/plan/v3`). |
| `OPENAI_TIMEOUT` | no | API request timeout in seconds (default `180`). |
| `OPENAI_MAX_RETRIES` | no | Retry count for timeouts/429/5xx errors (default `5`). |
| `REVIEW_LANGUAGE` | no | Review output language — codes (`en`, `zh`, `cn`, `ja`, `ko`, `es`, `fr`, `de`, `ru`, `pt`) or full names (default `cn`). |
| `MAX_TOKENS_PER_CHUNK` | no | Max tokens of diff per review call (default `131072`). |
| `SILENT_MODE` | no | Post a comment instead of a review. Set to `0`/`false` to post a review with `APPROVE`/`REQUEST_CHANGES` (default: on). |
| `DRY_RUN` | no | Print the review without posting. Set to `1`/`true` to enable (default: off). |
| `REVIEW_STATE_DIR` | no | Directory for local per-PR history files (default `<tmp>/ai-code-review`). |
| `PROMPT_TARGET` | no | `owner/repo/path` for prompt-improvement PRs (default `peroperogames/ToolsWorkflow/review/prompt.md`). |

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

- **PR conversation** (`issue_comment`) — GitHub exposes no thread relationship
  there, so the comment must **@-mention the bot**.
- **Inline review comments** (`pull_request_review_comment`) — replying inside
  one of the bot's own threads is enough; no @-mention needed. A brand-new
  inline comment still has to mention it.

Comments on non-PR issues, bot comments, and comments that address neither the
bot nor one of its threads are ignored. When the trigger came from an inline
thread, the bot replies inside that same thread.

#### Special commands

- **Improve the prompt** — e.g. `@perotoolsbot improve review`. The bot
  classifies the comment intent; if it's a prompt-improvement request it
  generates an updated `prompt.md` and submits it as a PR to `PROMPT_TARGET`.

- **Code changes** — e.g. `@perotoolsbot fix src/foo.py`.
  The bot reads the current file contents, generates code changes, and
  submits a PR to the current repository's feature branch.

- **Review request** — e.g. `@perotoolsbot review this PR for me.`. Runs a full
  review on demand and posts it.

Replying requires the GitHub App to have **`Issues: Read and write`** permission (issue comments use the Issues API, which is separate from `Pull requests`).

## Review pipeline

1. Fetch PR metadata; if the PR is closed, delete any local history and stop.
   Merges from `release/*` back to `master`/`main` are skipped. The PR's **first**
   pass gets the full structured review; later `synchronize` pushes get a light
   incremental pass (short plain summary + inline comments) instead.
2. Load local per-PR history and fetch prior reviews, conversation comments
   **and inline review comments**, merging them into the conversation context.
3. Build the diff payload from the per-file patches — every line is prefixed
   with its absolute line number so the model can quote a line instead of
   computing line numbers itself.
4. If the payload still exceeds `MAX_TOKENS_PER_CHUNK`, review it in chunks and
   then merge the chunk reviews back into a **single** review body.
5. Classify the review (`REQUEST_CHANGES` / `COMMENT` / `APPROVE`) from the
   presence of critical/warning keywords.
6. Post the review (or comment in `SILENT_MODE`). No labels are applied.
7. Resolve and approve are re-checked after **both** a later push and a reply
   in an open thread:
   - On a push, the diff of **that push alone** (`before...after` from the
     event) is what the model judges against.
   - In a thread, a concern answered by discussion counts as settled even when
     no code changed.
   - Once no unresolved thread remains and the latest review was clean, the bot
     submits an `APPROVE` review. Thread resolution uses the GraphQL API — the
     REST API cannot do it.

The review can also carry **inline line comments** (single-line and cross-line via `start_line`). The model emits them as a JSON `comments` block, which the script parses and posts alongside the review body; if GitHub rejects the line numbers, it falls back to a body-only review.

## Files

- `main.py` — entry point and orchestration.
- `action.yml` — composite action definition.
- `github_client.py` — GitHub REST API client.
- `ai_client.py` — OpenAI-compatible chat completions client.
- `history.py` — local per-PR history persistence (temp files).
- `prompt.md` — default review prompt (auto-improveable via natural language).
- `requirements.txt` — Python dependencies.