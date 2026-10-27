"""GitHub REST API client used by the AI code review tool."""

from __future__ import annotations

import base64
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

import requests


def log(message: str) -> None:
    print(message, file=sys.stderr)

# Review-thread resolution is GraphQL-only — the REST API cannot do it.
REVIEW_THREADS_QUERY = """
query($owner: String!, $name: String!, $number: Int!, $cursor: String) {
  repository(owner: $owner, name: $name) {
    pullRequest(number: $number) {
      reviewThreads(first: 50, after: $cursor) {
        pageInfo { hasNextPage endCursor }
        nodes {
          id
          isResolved
          isOutdated
          path
          comments(first: 50) {
            nodes { databaseId body author { login __typename } }
          }
        }
      }
    }
  }
}
"""

RESOLVE_THREAD_MUTATION = """
mutation($threadId: ID!) {
  resolveReviewThread(input: {threadId: $threadId}) {
    thread { id isResolved }
  }
}
"""

# One thread's current state, asked immediately before it is resolved: another
# run of the same pull request may have resolved it since this one listed the
# threads, and resolving it twice means telling the author twice.
THREAD_STATE_QUERY = """
query($threadId: ID!) {
  node(id: $threadId) {
    ... on PullRequestReviewThread { isResolved }
  }
}
"""


