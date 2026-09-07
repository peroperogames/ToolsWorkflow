# GitHub AI Code Review (Python)

An AI-powered GitHub pull request reviewer. It fetches a pull request's diff via
the GitHub REST API, sends it to an OpenAI-compatible chat completions endpoint,
and posts the review back to the pull request (as `APPROVE`,
`REQUEST_CHANGES`, or `COMMENT`).

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

## Review pipeline

1. Fetch PR metadata and the list of changed files (paginated).
2. Fetch prior reviews and comments on the PR as conversation context (best-effort).
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
- `prompt.md` — default review prompt.
- `requirements.txt` — Python dependencies.