"""GitHub REST API client used by the AI code review tool."""

from __future__ import annotations

import base64
from typing import Any, Dict, List, Optional

import requests

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


class GitHubClient:
    """Minimal GitHub REST API client for pull request reviews."""

    def __init__(self, token: str, api_url: str = "https://api.github.com") -> None:
        self.api_url = api_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            }
        )

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        resp = self.session.request(method, f"{self.api_url}{path}", **kwargs)
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
        resp = self.session.post(
            f"{self.api_url}/graphql",
            json={"query": query, "variables": variables or {}},
            timeout=60,
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

    def get_pull_request(self, owner: str, repo: str, number: int) -> Dict[str, Any]:
        """Fetch metadata for a single pull request."""
        return self._request("GET", f"/repos/{owner}/{repo}/pulls/{number}")

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