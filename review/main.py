#!/usr/bin/env python3
"""GitHub AI Code Review.

Fetches a pull request from GitHub, sends its diff to an OpenAI-compatible chat
completions API for review, and posts the result back to the pull request as a
review (APPROVE / REQUEST_CHANGES / COMMENT).

The tool is fully configured through environment variables (no CLI arguments):

    GITHUB_TOKEN          (required) GitHub token with pull-requests write access.
    OPENAI_API_KEY        (required) OpenAI-compatible API token.
    OPENAI_API_MODEL      (optional) Model to use (default: gpt-4o).
    OPENAI_API_BASE_URL   (optional) API base URL (default: https://api.openai.com/v1).
    REVIEW_LANGUAGE       (optional) Review output language (default: en).
    REVIEW_PROMPT         (optional) Review prompt; defaults to prompt.md next to this script.
    MAX_TOKENS_PER_CHUNK  (optional) Max tokens per chunk for large PRs (default: 6000).
    SILENT_MODE           (optional) "true"/"1" posts a comment instead of a review.
    DRY_RUN               (optional) "true"/"1" prints the review without posting.

The pull request is resolved from the GitHub Actions environment
(``GITHUB_REPOSITORY`` + ``GITHUB_EVENT_PATH``); for manual runs, set
``GITHUB_REPOSITORY`` and ``GITHUB_PR_NUMBER``.
"""

from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ai_client import AIClient, DEFAULT_BASE_URL, DEFAULT_MODEL
from github_client import GitHubClient

import history

# The prompt file is resolved next to this script so the tool works regardless
# of the caller's current working directory.
DEFAULT_PROMPT_FILE = Path(__file__).resolve().parent / "prompt.md"

# Rough heuristic: ~4 characters per token, used for chunking large PRs.
CHARS_PER_TOKEN = 4
DEFAULT_MAX_TOKENS_PER_CHUNK = 6000

# Conversation transcript limits, to avoid unbounded context growth.
MAX_CONVERSATION_ENTRIES = 50
MAX_CONVERSATION_ENTRY_CHARS = 4000

# Minimal fallback used only when both REVIEW_PROMPT and prompt.md are empty.
FALLBACK_PROMPT = (
    "You are an expert software engineer performing a thorough code review. "
    "Identify bugs, security issues, performance problems, and maintainability "
    "concerns. Be specific (file and line), actionable (show fixes), and "
    "constructive (acknowledge what was done well). Return a structured Markdown review."
)

# Prompt used when answering a developer's reply — short and plain, not a review.
REPLY_SYSTEM_PROMPT = (
    "You are a helpful AI code review assistant. A developer is replying to your "
    "previous review on a pull request. Answer their comment directly and "
    "concisely — a short, plain message, NOT a full structured review. Reference "
    "files or code only when it helps."
)

INTENT_CLASSIFIER_PROMPT = (
    "Classify the intent of this GitHub comment directed at you (a code review bot).\n"
    "Reply with EXACTLY one word:\n"
    "- 'improve_prompt' if the user is asking to improve the review prompt.\n"
    "- 'code_change' if the user is asking you to write code, fix a bug, add a "
    "feature, refactor, or submit a PR with code changes.\n"
    "- 'reply' for anything else (questions, review requests, etc.)."
)

IMPROVE_PROMPT_SYSTEM_PROMPT = (
    "You are an expert at improving AI prompts for code review. "
    "You will be given the current review prompt and user feedback. "
    "Produce an improved version that addresses the feedback while "
    "preserving the core structure and purpose.\n\n"
    "Rules:\n"
    "- Keep the same overall structure (sections, headings).\n"
    "- Address the feedback specifically.\n"
    "- Do NOT remove existing useful content.\n"
    "- Return ONLY the improved prompt in markdown. No explanation, no code fences."
)

CODE_CHANGE_SYSTEM_PROMPT = (
    "You are a skilled software engineer. Given current file contents, "
    "conversation context, and the user's instruction, generate the required "
    "code changes.\n\n"
    "Return a JSON object:\n"
    '{"message": "concise commit message", "files": [{"path": "relative/path", '
    '"content": "complete new file content"}]}\n\n'
    "Rules:\n"
    "- Return the COMPLETE new file content for each file, not a diff.\n"
    "- Only include files that actually change.\n"
    "- Preserve the existing code style, conventions, and imports.\n"
    "- Make minimal, focused changes that address the instruction.\n"
    "- Return ONLY the JSON, no markdown fences, no extra text."
)

