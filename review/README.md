# GitHub AI Code Review

An AI-powered GitHub pull request reviewer. It fetches a pull request's diff via
the GitHub REST API, sends it to an OpenAI-compatible chat completions endpoint,
and posts the review back to the pull request (as `APPROVE`,
`REQUEST_CHANGES`, or `COMMENT`).

## Usage (GitHub Action)

Consumers reuse the `code-review.yml` reusable workflow (existing callers keep
working unchanged). Internally it delegates to the `review` composite action, so
there is no repository clone:

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
      openai-model: glm-5.3-flash
      openai-base-url: https://token.peropero.net/v1
      review-language: cn
    secrets:
      OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
      APP_ID: ${{ secrets.APP_ID }}
      APP_PK: ${{ secrets.APP_PK }}
```

The GitHub App token is generated in `code-review.yml` via
`actions/create-github-app-token` and passed to the composite action as
`github-token`. Per-PR session history is stored on the runner (not inside the
action), keyed by PR and removed when the PR closes.

Per-PR session history is stored on the runner (not inside the action), keyed by
PR and removed automatically when the PR closes.

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
| `OPENAI_API_MODEL` | no | Model to use (default `gpt-4o`). |
| `OPENAI_API_BASE_URL` | no | API base URL (default `https://api.openai.com/v1`). |
| `REVIEW_LANGUAGE` | no | Review output language — codes (`en`, `zh`, `cn`, `ja`, `ko`, `es`, `fr`, `de`, `ru`, `pt`) or full names (default `en`). |
| `REVIEW_PROMPT` | no | Review prompt. If empty/unset, `prompt.md` next to the script is used. |
| `MAX_TOKENS_PER_CHUNK` | no | Max tokens per chunk for large PRs (default `6000`). |
| `SILENT_MODE` | no | Set `true`/`1` to post a comment instead of a review. |
| `DRY_RUN` | no | Set `true`/`1` to print the review without posting. |
| `REVIEW_STATE_DIR` | no | Directory for local per-PR history files (default `<tmp>/ai-code-review`). |

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

Triggering the workflow on `issue_comment` makes the bot answer human comments
on the PR instead of performing a full review:

- A human comment on a PR → the bot posts an AI-generated reply.
- Comments on non-PR issues and bot comments are ignored (the latter prevents
  the bot from replying to its own messages in a loop).

Replying requires the GitHub App to have **`Issues: Read and write`** permission
(issue comments use the Issues API, which is separate from `Pull requests`).

## Review pipeline

1. Fetch PR metadata; if the PR is closed, delete any local history and stop.
2. Load local per-PR history and fetch prior reviews/comments, merging them into
   conversation context.
3. Build a diff payload from the per-file patches.
4. Chunk the diff when it exceeds `MAX_TOKENS_PER_CHUNK`, review each chunk
   (passing the full file list and conversation as context), and combine the results.
5. Classify the review (`REQUEST_CHANGES` / `COMMENT` / `APPROVE`) from the
   presence of critical/warning keywords.
6. Post the review (or comment in `SILENT_MODE`) and apply a best-effort label.

## Files

- `main.py` — entry point and orchestration.
- `github_client.py` — GitHub REST API client.
- `ai_client.py` — OpenAI-compatible chat completions client.
- `history.py` — local per-PR history persistence (temp files).
- `prompt.md` — default review prompt.
- `requirements.txt` — Python dependencies.