class GitHubClient:
    """Minimal GitHub REST API client for pull request reviews."""

    def __init__(
        self,
        token: str,
        api_url: str = "https://api.github.com",
        max_retries: int = 4,
        timeout: int = 60,
    ) -> None:
        self.api_url = api_url.rstrip("/")
        self.max_retries = max_retries
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            }
        )

    def _send(self, method: str, url: str, **kwargs: Any) -> requests.Response:
        """HTTP request with retry on transient network errors and 5xx/429.

        GitHub occasionally drops the connection (``RemoteDisconnected``) or
        rate-limits; a single blip must not abort the whole review.
        """
        kwargs.setdefault("timeout", self.timeout)
        last_error: Optional[Exception] = None
        for attempt in range(self.max_retries + 1):
            try:
                resp = self.session.request(method, url, **kwargs)
            except (requests.ConnectionError, requests.Timeout) as exc:
                last_error = exc
                if attempt < self.max_retries:
                    delay = min(2 ** attempt, 10)
                    time.sleep(delay)
                    continue
                raise
            if resp.status_code in (429, 500, 502, 503, 504) and attempt < self.max_retries:
                time.sleep(min(2 ** attempt, 10))
                continue
            return resp
        # Only reached if the loop exhausted retries on exceptions.
        raise last_error if last_error else RuntimeError("request failed")

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        resp = self._send(method, f"{self.api_url}{path}", **kwargs)
        if resp.status_code >= 400:
            detail = ""
            try:
                detail = resp.json().get("message", "")
            except ValueError:
                detail = resp.text
            raise RuntimeError(
                f"GitHub API error ({resp.status_code}) {method} {path}: {detail}"
            )
        return resp.json()

    def graphql(
        self, query: str, variables: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Run a GraphQL query/mutation (review threads need GraphQL)."""
        resp = self._send(
            "POST",
            f"{self.api_url}/graphql",
            json={"query": query, "variables": variables or {}},
        )
        if resp.status_code >= 400:
            raise RuntimeError(
                f"GitHub GraphQL error ({resp.status_code}): {resp.text[:500]}"
            )
        data = resp.json()
        if data.get("errors"):
            raise RuntimeError(f"GitHub GraphQL error: {data['errors']}")
        return data.get("data") or {}

    def list_review_threads(
        self, owner: str, repo: str, number: int
    ) -> List[Dict[str, Any]]:
        """List the pull request's review threads, resolved ones included."""
        threads: List[Dict[str, Any]] = []
        cursor: Optional[str] = None
        while True:
            data = self.graphql(
                REVIEW_THREADS_QUERY,
                {"owner": owner, "name": repo, "number": number, "cursor": cursor},
            )
            pull = ((data.get("repository") or {}).get("pullRequest")) or {}
            connection = pull.get("reviewThreads") or {}
            threads.extend(connection.get("nodes") or [])
            page = connection.get("pageInfo") or {}
            if not page.get("hasNextPage"):
                break
            cursor = page.get("endCursor")
        return threads

    def resolve_review_thread(self, thread_id: str) -> Dict[str, Any]:
        """Mark a review thread as resolved."""
        return self.graphql(RESOLVE_THREAD_MUTATION, {"threadId": thread_id})

    def thread_is_resolved(self, thread_id: str) -> Optional[bool]:
        """Whether the thread is resolved *now*, or None when that cannot be told.

        Asked right before resolving, because runs of the same pull request can
        overlap: each lists the threads, each finds the same ones unresolved, and
        the author otherwise gets one "why this is resolved" note per run.
        """
        try:
            data = self.graphql(THREAD_STATE_QUERY, {"threadId": thread_id})
        except Exception:  # noqa: BLE001 - the caller simply resolves as before
            return None
        node = data.get("node") or {}
        value = node.get("isResolved")
        return value if isinstance(value, bool) else None

    def get_pull_request(self, owner: str, repo: str, number: int) -> Dict[str, Any]:
        """Fetch metadata for a single pull request.

        A 404 is retried once. It happens for a token that can plainly read the
        repository — RhythmAce-Neo #36 answered 200 for this call in one stage and
        404 for the same call five seconds later in the next — and that is not worth
        failing a run over. When it persists, the error says what the usual cause is:
        "Not Found" for a pull request that is visibly open reads like the pipeline's
        own bug, and the answer (the App installation is missing the repository) is
        also what breaks the clone.
        """
        path = f"/repos/{owner}/{repo}/pulls/{number}"
        try:
            return self._request("GET", path)
        except RuntimeError as exc:
            if "(404)" not in str(exc):
                raise
            time.sleep(1)
        try:
            return self._request("GET", path)
        except RuntimeError as exc:
            if "(404)" not in str(exc):
                raise
            raise RuntimeError(
                f"{str(exc).strip()} — and again after a retry. A 404 here for a pull "
                "request that exists usually means the GitHub App's installation does "
                "not include this repository: the API can still answer for a repository "
                "the git side refuses, and that is also what makes the clone say "
                "'Repository not found'. Check the App's repository access."
            ) from exc

    def list_files(self, owner: str, repo: str, number: int) -> List[Dict[str, Any]]:
        """List the files changed by a pull request (paginated)."""
        files: List[Dict[str, Any]] = []
        page = 1
        while True:
            data = self._request(
                "GET",
                f"/repos/{owner}/{repo}/pulls/{number}/files",
                params={"per_page": 100, "page": page},
            )
            if not data:
                break
            files.extend(data)
            if len(data) < 100:
                break
            page += 1
        return files

    def list_comments(self, owner: str, repo: str, number: int) -> List[Dict[str, Any]]:
        """List issue comments on a pull request (the conversation thread)."""
        comments: List[Dict[str, Any]] = []
        page = 1
        while True:
            data = self._request(
                "GET",
                f"/repos/{owner}/{repo}/issues/{number}/comments",
                params={"per_page": 100, "page": page},
            )
            if not data:
                break
            comments.extend(data)
            if len(data) < 100:
                break
            page += 1
        return comments

    def list_review_comments(
        self, owner: str, repo: str, number: int
    ) -> List[Dict[str, Any]]:
        """List inline review comments (the ones attached to diff lines)."""
        comments: List[Dict[str, Any]] = []
        page = 1
        while True:
            data = self._request(
                "GET",
                f"/repos/{owner}/{repo}/pulls/{number}/comments",
                params={"per_page": 100, "page": page},
            )
            if not data:
                break
            comments.extend(data)
            if len(data) < 100:
                break
            page += 1
        return comments

    def list_reviews(self, owner: str, repo: str, number: int) -> List[Dict[str, Any]]:
        """List pull request reviews (with bodies and submitter)."""
        reviews: List[Dict[str, Any]] = []
        page = 1
        while True:
            data = self._request(
                "GET",
                f"/repos/{owner}/{repo}/pulls/{number}/reviews",
                params={"per_page": 100, "page": page},
            )
            if not data:
                break
            reviews.extend(data)
            if len(data) < 100:
                break
            page += 1
        return reviews

    def post_review(
        self,
        owner: str,
        repo: str,
        number: int,
        body: str,
        event: str = "COMMENT",
        comments: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """Post a pull request review (APPROVE / REQUEST_CHANGES / COMMENT).

        ``comments`` is an optional list of inline review comments, each shaped
        like ``{"path", "line", "side", "body", "start_line", "start_side"}``.
        """
        payload: Dict[str, Any] = {"body": body, "event": event}
        if comments:
            payload["comments"] = comments
        return self._request(
            "POST",
            f"/repos/{owner}/{repo}/pulls/{number}/reviews",
            json=payload,
        )

    def post_review_comment(
        self,
        owner: str,
        repo: str,
        number: int,
        commit_id: str,
        comment: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Post a single inline review comment (no review state attached)."""
        payload = {"commit_id": commit_id, **comment}
        return self._request(
            "POST", f"/repos/{owner}/{repo}/pulls/{number}/comments", json=payload
        )

    def compare(
        self, owner: str, repo: str, base: str, head: str
    ) -> List[Dict[str, Any]]:
        """List the files changed between two commits (i.e. one push)."""
        files: List[Dict[str, Any]] = []
        page = 1
        while True:
            data = self._request(
                "GET",
                f"/repos/{owner}/{repo}/compare/{base}...{head}",
                params={"per_page": 100, "page": page},
            )
            chunk = (data or {}).get("files") or []
            files.extend(chunk)
            if len(chunk) < 100:
                break
            page += 1
        return files

    def get_review_comment(
        self, owner: str, repo: str, comment_id: int
    ) -> Dict[str, Any]:
        """Fetch a single inline review comment."""
        return self._request(
            "GET", f"/repos/{owner}/{repo}/pulls/comments/{comment_id}"
        )

    def post_review_comment_reply(
        self, owner: str, repo: str, number: int, comment_id: int, body: str
    ) -> Dict[str, Any]:
        """Reply inside an existing inline review-comment thread."""
        return self._request(
            "POST",
            f"/repos/{owner}/{repo}/pulls/{number}/comments/{comment_id}/replies",
            json={"body": body},
        )

    def post_comment(self, owner: str, repo: str, number: int, body: str) -> Dict[str, Any]:
        """Post a regular issue comment (used in silent mode)."""
        return self._request(
            "POST",
            f"/repos/{owner}/{repo}/issues/{number}/comments",
            json={"body": body},
        )

    def update_comment(
        self, owner: str, repo: str, comment_id: Any, body: str
    ) -> Optional[Dict[str, Any]]:
        """Edit one issue comment, or None when it cannot be edited.

        Used to put the artifact's own download URL into a comment that was
        posted before the upload happened. Every failure is a warning: the
        comment exists and already points somewhere useful, so a refused edit
        must not fail the run that has just finished the work it describes.
        """
        if not comment_id:
            return None
        try:
            return self._request(
                "PATCH",
                f"/repos/{owner}/{repo}/issues/comments/{comment_id}",
                json={"body": body},
            )
        except Exception as exc:  # noqa: BLE001 - a stale link is not fatal
            log(f"Warning: could not edit comment {comment_id}: {exc}")
            return None

    def create_check_run(
        self,
        owner: str,
        repo: str,
        head_sha: str,
        name: str,
        conclusion: str,
        title: str,
        summary: str,
    ) -> Optional[Dict[str, Any]]:
        """Publish a check run for this commit, or None when it is not allowed.

        The red cross (or green tick) on the pull request comes from here. It
        needs the App to hold ``checks: write``; without it GitHub answers 403 and
        the review carries on — the check run is a summary of work already
        reported in the comment, never the only place the result appears.
        """
        if not head_sha:
            return None
        payload = {
            "name": name,
            "head_sha": head_sha,
            "status": "completed",
            "conclusion": conclusion,
            "output": {"title": title[:255], "summary": summary[:60000]},
        }
        try:
            return self._request(
                "POST", f"/repos/{owner}/{repo}/check-runs", json=payload
            )
        except RuntimeError as exc:
            if "403" in str(exc) or "404" in str(exc):
                log(
                    "GitHub refused the check run — the App needs the 'Checks: write' "
                    "permission for it; the comment still carries the result."
                )
            else:
                log(f"Could not publish the check run: {exc}")
            return None

    def add_labels(self, owner: str, repo: str, number: int, labels: List[str]) -> Any:
        """Add labels to a pull request."""
        return self._request(
            "POST",
            f"/repos/{owner}/{repo}/issues/{number}/labels",
            json={"labels": labels},
        )

    def create_branch(
        self, owner: str, repo: str, branch_name: str, base_branch: str = "main"
    ) -> Dict[str, Any]:
        """Create a new branch from the given base branch (default main)."""
        ref = self._request(
            "GET", f"/repos/{owner}/{repo}/git/ref/heads/{base_branch}"
        )
        sha = ref["object"]["sha"]
        return self._request(
            "POST",
            f"/repos/{owner}/{repo}/git/refs",
            json={"ref": f"refs/heads/{branch_name}", "sha": sha},
        )

    def get_file_content(
        self, owner: str, repo: str, path: str, ref: Optional[str] = None
    ) -> str:
        """Read a file's content from the repository (base64-decoded)."""
        params: Dict[str, Any] = {}
        if ref:
            params["ref"] = ref
        data = self._request(
            "GET", f"/repos/{owner}/{repo}/contents/{path}", params=params
        )
        return base64.b64decode(data.get("content", "")).decode("utf-8")

    def get_file_content_optional(
        self, owner: str, repo: str, path: str, ref: Optional[str] = None
    ) -> Optional[Tuple[str, str]]:
        """Read a file's content, returning ``(content, blob_sha)`` or ``None``.

        Unlike :meth:`get_file_content` this never raises. Callers use the result
        to *enrich* a run, so a file that cannot be read has to degrade to their
        default rather than abort. ``None`` covers every way ``path`` can fail to
        be readable text: missing (404), a directory (the contents API answers
        with a JSON array), too large for the API (``encoding`` other than
        ``base64``, with an empty ``content``) and bytes that are not UTF-8.
        """
        params: Dict[str, Any] = {}
        if ref:
            params["ref"] = ref
        try:
            data = self._request(
                "GET", f"/repos/{owner}/{repo}/contents/{path}", params=params
            )
            if not isinstance(data, dict):
                return None
            if data.get("encoding") != "base64":
                return None
            # The API wraps base64 in newlines; b64decode only tolerates those
            # with validation off, so drop them rather than depend on that.
            raw = "".join((data.get("content") or "").split())
            return base64.b64decode(raw).decode("utf-8"), data.get("sha", "")
        except Exception:  # noqa: BLE001 - callers have a default to fall back to
            return None

    def path_exists(
        self, owner: str, repo: str, path: str, ref: Optional[str] = None
    ) -> Optional[bool]:
        """Does ``path`` exist at ``ref``? ``None`` when the answer is not available.

        The contents API answers 404 for a missing path and 200 for anything it can
        list, a binary or oversized file included — which is the distinction a
        thread decider needs: "this file was removed" must not be confused with "I
        could not read it as text", or a thread asking for a removal is told the
        file is still there when it is not.
        """
        params: Dict[str, Any] = {}
        if ref:
            params["ref"] = ref
        try:
            self._request("GET", f"/repos/{owner}/{repo}/contents/{path}", params=params)
            return True
        except RuntimeError as exc:
            if "GitHub API error (404)" in str(exc):
                return False
            log(f"Warning: could not check whether {path} exists: {exc}")
            return None
        except Exception as exc:  # noqa: BLE001 - the caller says "unknown"
            log(f"Warning: could not check whether {path} exists: {exc}")
            return None

    def put_file(
        self,
        owner: str,
        repo: str,
        path: str,
        content: str,
        branch: str,
        message: str,
    ) -> Dict[str, Any]:
        """Create or update a file on a branch (auto-handles the blob SHA)."""
        sha = None
        try:
            existing = self._request(
                "GET", f"/repos/{owner}/{repo}/contents/{path}?ref={branch}"
            )
            sha = existing.get("sha")
        except Exception:
            pass
        payload: Dict[str, Any] = {
            "message": message,
            "content": base64.b64encode(content.encode("utf-8")).decode("ascii"),
            "branch": branch,
        }
        if sha:
            payload["sha"] = sha
        return self._request(
            "PUT", f"/repos/{owner}/{repo}/contents/{path}", json=payload
        )

    def create_pr(
        self,
        owner: str,
        repo: str,
        title: str,
        head: str,
        base: str,
        body: str = "",
    ) -> Dict[str, Any]:
        """Create a pull request."""
        return self._request(
            "POST",
            f"/repos/{owner}/{repo}/pulls",
            json={"title": title, "head": head, "base": base, "body": body},
        )