# Common language codes/names -> human-readable label used in the directive.
LANGUAGE_ALIASES = {
    "en": "English",
    "english": "English",
    "zh": "Chinese",
    "cn": "Chinese",
    "zh-cn": "Chinese (Simplified)",
    "zh-tw": "Chinese (Traditional)",
    "chinese": "Chinese",
    "中文": "Chinese",
    "ja": "Japanese",
    "japanese": "Japanese",
    "ko": "Korean",
    "korean": "Korean",
    "es": "Spanish",
    "spanish": "Spanish",
    "fr": "French",
    "french": "French",
    "de": "German",
    "german": "German",
    "ru": "Russian",
    "russian": "Russian",
    "pt": "Portuguese",
    "portuguese": "Portuguese",
    "it": "Italian",
    "italian": "Italian",
    "ar": "Arabic",
    "arabic": "Arabic",
    "hi": "Hindi",
    "hindi": "Hindi",
}


def log(message: str) -> None:
    """Print a progress message to stderr (stdout is reserved for the review)."""
    print(message, file=sys.stderr)


@dataclass
class Config:
    github_token: str
    openai_token: str
    model: str
    base_url: str
    language: str
    prompt: str
    max_tokens_per_chunk: int
    silent: bool
    dry_run: bool


def env_bool(name: str, default: bool = False) -> bool:
    """Read a boolean-style environment variable."""
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


def load_prompt() -> str:
    """Resolve the review prompt from REVIEW_PROMPT, then prompt.md."""
    explicit = os.environ.get("REVIEW_PROMPT", "").strip()
    if explicit:
        return explicit

    if DEFAULT_PROMPT_FILE.is_file():
        content = DEFAULT_PROMPT_FILE.read_text(encoding="utf-8").strip()
        if content:
            return content

    log("Warning: prompt.md is missing or empty; using fallback prompt.")
    return FALLBACK_PROMPT


