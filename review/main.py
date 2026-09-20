#!/usr/bin/env python3
"""GitHub AI Code Review.

Fetches a pull request from GitHub, sends its diff to an OpenAI-compatible chat
completions API for review, and posts the result back to the pull request as a
review (APPROVE / REQUEST_CHANGES / COMMENT).

The tool is fully configured through environment variables (no CLI arguments):

    GITHUB_TOKEN          (required) GitHub token with pull-requests write access.
    OPENAI_API_KEY        (required) OpenAI-compatible API token.
    OPENAI_API_MODEL      (optional) Model to use (default: gpt-4o).
    OPENAI_API_MODEL_FALLBACK (optional) Fallback model used if the primary fails.
    OPENAI_API_BASE_URL   (optional) API base URL (default: https://api.openai.com/v1).
    REVIEW_LANGUAGE       (optional) Review output language (default: en).
    MAX_TOKENS_PER_CHUNK  (optional) Max tokens per chunk for large PRs (default: 131072).
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

# Bumped whenever behaviour changes, so the job log shows which build ran.
VERSION = "2026-09-18.5"

# Sections the review body is assembled from when the model only returns
# comments (JSON-only prompt) rather than ready-made Markdown.
REVIEW_SECTIONS = (
    ("blocker", "🔴 Blockers"),
    ("warning", "⚠️ Warnings"),
    ("suggestion", "💡 Suggestions"),
    ("security", "🔒 Security"),
    ("performance", "⚡ Performance"),
    ("recommendation_immediate", "Immediate (before merge)"),
    ("recommendation_short", "Short-term (next sprint)"),
    ("recommendation_long", "Long-term (technical debt)"),
    ("strength", "✅ Strengths"),
)

# Rough heuristic: ~4 characters per token, used for chunking large PRs.
CHARS_PER_TOKEN = 4
DEFAULT_MAX_TOKENS_PER_CHUNK = 131072  # DeepSeek V4's max_tokens ceiling

# Conversation transcript limits, to avoid unbounded context growth.
MAX_CONVERSATION_ENTRIES = 50
MAX_CONVERSATION_ENTRY_CHARS = 4000


# Minimal fallback used only when prompt.md is empty.
FALLBACK_PROMPT = (
    "You are an expert software engineer performing a thorough code review. "
    "Identify bugs, security issues, performance problems, and maintainability "
    "concerns. Be specific (file and line), actionable (show fixes), and "
    "constructive (acknowledge what was done well). Return a structured Markdown review."
)

# Prompt used when answering a developer's reply — short and plain, not a review.
REPLY_SYSTEM_PROMPT = (
    "You are a helpful AI code review assistant. A developer has @-mentioned you "
    "on a pull request. Answer their question concisely and directly — a short, "
    "plain message, NOT a full structured review. If the user is asking for a "
    "review but none has been done yet, explain that you review automatically "
    "when a PR is opened or updated. Reference files or code only when it helps.\n"
    "When the developer asks about a comment you left, quote or paraphrase that "
    "specific finding and explain the reasoning behind it. Never claim to have "
    "said something that is not in the conversation above, and never guess at "
    "what you 'previously replied' — if the context is missing, say so plainly."
)

INTENT_CLASSIFIER_PROMPT = (
    "Classify the intent of this GitHub comment directed at you (a code review bot).\n"
    "Reply with EXACTLY one of these four words, nothing else:\n"
    "- 'improve_prompt' — the user wants you to change HOW you review: your "
    "instructions, your prompt, prompt.md, your review style, wording, or format.\n"
    "- 'review' — the user wants you to review this PR now.\n"
    "- 'code_change' — the user wants the SOURCE CODE of the repo under review "
    "changed (fix a bug, add a feature, refactor).\n"
    "- 'reply' — anything else: questions, acknowledgements, discussion.\n"
    "Rules:\n"
    "- Feedback about your own reviewing behaviour (too long, use inline "
    "comments, be stricter, ...) is 'improve_prompt', NOT 'code_change'.\n"
    "- Only choose 'code_change' when the repo's actual source code must change.\n"
    "- If a comment contains an acknowledgement or quoted reply and no clear "
    "request, choose 'reply'."
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
    fallback_model: str
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
    """Resolve the review prompt from prompt.md."""
    path = DEFAULT_PROMPT_FILE
    if path.is_file():
        content = path.read_text(encoding="utf-8").strip()
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
        fallback_model=os.environ.get("OPENAI_API_MODEL_FALLBACK", "").strip(),
        base_url=os.environ.get("OPENAI_API_BASE_URL", DEFAULT_BASE_URL).strip() or DEFAULT_BASE_URL,
        language=os.environ.get("REVIEW_LANGUAGE", "en").strip() or "en",
        prompt=load_prompt(),
        max_tokens_per_chunk=max_tokens_per_chunk,
        silent=env_bool("SILENT_MODE", default=True),
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
    if event_name in (
        "pull_request",
        "pull_request_target",
        "pull_request_review_comment",
    ):
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

    # Inline comments live on their own endpoint; without them the bot cannot
    # explain or follow up on the findings it posted on individual lines.
    try:
        for comment in gh.list_review_comments(owner, repo, number):
            body = (comment.get("body") or "").strip()
            if not body:
                continue
            where = comment.get("path") or ""
            line = comment.get("line") or comment.get("original_line")
            if where and line:
                body = f"[inline {where}:{line}]\n{body}"
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
        log(f"Warning: could not fetch inline review comments: {exc}")

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

    ``+`` lines get the new-file (RIGHT) line number, ``-`` lines the old-file
    (LEFT) one, so the model can quote a line instead of doing hunk-header
    arithmetic. Context lines are kept — the model needs the surrounding code
    to judge what it is looking at.
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


RESOLVE_DECIDER_PROMPT = (
    "Earlier review comments of yours on a pull request are listed below as "
    "unresolved threads. The code below is the diff of the LATEST push only — "
    "that is what changed since your review.\n"
    "Decide which of those threads are now ADDRESSED by those changes and can be "
    "marked resolved.\n"
    'Reply with ONLY a JSON object: {"resolved": ["<thread id>", ...]}\n'
    "Rules:\n"
    "- Include a thread only when the current code clearly fixes or removes the "
    "issue it raised.\n"
    "- If the concern is still present, or you cannot tell, LEAVE IT OUT — an "
    "unresolved thread costs nothing, a wrongly resolved one hides a bug.\n"
    "- Never include ids that are not in the list."
)

INCREMENTAL_DIRECTIVE = (
    "\n\n## Incremental Review Mode\n\n"
    "This is a re-review after new commits were pushed. Do NOT use the "
    "structured report format above. Return only:\n"
    "1. A short, plain summary (2-4 sentences) of issues NEWLY introduced by "
    "the latest changes. If there are none, say so in one sentence.\n"
    "2. The JSON comments block for any line-level findings.\n"
    "Never repeat issues already raised in the earlier reviews."
)

CONSOLIDATE_INSTRUCTION = (
    "The following are partial reviews of the SAME pull request, one per file "
    "group. Merge them into a SINGLE review in the required output format: "
    "combine matching sections, drop duplicates and contradictions, and keep "
    "every distinct finding. Do not invent findings, and do not mention "
    "'chunks', 'parts' or file groups in the result."
)


def consolidate_reviews(
    ai: AIClient, system_prompt: str, parts: List[str]
) -> str:
    """Merge per-chunk reviews into one review body."""
    messages = [
        {"role": "system", "content": system_prompt},
        {
            "role": "user",
            "content": "\n\n---\n\n".join(parts) + "\n\n" + CONSOLIDATE_INSTRUCTION,
        },
    ]
    try:
        merged = ai.chat(messages)
        if merged:
            # The merged body must not carry a JSON block of its own — the
            # per-chunk comments were already collected.
            merged, _ = extract_inline_comments(merged)
            return merged
        log("Warning: consolidation returned empty; keeping concatenated chunks.")
    except Exception as exc:  # noqa: BLE001 - fall back to the raw chunks
        log(f"Warning: consolidation failed ({exc}); keeping concatenated chunks.")
    return "# AI Code Review\n\n" + "\n\n---\n\n".join(parts)


def split_comments(
    comments: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Split comments into line-anchored ones and general (no line) ones."""
    inline: List[Dict[str, Any]] = []
    general: List[Dict[str, Any]] = []
    for c in comments:
        if c.get("path") and c.get("quote"):
            inline.append(c)
        else:
            general.append(c)
    return inline, general


def render_review_body(general: List[Dict[str, Any]], leftover: str = "") -> str:
    """Build the posted review body.

    A prompt that returns Markdown plus a comments block produces ``leftover``
    prose, which is used verbatim. With the JSON-only prompt there is no prose,
    so the general findings are grouped back into sections here.
    """
    if leftover.strip():
        return leftover.strip()
    if not general:
        return ""

    known = {key for key, _ in REVIEW_SECTIONS}
    lines: List[str] = []
    for key, title in REVIEW_SECTIONS:
        items = [
            (c.get("body") or "").strip()
            for c in general
            if (c.get("type") or "").lower() == key
        ]
        items = [i for i in items if i]
        if not items:
            continue
        lines.append(f"## {title}")
        lines.append("")
        lines.extend(f"- {item}" for item in items)
        lines.append("")

    other = [
        (c.get("body") or "").strip()
        for c in general
        if (c.get("type") or "").lower() not in known
    ]
    other = [i for i in other if i]
    if other:
        lines.append("## Other")
        lines.append("")
        lines.extend(f"- {item}" for item in other)

    return "\n".join(lines).strip()


def perform_review(
    ai: AIClient,
    system_prompt: str,
    pr: Dict[str, Any],
    files: List[Dict[str, Any]],
    max_tokens_per_chunk: int,
    conversation: str = "",
) -> Tuple[str, List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Review the whole PR.

    Returns ``(review body, raw line comments, general comments)``. Large diffs
    are reviewed in chunks; general findings are grouped into one body and line
    findings are merged into a single comment list.
    """
    max_chars = max_tokens_per_chunk * CHARS_PER_TOKEN
    chunks = chunk_files(files, max_chars)

    if len(chunks) <= 1:
        raw = review_files(ai, system_prompt, pr, files, conversation=conversation)
        leftover, comments = extract_inline_comments(raw)
        inline, general = split_comments(comments)
        return render_review_body(general, leftover), inline, general

    log(f"Large PR: reviewing in {len(chunks)} chunks.")
    parts: List[str] = []
    comments: List[Dict[str, Any]] = []
    for i, chunk in enumerate(chunks, start=1):
        log(f"Reviewing chunk {i}/{len(chunks)} ({len(chunk)} files)...")
        raw = review_files(
            ai, system_prompt, pr, chunk, all_files=files, conversation=conversation
        )
        leftover, chunk_comments = extract_inline_comments(raw)
        comments.extend(chunk_comments)
        if leftover.strip():
            filenames = "\n".join(f"  - {f['filename']}" for f in chunk)
            parts.append(
                f"### Part {i}/{len(chunks)}\n\nFiles:\n{filenames}\n\n{leftover}"
            )

    inline, general = split_comments(comments)
    if parts:
        log("Consolidating chunk reviews into a single review...")
        body = consolidate_reviews(ai, system_prompt, parts)
    else:
        # JSON-only output: the general findings already merge cleanly.
        body = ""
    return render_review_body(general, body), inline, general


def generate_reply(
    ai: AIClient,
    reply_prompt: str,
    conversation: str,
    author: str,
    comment_body: str,
    thread_context: str = "",
) -> str:
    """Generate a short, plain reply to a human comment on the pull request."""
    parts: List[str] = []
    if conversation:
        parts.append(
            "## Previous Conversation\n\nThe following prior reviews and comments "
            f"on this pull request are provided for context:\n\n{conversation}"
        )
    if thread_context:
        parts.append(
            "## The Comment Being Replied To\n\n"
            "The developer replied inside this thread of yours:\n\n"
            f"{thread_context}"
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


def _heading_start_above(text: str, index: int) -> int:
    """Offset of the markdown heading directly above ``index``.

    Returns ``index`` unchanged when no heading sits right above it (only blank
    lines may separate them). The heading's wording does not matter — whatever
    label the model invented for the comments block goes away with it.
    """
    lines = text[:index].split("\n")
    i = len(lines) - 1
    while i >= 0 and not lines[i].strip():
        i -= 1
    if i < 0 or not re.match(r"^#{1,6}\s+\S", lines[i]):
        return index
    return len("\n".join(lines[:i])) + (1 if i > 0 else 0)


def is_comments_object(data: Any) -> bool:
    """Is this parsed JSON the comments payload we asked for?"""
    if not isinstance(data, dict):
        return False
    entries = data.get("comments")
    if not isinstance(entries, list):
        return False
    if not entries:
        return set(data) == {"comments"}
    # Only `body` is mandatory — a finding without a line has no `path`.
    return all(isinstance(c, dict) and isinstance(c.get("body"), str) for c in entries)


def find_json_object(text: str) -> Optional[Tuple[Dict[str, Any], int, int]]:
    """First JSON object in ``text`` with its ``(obj, start, end)`` offsets.

    The model does not always wrap its JSON in a code fence, so the raw text has
    to be searched as well.
    """
    decoder = json.JSONDecoder(strict=False)
    for index, char in enumerate(text or ""):
        if char != "{":
            continue
        try:
            obj, end = decoder.raw_decode(text, index)
        except ValueError:
            continue
        if isinstance(obj, dict):
            return obj, index, index + end
    return None


def is_comments_payload(body: str) -> bool:
    """Is this fenced block the inline-comments payload we asked for?

    Requires the ``comments`` key *and* the per-entry ``path``/``body`` fields,
    so a JSON sample in the review that merely happens to contain a ``comments``
    key is left alone.
    """
    if '"comments"' not in body:
        return False
    try:
        data = json.loads(body, strict=False)
    except ValueError:
        # Malformed payload: fall back to the structural signature.
        return '"body"' in body
    if not isinstance(data, dict) or not isinstance(data.get("comments"), list):
        return False
    entries = [c for c in data["comments"] if isinstance(c, dict)]
    if not entries:
        # An empty payload is only accepted when it carries nothing else.
        return set(data) == {"comments"}
    # Only `body` is mandatory — a finding without a line has no `path`.
    return all(isinstance(c.get("body"), str) for c in entries)


def extract_inline_comments(review_text: str) -> Tuple[str, List[Dict[str, Any]]]:
    """Extract the JSON ``{"comments": [...]}`` block(s) from the review.

    Returns the review text with those blocks (and their section headings)
    removed, plus the raw inline comments.
    """
    comments: List[Dict[str, Any]] = []
    spans: List[Tuple[int, int]] = []
    # Fences may be indented (the model often nests code blocks inside list
    # items), so leading whitespace must be allowed on both fences — otherwise
    # an indented closer is skipped and the following block gets swallowed.
    pattern = re.compile(r"(?m)^[ \t]*```[^\n`]*\n([\s\S]*?)\n[ \t]*```[ \t]*$")
    for match in pattern.finditer(review_text):
        body = match.group(1)
        # Blocks that are not our payload — including malformed ones — are
        # removed anyway, so raw JSON never ends up in the posted review.
        if not is_comments_payload(body):
            continue
        try:
            data = json.loads(body, strict=False)
        except ValueError:
            data = None
        if isinstance(data, dict) and isinstance(data.get("comments"), list):
            comments.extend(c for c in data["comments"] if isinstance(c, dict))
        spans.append((match.start(), match.end()))

    if not spans:
        # No fenced block — the JSON-only prompt often returns the payload bare.
        found = find_json_object(review_text)
        if found and is_comments_object(found[0]):
            comments = [
                c for c in found[0]["comments"] if isinstance(c, dict)
            ]
            spans.append((found[1], found[2]))

    if spans:
        log(f"Inline comments block: found {len(spans)}, parsed {len(comments)} comment(s).")
    else:
        preview = " ".join((review_text or "").split())[:200]
        log(f"Inline comments block: none found. Output starts with: {preview!r}")

    # Remove from the end backwards so earlier offsets stay valid.
    cleaned = review_text
    for start, end in reversed(spans):
        cleaned = cleaned[: _heading_start_above(cleaned, start)] + cleaned[end:]

    cleaned = re.sub(r"\n+-{3,}\s*\n+-{3,}\s*$", "", cleaned)
    cleaned = re.sub(r"\n+-{3,}\s*$", "", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    return cleaned, comments


def post_inline_comments(
    gh: GitHubClient,
    owner: str,
    repo: str,
    number: int,
    commit_id: str,
    comments: List[Dict[str, Any]],
) -> int:
    """Post inline comments individually (used when there is no review to attach them to)."""
    if not comments:
        return 0
    if not commit_id:
        log("Warning: no commit id available; skipping inline comments.")
        return 0
    posted = 0
    for c in comments:
        try:
            gh.post_review_comment(owner, repo, number, commit_id, c)
            posted += 1
        except Exception as exc:  # noqa: BLE001 - one bad comment shouldn't stop the rest
            log(f"Warning: inline comment failed ({c.get('path')}:{c.get('line')}): {exc}")
    log(f"Posted {posted}/{len(comments)} inline comment(s).")
    return posted


def index_diff_lines(patch: str) -> List[Dict[str, Any]]:
    """Index every line of a patch as ``{"side", "line", "text"}``.

    Context lines appear on both sides; ``+`` lines are RIGHT, ``-`` are LEFT.
    """
    out: List[Dict[str, Any]] = []
    old_line: Optional[int] = None
    new_line: Optional[int] = None
    for raw in patch.splitlines():
        if raw.startswith("@@"):
            match = re.match(r"@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@", raw)
            if match:
                old_line = int(match.group(1))
                new_line = int(match.group(2))
            continue
        if raw.startswith("+") and new_line is not None:
            out.append({"side": "RIGHT", "line": new_line, "text": raw[1:]})
            new_line += 1
        elif raw.startswith("-") and old_line is not None:
            out.append({"side": "LEFT", "line": old_line, "text": raw[1:]})
            old_line += 1
        elif raw.startswith("\\"):
            continue
        elif new_line is not None and old_line is not None:
            text = raw[1:]
            out.append({"side": "RIGHT", "line": new_line, "text": text})
            out.append({"side": "LEFT", "line": old_line, "text": text})
            new_line += 1
            old_line += 1
    return out


def resolve_from_quote(
    comment: Dict[str, Any],
    index: List[Dict[str, Any]],
    side: str,
    line_hint: Optional[int],
) -> Optional[Dict[str, Any]]:
    """Locate a comment's target line by matching its quoted text in the diff.

    The model sometimes quotes several lines at once, so a quote that matches no
    single line is retried against windows of consecutive lines.
    """
    quote = " ".join((comment.get("quote") or "").split())
    if not quote:
        return None

    same_side = [e for e in index if e["side"] == side]
    matches = [e for e in same_side if " ".join(e["text"].split()) == quote]
    if not matches:
        matches = [e for e in index if " ".join(e["text"].split()) == quote]

    if not matches:
        for width in range(2, min(8, len(same_side)) + 1):
            for start in range(len(same_side) - width + 1):
                window = same_side[start : start + width]
                joined = " ".join(" ".join(e["text"].split()) for e in window)
                if joined == quote:
                    matches = [window[-1]]  # anchor on the last line of the range
                    break
            if matches:
                break

    if not matches:
        return None
    if line_hint:
        matches.sort(key=lambda e: abs(e["line"] - line_hint))
    return matches[0]


def normalize_inline_comments(
    raw: List[Dict[str, Any]], files: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """Validate/normalize raw findings into GitHub review-comment objects.

    Line numbers are resolved from the model's quoted source line (reliable)
    and every comment is checked against the diff, so a comment can never land
    on a line that is not part of the change.
    """
    indexes = {
        f.get("filename"): index_diff_lines(f.get("patch") or "") for f in files
    }
    valid = {
        path: {(e["side"], e["line"]) for e in entries}
        for path, entries in indexes.items()
    }

    out: List[Dict[str, Any]] = []
    for c in raw:
        path = c.get("path")
        body = c.get("body")
        if not isinstance(path, str) or not isinstance(body, str):
            continue
        if path not in indexes:
            continue
        side = c.get("side", "RIGHT")
        if side not in ("LEFT", "RIGHT"):
            side = "RIGHT"
        line = _as_int(c.get("line"))

        # Prefer the quoted source line — the model only has to copy text,
        # not compute line numbers.
        located = resolve_from_quote(c, indexes[path], side, line)
        if located:
            side, line = located["side"], located["line"]

        if not line or line <= 0:
            continue
        if (side, line) not in valid[path]:
            log(f"Warning: dropping inline comment off the diff: {path}:{line} ({side}).")
            continue

        comment: Dict[str, Any] = {"path": path, "line": line, "side": side, "body": body}

        # Cross-line range: resolve the first line the same way.
        start_line = _as_int(c.get("start_line"))
        start_quote = c.get("start_quote")
        if isinstance(start_quote, str) and start_quote.strip():
            located_start = resolve_from_quote(
                {"quote": start_quote}, indexes[path], side, start_line
            )
            if located_start:
                start_line = located_start["line"]
        if start_line and 0 < start_line < line and (side, start_line) in valid[path]:
            comment["start_line"] = start_line
            comment["start_side"] = side

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


# Comments containing these target the bot's own review setup rather than the
# repo's source code, so they are prompt improvements regardless of what the
# LLM classifier guesses.
PROMPT_INTENT_HINTS = (
    "toolsworkflow",
    "prompt.md",
    "提示词",
    "评审规范",
    "评审标准",
    "评审规则",
    "代码规范",
    "review prompt",
    "review standard",
)


def pick_intent(raw: str) -> str:
    """Map a classifier response to one of the known intents."""
    text = (raw or "").strip().lower()
    # Most specific first — "improve_prompt" must win over a loose "review" match.
    for intent in ("improve_prompt", "code_change", "review"):
        if intent in text:
            return intent
    if "improve" in text or "prompt" in text:
        return "improve_prompt"
    return "reply"


def classify_intent(ai: AIClient, body: str) -> str:
    """Classify whether a comment asks to improve the prompt, or is a normal reply."""
    # Deterministic guard: anything that clearly targets the bot's own review
    # setup is prompt improvement, whatever the LLM would have guessed.
    text = (body or "").lower()
    for hint in PROMPT_INTENT_HINTS:
        if hint in text:
            log(f"Intent: improve_prompt (matched hint '{hint}').")
            return "improve_prompt"

    try:
        result = ai.chat(
            [
                {"role": "system", "content": INTENT_CLASSIFIER_PROMPT},
                {"role": "user", "content": body},
            ],
            temperature=0.0,
        )
        intent = pick_intent(result)
        log(f"Classified intent: {intent}")
        return intent
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

    prompt_target = os.environ.get("PROMPT_TARGET", "peroperogames/ToolsWorkflow/review/prompt.md")
    prompt_owner, prompt_repo, prompt_path = prompt_target.split("/", 2)
    branch = f"ai-prompt-{int(datetime.now(timezone.utc).timestamp())}"

    try:
        log(f"Creating branch {branch} in {prompt_owner}/{prompt_repo}...")
        gh.create_branch(prompt_owner, prompt_repo, branch)
        gh.put_file(
            prompt_owner, prompt_repo,
            prompt_path, improved, branch,
            "ai: improve review prompt based on feedback",
        )
        pr = gh.create_pr(
            prompt_owner, prompt_repo,
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


def thread_has_bot_comment(
    gh: GitHubClient, owner: str, repo: str, number: int, comment_id: int
) -> bool:
    """Does the review thread containing ``comment_id`` involve the bot?

    The immediate parent is not enough: once a thread has several turns the
    reply's ``in_reply_to_id`` may point at another human comment, yet the
    thread is still a conversation with the bot.
    """
    try:
        threads = gh.list_review_threads(owner, repo, number)
    except Exception as exc:  # noqa: BLE001 - best-effort
        log(f"Warning: could not inspect review threads: {exc}")
        return False
    for thread in threads:
        nodes = (thread.get("comments") or {}).get("nodes") or []
        if comment_id not in {n.get("databaseId") for n in nodes}:
            continue
        return any(
            (((n.get("author") or {}).get("login")) or "").endswith("[bot]")
            for n in nodes
        )
    return False


def settle_threads_and_approve(
    ai: AIClient,
    gh: GitHubClient,
    owner: str,
    repo: str,
    number: int,
    pr: Dict[str, Any],
    files: List[Dict[str, Any]],
    conversation: str = "",
    push_files: Optional[List[Dict[str, Any]]] = None,
    allow_approve: bool = True,
) -> None:
    """Resolve the threads that are done with, then approve if none are left."""
    decide_resolved_threads(
        ai, gh, owner, repo, number, pr, files, "perotoolsbot[bot]",
        push_files=push_files, conversation=conversation,
    )

    if not allow_approve:
        log("New findings were raised; not approving.")
        return

    remaining = unresolved_bot_thread_count(gh, owner, repo, number)
    if remaining != 0:
        log(f"{remaining} thread(s) still open; not approving.")
        return
    try:
        gh.post_review(
            owner, repo, number, "所有遗留问题已解决 ✅", event="APPROVE"
        )
        log("Approved: no unresolved threads remain.")
    except Exception as exc:  # noqa: BLE001 - approving is best-effort
        log(f"Warning: could not approve: {exc}")


def unresolved_bot_thread_count(
    gh: GitHubClient, owner: str, repo: str, number: int
) -> int:
    """Number of unresolved review threads the bot is part of (-1 if unknown)."""
    try:
        threads = gh.list_review_threads(owner, repo, number)
    except Exception as exc:  # noqa: BLE001 - best-effort
        log(f"Warning: could not count review threads: {exc}")
        return -1

    log(f"Review threads seen: {len(threads)}.")
    count = 0
    for thread in threads:
        nodes = (thread.get("comments") or {}).get("nodes") or []
        authors = ",".join(
            (((n.get("author") or {}).get("login")) or "?") for n in nodes
        )
        resolved = bool(thread.get("isResolved"))
        log(f"  {thread.get('path')} resolved={resolved} comments=[{authors}]")
        if resolved:
            continue
        if any(a.endswith("[bot]") for a in authors.split(",") if a):
            count += 1
    return count


def _first_json_object(text: str) -> Optional[Dict[str, Any]]:
    """Return the first JSON object embedded in ``text``, if any."""
    decoder = json.JSONDecoder()
    for index, char in enumerate(text or ""):
        if char != "{":
            continue
        try:
            obj, _ = decoder.raw_decode(text, index)
        except ValueError:
            continue
        if isinstance(obj, dict):
            return obj
    return None


def decide_resolved_threads(
    ai: AIClient,
    gh: GitHubClient,
    owner: str,
    repo: str,
    number: int,
    pr: Dict[str, Any],
    files: List[Dict[str, Any]],
    bot_login: str,
    push_files: Optional[List[Dict[str, Any]]] = None,
    conversation: str = "",
) -> int:
    """Resolve the review threads that have been settled.

    A thread counts as settled when the latest push fixed it (``push_files``) or
    when the discussion concluded it (``conversation``) — a concern answered in
    the thread is resolved even if no code changed.
    """
    try:
        threads = gh.list_review_threads(owner, repo, number)
    except Exception as exc:  # noqa: BLE001 - best-effort, never block the review
        log(f"Warning: could not list review threads: {exc}")
        return 0

    candidates: List[Dict[str, Any]] = []
    for thread in threads:
        if thread.get("isResolved"):
            continue
        nodes = (thread.get("comments") or {}).get("nodes") or []
        if not nodes:
            continue
        author = ((nodes[0].get("author") or {}).get("login")) or ""
        # Only resolve our own threads, never a human reviewer's.
        if not author.endswith("[bot]"):
            continue
        candidates.append(
            {
                "id": thread.get("id"),
                "path": thread.get("path"),
                "outdated": bool(thread.get("isOutdated")),
                "body": " ".join((nodes[0].get("body") or "").split())[:600],
            }
        )

    if not candidates:
        log("No unresolved bot review threads to consider.")
        return 0

    log(f"Judging {len(candidates)} unresolved thread(s)...")
    listing = "\n".join(
        f"- id: {c['id']}\n  path: {c['path']}\n  outdated: {c['outdated']}\n"
        f"  comment: {c['body']}"
        for c in candidates
    )
    context = "## Unresolved threads\n\n" + listing
    if push_files is not None:
        context += "\n\n## Changes in the latest push\n\n" + build_diff_text(
            pr, push_files
        )
    if conversation:
        context += "\n\n## Discussion so far\n\n" + conversation
    messages = [
        {"role": "system", "content": RESOLVE_DECIDER_PROMPT},
        {"role": "user", "content": context},
    ]
    try:
        raw = ai.chat(messages, temperature=0.0)
    except Exception as exc:  # noqa: BLE001
        log(f"Warning: thread-resolution decision failed: {exc}")
        return 0

    data = _first_json_object(raw or "")
    if not data or not isinstance(data.get("resolved"), list):
        log("Thread-resolution decision returned no usable JSON; resolving nothing.")
        return 0

    wanted = {str(x) for x in data["resolved"]}
    known = {str(c["id"]) for c in candidates}
    resolved = 0
    for c in candidates:
        if str(c["id"]) not in wanted or str(c["id"]) not in known:
            continue
        try:
            gh.resolve_review_thread(c["id"])
            resolved += 1
            log(f"Resolved thread on {c['path']}.")
        except Exception as exc:  # noqa: BLE001 - one failure shouldn't stop the rest
            log(f"Warning: failed to resolve thread on {c['path']}: {exc}")
    log(f"Resolved {resolved}/{len(candidates)} thread(s).")
    return resolved


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


def handle_review_request(
    ai: AIClient,
    gh: GitHubClient,
    pr: Dict[str, Any],
    body: str,
    author: str,
    owner: str,
    repo: str,
    number: int,
    config: Config,
    system_prompt: str,
    conversation: str,
    bot_login: str,
) -> int:
    """Run a full review when the user explicitly asks for one via @-mention."""
    files = gh.list_files(owner, repo, number)
    if not files:
        gh.post_comment(owner, repo, number, f"@{author} 没有找到变更文件，无法评审。")
        return 0

    log(f"Review requested via @-mention ({len(files)} files, ~{len(conversation)} chars context)...")
    review_text, raw_comments, _general = perform_review(
        ai, system_prompt, pr, files, config.max_tokens_per_chunk, conversation
    )
    if not review_text:
        log("Error: perform_review returned empty — model may have hit a limit or returned no content.")
        gh.post_comment(owner, repo, number, f"@{author} 评审失败，AI 返回了空内容。请稍后重试。")
        return 0

    inline = normalize_inline_comments(raw_comments, files)
    event = determine_event(review_text)

    if config.dry_run:
        print(review_text)
        return 0

    try:
        result = gh.post_review(
            owner, repo, number, review_text, event=event, comments=inline
        )
    except Exception as exc:
        log(f"Warning: posting review with inline comments failed ({exc}); retrying.")
        result = gh.post_review(owner, repo, number, review_text, event=event)
        post_inline_comments(
            gh, owner, repo, number, pr.get("head", {}).get("sha", ""), inline
        )

    posted_login = (result.get("user") or {}).get("login", "") or bot_login

    entries = merge_conversation(
        history.load(owner, repo, number),
        fetch_conversation(gh, owner, repo, number),
    )
    entries.append(
        {
            "ts": datetime.now(timezone.utc).isoformat(),
            "who": posted_login,
            "kind": "review",
            "body": review_text,
        }
    )
    history.save(owner, repo, number, entries[-MAX_CONVERSATION_ENTRIES:])

    gh.post_comment(owner, repo, number, f"@{author} 评审已发布。")
    log(f"Review posted on request ({event}).")
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


def main() -> int:
    config = load_config()
    system_prompt = build_system_prompt(config.prompt, config.language)
    reply_prompt = build_system_prompt(REPLY_SYSTEM_PROMPT, config.language)

    event_name, payload = load_event()

    # Comments reach us as `issue_comment` (the PR conversation) or as
    # `pull_request_review_comment` (an inline review-comment thread). GitHub
    # exposes no threading for the former, so an @-mention is the trigger in
    # both cases.
    is_issue_comment = event_name == "issue_comment"
    is_review_comment = event_name == "pull_request_review_comment"
    comment: Dict[str, Any] = {}
    if is_issue_comment or is_review_comment:
        comment = payload.get("comment") or {}
        if is_issue_comment:
            issue = payload.get("issue") or {}
            if not issue.get("pull_request"):
                log("Ignoring comment on a non-pull-request issue.")
                return 0
        author = (comment.get("user") or {}).get("login", "")
        if author.endswith("[bot]"):
            log("Ignoring comment from a bot (prevents reply loops).")
            return 0

    owner, repo, number = resolve_pull_request(event_name, payload)

    gh = GitHubClient(config.github_token)
    ai = AIClient(
        config.openai_token,
        model=config.model,
        base_url=config.base_url,
        fallback_model=config.fallback_model,
    )

    log(f"ai-review {VERSION}")
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

    # Merges from release branches back to master/main don't need review.
    head_ref = pr.get("head", {}).get("ref", "")
    base_ref = pr.get("base", {}).get("ref", "")
    if head_ref.startswith("release/") and base_ref in ("master", "main"):
        log(f"Skipping review: merge from {head_ref} to {base_ref}.")
        return 0

    stored = history.load(owner, repo, number)
    fresh = fetch_conversation(gh, owner, repo, number)

    # Reply mode.
    if is_issue_comment or is_review_comment:
        body = comment.get("body") or ""
        # Determine bot login from the conversation (bot-authored entries),
        # with an env-var fallback for the first run when no history exists yet.
        bot_login = "perotoolsbot[bot]"
        addressed = comment_mentions_bot(body, bot_login)
        thread_context = ""
        if is_review_comment:
            # An inline reply inside one of our own threads is already aimed at
            # us — review comments are the one place GitHub exposes the thread
            # relationship, so no @-mention is needed there. The parent comment
            # is also the thing the developer is asking about, so hand it to the
            # model explicitly instead of making it dig through the transcript.
            parent_id = comment.get("in_reply_to_id")
            if parent_id:
                try:
                    parent = gh.get_review_comment(owner, repo, parent_id)
                    parent_author = (parent.get("user") or {}).get("login", "")
                    addressed = addressed or parent_author.endswith("[bot]")
                    if not addressed and comment.get("id"):
                        # The parent may be another human comment in a thread the
                        # bot is part of — the thread as a whole is what counts.
                        addressed = thread_has_bot_comment(
                            gh, owner, repo, number, comment["id"]
                        )
                    parent_body = (parent.get("body") or "").strip()
                    if parent_body:
                        where = parent.get("path") or ""
                        line = parent.get("line") or parent.get("original_line")
                        location = f" ({where}:{line})" if where and line else ""
                        thread_context = f"{parent_author}{location}:\n\n{parent_body}"
                except Exception as exc:  # noqa: BLE001 - fall back to the mention check
                    log(f"Warning: could not look up the parent review comment: {exc}")
        if not addressed:
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
        if intent == "improve_prompt":
            return handle_improve_prompt(
                ai, gh, body, author, owner, repo, number, bot_login
            )
        if intent == "code_change":
            return handle_code_change(
                ai, gh, pr, body, author, owner, repo, number, conversation, bot_login
            )
        if intent == "review":
            return handle_review_request(
                ai, gh, pr, body, author, owner, repo, number, config, system_prompt, conversation, bot_login
            )

        try:
            reply = generate_reply(
                ai, reply_prompt, conversation, author, body, thread_context
            )
        except Exception as exc:  # noqa: BLE001 - report instead of going silent
            log(f"Error: reply generation failed: {exc}")
            reply = ""
        if not reply:
            log("Error: no reply was produced (empty content or a failed call).")
            if not config.dry_run:
                gh.post_comment(
                    owner, repo, number,
                    f"⚠️ @{author} 生成回复失败（模型返回空内容或调用出错），请查看 workflow 日志。",
                )
            return 1

        if config.dry_run:
            print(reply)
            return 0

        if is_review_comment and comment.get("id"):
            # Answer inside the inline thread the user wrote in.
            result = gh.post_review_comment_reply(
                owner, repo, number, comment["id"], reply
            )
            log("Posted reply in the review-comment thread.")
        else:
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

        # A concern answered in the thread is settled even without a code change,
        # so re-check the open threads and approve once nothing is left.
        if not config.dry_run:
            settle_threads_and_approve(
                ai, gh, owner, repo, number, pr, [], conversation=conversation
            )
        return 0

    # Review mode.
    # The PR's first pass gets the full structured review. Later pushes only
    # get a light incremental pass: a short plain summary plus inline comments.
    incremental = (
        event_name in ("pull_request", "pull_request_target")
        and payload.get("action") == "synchronize"
        and any((e.get("who") or "").endswith("[bot]") for e in fresh)
    )
    review_prompt = system_prompt + INCREMENTAL_DIRECTIVE if incremental else system_prompt
    if incremental:
        log("Later push detected: running an incremental (unstructured) review.")

    files = gh.list_files(owner, repo, number)
    log(f"Changed files: {len(files)}")

    if not files:
        log("No changed files found; nothing to review.")
        return 0

    entries = merge_conversation(stored, fresh)
    conversation = render_conversation(entries)
    if conversation:
        log(f"Using {len(entries)} prior review/comment entry(ies) as context.")

    review_text, raw_comments, general = perform_review(
        ai, review_prompt, pr, files, config.max_tokens_per_chunk, conversation
    )
    if not review_text:
        log("Error: the AI returned an empty review.")
        return 1

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
        # A regular comment cannot carry inline comments, so post them one by one.
        post_inline_comments(
            gh, owner, repo, number, pr.get("head", {}).get("sha", ""), inline
        )
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
            post_inline_comments(
                gh, owner, repo, number, pr.get("head", {}).get("sha", ""), inline
            )

    # On a later push, retire the threads that push settled, then approve when
    # the review came back clean and nothing is left open.
    if incremental:
        push_files: Optional[List[Dict[str, Any]]] = None
        before, after = payload.get("before"), payload.get("after")
        if before and after:
            try:
                push_files = gh.compare(owner, repo, before, after)
                log(f"Latest push touched {len(push_files)} file(s).")
            except Exception as exc:  # noqa: BLE001 - fall back to the discussion
                log(f"Warning: could not diff the push ({before[:7]}..{after[:7]}): {exc}")
        settle_threads_and_approve(
            ai, gh, owner, repo, number, pr, files,
            conversation=conversation,
            push_files=push_files,
            allow_approve=(event == "APPROVE"),
        )

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