def load_config() -> Config:
    """Build the runtime configuration from environment variables."""
    github_token = os.environ.get("GITHUB_TOKEN", "").strip()
    openai_token = os.environ.get("OPENAI_API_KEY", "").strip()
    if not github_token:
        raise SystemExit("Error: GITHUB_TOKEN environment variable is required.")
    if not openai_token:
        raise SystemExit("Error: OPENAI_API_KEY environment variable is required.")

    try:
        max_tokens_per_chunk = int(
            os.environ.get("MAX_TOKENS_PER_CHUNK", DEFAULT_MAX_TOKENS_PER_CHUNK)
        )
    except ValueError:
        log("Warning: invalid MAX_TOKENS_PER_CHUNK; using default.")
        max_tokens_per_chunk = DEFAULT_MAX_TOKENS_PER_CHUNK

    return Config(
        github_token=github_token,
        openai_token=openai_token,
        model=os.environ.get("OPENAI_API_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL,
        base_url=os.environ.get("OPENAI_API_BASE_URL", DEFAULT_BASE_URL).strip() or DEFAULT_BASE_URL,
        language=os.environ.get("REVIEW_LANGUAGE", "en").strip() or "en",
        prompt=load_prompt(),
        max_tokens_per_chunk=max_tokens_per_chunk,
        silent=env_bool("SILENT_MODE"),
        dry_run=env_bool("DRY_RUN"),
    )


def resolve_language(language: Optional[str]) -> str:
    """Normalize a language code/name to a human-readable label."""
    if not language:
        return "English"
    key = language.strip().lower()
    if key in LANGUAGE_ALIASES:
        return LANGUAGE_ALIASES[key]
    # Fall back to the base code for region-suffixed tags (e.g. "fr-fr" -> "fr").
    base = key.split("-", 1)[0]
    return LANGUAGE_ALIASES.get(base, language.strip())


def build_system_prompt(prompt: str, language: Optional[str]) -> str:
    """Attach an explicit output-language directive to the review prompt."""
    label = resolve_language(language)
    if label.lower() == "english":
        return prompt
    return (
        prompt
        + "\n\n## Output Language\n"
        + f"Write your ENTIRE review in {label}. "
        + "Keep code snippets, file paths, and technical terms unchanged."
    )


def load_event() -> Tuple[str, Dict[str, Any]]:
    """Read the current GitHub Actions event name and payload."""
    event_name = os.environ.get("GITHUB_EVENT_NAME") or ""
    event_path = os.environ.get("GITHUB_EVENT_PATH")
    payload: Dict[str, Any] = {}
    if event_path and os.path.exists(event_path):
        with open(event_path, encoding="utf-8") as fh:
            payload = json.load(fh)
    return event_name, payload


def resolve_pull_request(event_name: str, payload: Dict[str, Any]) -> Tuple[str, str, int]:
    """Determine (owner, repo, number) from the GitHub Actions environment."""
    repo_slug = os.environ.get("GITHUB_REPOSITORY")

    owner: Optional[str] = None
    repo: Optional[str] = None
    if repo_slug and "/" in repo_slug:
        owner, repo = repo_slug.split("/", 1)
    if not (owner and repo):
        repository = payload.get("repository") or {}
        owner = owner or repository.get("owner", {}).get("login")
        repo = repo or repository.get("name")

    number: Optional[int] = None
    if event_name in ("pull_request", "pull_request_target"):
        number = (payload.get("pull_request") or {}).get("number")
    elif event_name == "issue_comment":
        if (payload.get("issue") or {}).get("pull_request"):
            number = (payload.get("issue") or {}).get("number")
    if number is None:
        # Manual/local runs: allow an explicit override.
        number = int(os.environ.get("GITHUB_PR_NUMBER", 0) or 0) or None

    if not (owner and repo and number):
        raise SystemExit(
            "Could not determine the pull request. This tool expects the GitHub "
            "Actions environment (GITHUB_REPOSITORY + GITHUB_EVENT_PATH), or set "
            "GITHUB_PR_NUMBER for manual runs."
        )

    return owner, repo, int(number)


def _summarize_files(files: List[Dict[str, Any]]) -> List[str]:
    """Render a one-line summary per file, used for overview and chunk context."""
    return [
        f"- **{f.get('filename', '')}** ({f.get('status', '')}): "
        f"+{f.get('additions', 0)} -{f.get('deletions', 0)}"
        for f in files
    ]


def fetch_conversation(
    gh: GitHubClient, owner: str, repo: str, number: int
) -> List[Dict[str, str]]:
    """Collect prior reviews and comments into a chronological transcript."""
    entries: List[Dict[str, str]] = []

    try:
        for review in gh.list_reviews(owner, repo, number):
            body = (review.get("body") or "").strip()
            if not body:
                continue
            entries.append(
                {
                    "ts": review.get("submitted_at") or "",
                    "who": (review.get("user") or {}).get("login", "unknown"),
                    "kind": "review",
                    "body": body,
                }
            )
    except Exception as exc:  # noqa: BLE001 - context is best-effort
        log(f"Warning: could not fetch prior reviews: {exc}")

    try:
        for comment in gh.list_comments(owner, repo, number):
            body = (comment.get("body") or "").strip()
            if not body:
                continue
            entries.append(
                {
                    "ts": comment.get("created_at") or "",
                    "who": (comment.get("user") or {}).get("login", "unknown"),
                    "kind": "comment",
                    "id": comment.get("id"),
                    "body": body,
                }
            )
    except Exception as exc:  # noqa: BLE001 - context is best-effort
        log(f"Warning: could not fetch prior comments: {exc}")

    entries.sort(key=lambda e: e["ts"])
    return entries


def render_conversation(
    entries: List[Dict[str, str]],
    max_entries: int = MAX_CONVERSATION_ENTRIES,
    max_chars: int = MAX_CONVERSATION_ENTRY_CHARS,
) -> str:
    """Render a conversation transcript for inclusion in the review prompt."""
    if not entries:
        return ""

    blocks = []
    for entry in entries[-max_entries:]:
        body = entry["body"]
        if len(body) > max_chars:
            body = body[:max_chars] + "\n… (truncated)"
        label = "review" if entry["kind"] == "review" else "comment"
        blocks.append(f"### {entry['who']} ({label})\n\n{body}")
    return "\n\n".join(blocks)


def merge_conversation(
    stored: List[Dict[str, Any]], fresh: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """Merge stored and freshly-fetched entries, deduping by body content.

    ``fresh`` (from GitHub) is authoritative over ``stored`` (local cache),
    so when the same body appears in both the fresh entry (correct login) wins.
    """
    by_key: Dict[str, Dict[str, Any]] = {}
    for entry in [*stored, *fresh]:
        key = " ".join((entry.get("body") or "").split())
        if not key:
            continue
        by_key[key] = entry
    merged = sorted(by_key.values(), key=lambda e: e.get("ts", ""))
    return merged


def comment_mentions_bot(body: str, login: str) -> bool:
    """Return True if the comment @-mentions the bot (with or without [bot])."""
    if not body or not login:
        return False
    lowered = body.lower()
    login = login.lower()
    candidates = {login}
    if login.endswith("[bot]"):
        candidates.add(login[: -len("[bot]")])
    return any(f"@{c}" in lowered for c in candidates)


def annotate_diff(patch: str) -> str:
    """Number each diff line with its absolute file line.

    ``+`` and context lines get the new-file (RIGHT) line number; ``-`` lines
    get the old-file (LEFT) line number. The model can then reference these
    numbers directly instead of doing hunk-header arithmetic.
    """
    out: List[str] = []
    old_line: Optional[int] = None
    new_line: Optional[int] = None
    for line in patch.splitlines():
        if line.startswith("@@"):
            match = re.match(r"@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@", line)
            if match:
                old_line = int(match.group(1))
                new_line = int(match.group(2))
            out.append(line)
        elif line.startswith("+") and new_line is not None:
            out.append(f"{new_line:>5}: +{line[1:]}")
            new_line += 1
        elif line.startswith("-") and old_line is not None:
            out.append(f"{old_line:>5}: -{line[1:]}")
            old_line += 1
        elif line.startswith("\\"):
            out.append(line)
        elif new_line is not None and old_line is not None:
            out.append(f"{new_line:>5}: {line[1:]}")
            new_line += 1
            old_line += 1
        else:
            out.append(line)
    return "\n".join(out)


def build_diff_text(
    pr: Dict[str, Any],
    files: List[Dict[str, Any]],
    all_files: Optional[List[Dict[str, Any]]] = None,
    conversation: str = "",
) -> str:
    """Render PR metadata and per-file diffs into a single review payload.

    ``files`` are the files to review in detail; ``all_files`` is the complete
    list of files, used to provide context when reviewing a chunk of a large PR.
    ``conversation`` is an optional transcript of prior reviews/comments.
    """
    is_chunk = all_files is not None and len(all_files) > len(files)

    head = pr.get("head", {}).get("ref", "")
    base = pr.get("base", {}).get("ref", "")
    lines = [
        "# Pull Request Review Request",
        f"**Title**: {pr.get('title', '')}",
        f"**Author**: {pr.get('user', {}).get('login', 'unknown')}",
        f"**Branch**: {head} -> {base}",
        "",
        "**Description**:",
        pr.get("body") or "(No description provided)",
        "",
        f"**Total Files Changed**: {len(all_files) if is_chunk else len(files)}",
        f"**Additions**: +{pr.get('additions', 0)}",
        f"**Deletions**: -{pr.get('deletions', 0)}",
        "",
    ]

    if conversation:
        lines += [
            "## Previous Conversation",
            "",
            "The following prior reviews and comments on this pull request are "
            "provided for context:",
            "",
            conversation,
            "",
        ]

    if is_chunk:
        lines += [
            "## Chunk Review Context",
            "",
            f"You are reviewing {len(files)} of {len(all_files)} total files.",
            "The complete PR includes these files (for context only):",
            "",
            *_summarize_files(all_files),
            "",
            "**Instructions**:",
            "- Review ONLY the files under 'Files to Review' below in detail.",
            "- Use the full file list above to resolve imports, references, and "
            "cross-file relationships — do NOT flag a reference as missing if the "
            "file is listed above.",
            "",
            "## Files to Review",
            "",
            *_summarize_files(files),
            "",
        ]
    else:
        lines += [
            "## Files Modified",
            "",
            *_summarize_files(files),
            "",
        ]

    lines.append("## Changes")
    lines.append("")
    for f in files:
        filename = f.get("filename", "")
        status = f.get("status", "")
        additions = f.get("additions", 0)
        deletions = f.get("deletions", 0)
        patch = f.get("patch")
        lines.append(f"### {filename} ({status}) +{additions} -{deletions}")
        if patch:
            lines.append("```diff")
            lines.append(annotate_diff(patch))
            lines.append("```")
        else:
            lines.append("_(no textual patch available)_")
        lines.append("")
    return "\n".join(lines)


def chunk_files(files: List[Dict[str, Any]], max_chars: int) -> List[List[Dict[str, Any]]]:
    """Split files into chunks so no chunk exceeds ``max_chars``."""
    chunks: List[List[Dict[str, Any]]] = []
    current: List[Dict[str, Any]] = []
    size = 0
    for f in files:
        f_size = len(f.get("patch") or "") + len(f.get("filename", "")) + 120
        if current and size + f_size > max_chars:
            chunks.append(current)
            current = []
            size = 0
        current.append(f)
        size += f_size
    if current:
        chunks.append(current)
    return chunks


def review_files(
    ai: AIClient,
    system_prompt: str,
    pr: Dict[str, Any],
    files: List[Dict[str, Any]],
    all_files: Optional[List[Dict[str, Any]]] = None,
    conversation: str = "",
) -> str:
    """Review a set of files and return the AI's Markdown review."""
    diff_text = build_diff_text(pr, files, all_files, conversation)
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": diff_text},
    ]
    return ai.chat(messages)


def perform_review(
    ai: AIClient,
    system_prompt: str,
    pr: Dict[str, Any],
    files: List[Dict[str, Any]],
    max_tokens_per_chunk: int,
    conversation: str = "",
) -> str:
    """Review the whole PR, chunking large diffs and combining the results."""
    max_chars = max_tokens_per_chunk * CHARS_PER_TOKEN
    chunks = chunk_files(files, max_chars)

    if len(chunks) <= 1:
        return review_files(ai, system_prompt, pr, files, conversation=conversation)

    log(f"Large PR: reviewing in {len(chunks)} chunks.")
    reviews = []
    for i, chunk in enumerate(chunks, start=1):
        log(f"Reviewing chunk {i}/{len(chunks)} ({len(chunk)} files)...")
        chunk_review = review_files(
            ai, system_prompt, pr, chunk, all_files=files, conversation=conversation
        )
        filenames = "\n".join(f"  - {f['filename']}" for f in chunk)
        reviews.append(
            f"## Chunk {i}/{len(chunks)}\n\nFiles:\n{filenames}\n\n{chunk_review}"
        )

    return "# AI Code Review (multi-part)\n\n" + "\n\n---\n\n".join(reviews)


def generate_reply(
    ai: AIClient,
    reply_prompt: str,
    conversation: str,
    author: str,
    comment_body: str,
) -> str:
    """Generate a short, plain reply to a human comment on the pull request."""
    parts: List[str] = []
    if conversation:
        parts.append(
            "## Previous Conversation\n\nThe following prior reviews and comments "
            f"on this pull request are provided for context:\n\n{conversation}"
        )
    parts.append(
        f"## New Comment\n\n**{author}** just wrote:\n\n{comment_body}\n\n"
        "Reply concisely and directly to this comment."
    )
    messages = [
        {"role": "system", "content": reply_prompt},
        {"role": "user", "content": "\n\n".join(parts)},
    ]
    return ai.chat(messages)


def _as_int(value: Any) -> Optional[int]:
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def extract_inline_comments(review_text: str) -> Tuple[str, List[Dict[str, Any]]]:
    """Extract a JSON ``{"comments": [...]}`` block from the review.

    Returns the cleaned review text (JSON block removed) and the list of raw
    inline comments.
    """
    comments: List[Dict[str, Any]] = []
    cleaned = review_text
    pattern = re.compile(r"```[^\n`]*\n([\s\S]*?)\n```")
    for match in pattern.finditer(review_text):
        try:
            data = json.loads(match.group(1))
        except ValueError:
            continue
        if isinstance(data, dict) and isinstance(data.get("comments"), list):
            comments.extend(c for c in data["comments"] if isinstance(c, dict))
            cleaned = cleaned.replace(match.group(0), "")
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    return cleaned, comments


def normalize_inline_comments(
    raw: List[Dict[str, Any]], files: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """Validate/normalize raw findings into GitHub review-comment objects."""
    valid_paths = {f.get("filename") for f in files}
    out: List[Dict[str, Any]] = []
    for c in raw:
        path = c.get("path")
        body = c.get("body")
        line = _as_int(c.get("line"))
        if not isinstance(path, str) or not isinstance(body, str):
            continue
        if path not in valid_paths or not line or line <= 0:
            continue
        side = c.get("side", "RIGHT")
        if side not in ("LEFT", "RIGHT"):
            side = "RIGHT"
        comment: Dict[str, Any] = {"path": path, "line": line, "side": side, "body": body}
        start_line = _as_int(c.get("start_line"))
        if start_line and 0 < start_line < line:
            comment["start_line"] = start_line
            start_side = c.get("start_side", side)
            comment["start_side"] = start_side if start_side in ("LEFT", "RIGHT") else side
        out.append(comment)
    return out


def _strip_mention(body: str, bot_login: str) -> str:
    """Remove the leading bot @-mention from the comment body."""
    candidates = {bot_login}
    if bot_login.endswith("[bot]"):
        candidates.add(bot_login[: -len("[bot]")])
    for candidate in candidates:
        if candidate:
            body = body.replace(f"@{candidate}", "", 1)
    return body.strip()


def classify_intent(ai: AIClient, body: str) -> str:
    """Classify whether a comment asks to improve the prompt, or is a normal reply."""
    try:
        result = ai.chat(
            [
                {"role": "system", "content": INTENT_CLASSIFIER_PROMPT},
                {"role": "user", "content": body},
            ],
            temperature=0.0,
        )
        return result.strip().lower()
    except Exception as exc:  # noqa: BLE001 - fall back to a normal reply
        log(f"Warning: intent classification failed ({exc}); defaulting to reply.")
        return "reply"


def handle_improve_prompt(
    ai: AIClient,
    gh: GitHubClient,
    body: str,
    author: str,
    owner: str,
    repo: str,
    number: int,
    bot_login: str,
) -> int:
    """Generate an improved prompt.md and submit it as a PR to ToolsWorkflow."""
    feedback = _strip_mention(body, bot_login)
    if not feedback:
        gh.post_comment(
            owner, repo, number,
            f"@{author} 请补充具体建议，例如：`@perotoolsbot 把评审改得更简洁`",
        )
        return 0

    current_prompt = ""
    if DEFAULT_PROMPT_FILE.is_file():
        current_prompt = DEFAULT_PROMPT_FILE.read_text(encoding="utf-8")
    if not current_prompt:
        gh.post_comment(owner, repo, number, f"@{author} 无法读取当前 prompt.md，请检查。")
        return 0

    log("Generating improved prompt...")
    messages = [
        {"role": "system", "content": IMPROVE_PROMPT_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"Current prompt:\n\n{current_prompt}\n\n---\n\n"
                f"User feedback: {feedback}\n\nProduce the improved prompt."
            ),
        },
    ]
    improved = ai.chat(messages, temperature=0.3)
    if not improved:
        log("Error: AI returned empty improved prompt.")
        gh.post_comment(owner, repo, number, f"@{author} 改进失败，AI 返回了空内容。")
        return 0

    tools_repo = os.environ.get("TOOLS_REPO", "peroperogames/ToolsWorkflow")
    tools_owner, tools_repo_name = tools_repo.split("/", 1)
    branch = f"ai-prompt-{int(datetime.now(timezone.utc).timestamp())}"

    try:
        log(f"Creating branch {branch} in {tools_repo}...")
        gh.create_branch(tools_owner, tools_repo_name, branch)
        gh.put_file(
            tools_owner, tools_repo_name,
            "review/prompt.md", improved, branch,
            "ai: improve review prompt based on feedback",
        )
        pr = gh.create_pr(
            tools_owner, tools_repo_name,
            title="AI: improve review prompt",
            head=branch,
            base="main",
            body=f"根据 @{author} 的反馈自动改进 prompt.md\n\n**反馈**: {feedback}",
        )
        pr_url = pr.get("html_url", "")
        log(f"Prompt PR created: {pr_url}")
        gh.post_comment(
            owner, repo, number,
            f"@{author} 已提交 PR 更新 prompt.md: {pr_url}",
        )
    except Exception as exc:
        log(f"Error creating prompt PR: {exc}")
        gh.post_comment(
            owner, repo, number,
            f"@{author} 提交 PR 失败: {exc}",
        )

    return 0


def _parse_json_response(text: str) -> Dict[str, Any]:
    """Strip optional markdown fences and parse JSON."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()
    return json.loads(text)


def handle_code_change(
    ai: AIClient,
    gh: GitHubClient,
    pr: Dict[str, Any],
    body: str,
    author: str,
    owner: str,
    repo: str,
    number: int,
    conversation: str,
    bot_login: str,
) -> int:
    """Generate code changes and submit a PR to the current repository."""
    instruction = _strip_mention(body, bot_login)
    if not instruction:
        gh.post_comment(
            owner, repo, number,
            f"@{author} 请说明要做什么改动，例如：`@perotoolsbot 把 src/foo.py 里的 N+1 查询修一下`",
        )
        return 0

    head_ref = pr["head"]["ref"]
    log(f"Reading file contents from {head_ref}...")
    files = gh.list_files(owner, repo, number)
    file_contents: List[Dict[str, str]] = []
    for f in files:
        try:
            content = gh.get_file_content(owner, repo, f["filename"], ref=head_ref)
            file_contents.append({"path": f["filename"], "content": content})
        except Exception as exc:
            log(f"Warning: could not read {f['filename']}: {exc}")

    if not file_contents:
        gh.post_comment(owner, repo, number, f"@{author} 无法读取文件内容，请检查分支权限。")
        return 0

    log("Generating code changes...")
    files_text = "\n\n".join(
        f"### {fc['path']}\n```\n{fc['content']}\n```"
        for fc in file_contents
    )
    messages = [
        {"role": "system", "content": CODE_CHANGE_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"## Conversation Context\n\n{conversation}\n\n"
                f"## Current Files\n\n{files_text}\n\n"
                f"## Instruction\n\n{instruction}\n\n"
                "Generate the code changes as JSON."
            ),
        },
    ]
    result = ai.chat(messages, temperature=0.3)
    if not result:
        gh.post_comment(owner, repo, number, f"@{author} 代码生成失败，AI 返回了空内容。")
        return 0

    try:
        data = _parse_json_response(result)
    except (ValueError, KeyError) as exc:
        log(f"Failed to parse code-change JSON: {exc}")
        gh.post_comment(owner, repo, number, f"@{author} 代码生成失败，AI 返回了无效格式: {exc}")
        return 0

    commit_msg = (data.get("message") or "ai: apply code changes").strip()
    changed_files = data.get("files") or []
    if not isinstance(changed_files, list) or not changed_files:
        gh.post_comment(owner, repo, number, f"@{author} 代码生成失败，AI 没有返回文件改动。")
        return 0

    branch = f"ai-change-{int(datetime.now(timezone.utc).timestamp())}"
    try:
        log(f"Creating branch {branch} from {head_ref}...")
        gh.create_branch(owner, repo, branch, base_branch=head_ref)
        for fc in changed_files:
            path = fc.get("path")
            content = fc.get("content")
            if not path or content is None:
                continue
            gh.put_file(owner, repo, path, content, branch, commit_msg)
        pr_result = gh.create_pr(
            owner, repo,
            title=commit_msg,
            head=branch,
            base=head_ref,
            body=f"根据 @{author} 的指令自动生成\n\n**指令**: {instruction}",
        )
        pr_url = pr_result.get("html_url", "")
        log(f"Code-change PR created: {pr_url}")
        gh.post_comment(owner, repo, number, f"@{author} 已提交 PR: {pr_url}")
    except Exception as exc:
        log(f"Error creating code-change PR: {exc}")
        gh.post_comment(owner, repo, number, f"@{author} 提交 PR 失败: {exc}")

    return 0


def determine_event(review_text: str) -> str:
    """Map the review content to a GitHub review event."""
    t = review_text.lower()
    critical = any(k in t for k in ("critical", "blocking", "blocker", "must fix", "must-fix", "🔴"))
    warning = any(k in t for k in ("warning", "⚠️"))
    approved = any(k in t for k in ("approved", "looks good", "no issues", "✅"))
    if critical:
        return "REQUEST_CHANGES"
    if warning:
        return "COMMENT"
    if approved:
        return "APPROVE"
    return "COMMENT"


def labels_for_event(event: str) -> List[str]:
    if event == "REQUEST_CHANGES":
        return ["needs-changes"]
    if event == "APPROVE":
        return ["ai-approved"]
    return []


def main() -> int:
    config = load_config()
    system_prompt = build_system_prompt(config.prompt, config.language)
    reply_prompt = build_system_prompt(REPLY_SYSTEM_PROMPT, config.language)

    event_name, payload = load_event()

    # issue_comment: respond only to a human comment that @-mentions the bot.
    # GitHub does not expose threading for issue comments (in_reply_to_id only
    # exists for PR review comments), so a "reply" cannot be detected — an
    # @-mention is the reliable trigger.
    is_issue_comment = event_name == "issue_comment"
    comment: Dict[str, Any] = {}
    if is_issue_comment:
        issue = payload.get("issue") or {}
        comment = payload.get("comment") or {}
        if not issue.get("pull_request"):
            log("Ignoring comment on a non-pull-request issue.")
            return 0
        author = (comment.get("user") or {}).get("login", "")
        if author.endswith("[bot]"):
            log("Ignoring comment from a bot (prevents reply loops).")
            return 0

    owner, repo, number = resolve_pull_request(event_name, payload)

    gh = GitHubClient(config.github_token)
    ai = AIClient(config.openai_token, model=config.model, base_url=config.base_url)

    log(f"Repository: {owner}/{repo}")
    log(f"Pull Request: #{number}")
    log(f"Model: {config.model}")
    log(f"Language: {config.language}")

    pr = gh.get_pull_request(owner, repo, number)

    # Closed PRs need no review; drop any persisted history for them.
    if (pr.get("state") or "open") == "closed":
        history.delete(owner, repo, number)
        log(f"Pull Request #{number} is closed; removed any local review history.")
        return 0

    stored = history.load(owner, repo, number)
    fresh = fetch_conversation(gh, owner, repo, number)

    # Reply mode.
    if is_issue_comment:
        body = comment.get("body") or ""
        # Determine bot login from the conversation (bot-authored entries),
        # with an env-var fallback for the first run when no history exists yet.
        bot_login = os.environ.get("BOT_LOGIN", "").strip() or "perotoolsbot[bot]"
        if bot_login and not comment_mentions_bot(body, bot_login):
            log(f"Ignoring comment that does not @-mention the bot (@{bot_login}).")
            return 0

        author = (comment.get("user") or {}).get("login", "unknown")

        # Drop the triggering comment from the context (it is injected below).
        body_key = " ".join(body.split())
        fresh = [
            e
            for e in fresh
            if not (
                e.get("who") == author
                and " ".join((e.get("body") or "").split()) == body_key
            )
        ]

        entries = merge_conversation(stored, fresh)
        conversation = render_conversation(entries)

        # Classify intent and route.
        intent = classify_intent(ai, body)
        if "improve" in intent:
            return handle_improve_prompt(
                ai, gh, body, author, owner, repo, number, bot_login
            )
        if "code" in intent:
            return handle_code_change(
                ai, gh, pr, body, author, owner, repo, number, conversation, bot_login
            )

        reply = generate_reply(ai, reply_prompt, conversation, author, body)
        if not reply:
            log("Error: the AI returned an empty reply.")
            return 1

        if config.dry_run:
            print(reply)
            return 0

        result = gh.post_comment(owner, repo, number, reply)
        log("Posted reply comment.")

        entries.append(
            {
                "ts": datetime.now(timezone.utc).isoformat(),
                "who": (result.get("user") or {}).get("login", "") or bot_login,
                "kind": "comment",
                "body": reply,
            }
        )
        history.save(owner, repo, number, entries[-MAX_CONVERSATION_ENTRIES:])
        return 0

    # Review mode.
    files = gh.list_files(owner, repo, number)
    log(f"Changed files: {len(files)}")

    if not files:
        log("No changed files found; nothing to review.")
        return 0

    entries = merge_conversation(stored, fresh)
    conversation = render_conversation(entries)
    if conversation:
        log(f"Using {len(entries)} prior review/comment entry(ies) as context.")

    review = perform_review(
        ai, system_prompt, pr, files, config.max_tokens_per_chunk, conversation
    )
    if not review:
        log("Error: the AI returned an empty review.")
        return 1

    review_text, raw_comments = extract_inline_comments(review)
    inline = normalize_inline_comments(raw_comments, files)
    if inline:
        log(f"Found {len(inline)} inline comment(s).")

    event = determine_event(review_text)
    log(f"Review event: {event}")

    if config.dry_run:
        print(review_text)
        return 0

    if config.silent:
        result = gh.post_comment(owner, repo, number, review_text)
        log("Posted review as a regular comment (silent mode).")
    else:
        try:
            result = gh.post_review(owner, repo, number, review_text, event=event, comments=inline)
            if inline:
                log(f"Posted review ({event}) with {len(inline)} inline comment(s).")
            else:
                log(f"Posted review with event: {event}")
        except Exception as exc:  # noqa: BLE001 - fall back to body-only review
            log(f"Warning: posting review with inline comments failed ({exc}); retrying without them.")
            result = gh.post_review(owner, repo, number, review_text, event=event)
            log(f"Posted review with event: {event}")

    for label in labels_for_event(event):
        try:
            gh.add_labels(owner, repo, number, [label])
            log(f"Added label: {label}")
        except Exception as exc:  # noqa: BLE001 - labels are best-effort
            log(f"Warning: failed to add label '{label}': {exc}")

    # Persist this run's review so the next run can build on it.
    entries.append(
        {
            "ts": datetime.now(timezone.utc).isoformat(),
            "who": (result.get("user") or {}).get("login", "ai-reviewer"),
            "kind": "review",
            "body": review_text,
        }
    )
    history.save(owner, repo, number, entries[-MAX_CONVERSATION_ENTRIES:])

    return 0


if __name__ == "__main__":
    sys.exit(main())
