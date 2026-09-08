"""GitHub REST API client used by the AI code review tool."""

from __future__ import annotations

import base64
from typing import Any, Dict, List, Optional

import requests


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

    def create_branch(self, owner: str, repo: str, branch_name: str) -> Dict[str, Any]:
        """Create a new branch from the current main HEAD."""
        ref = self._request("GET", f"/repos/{owner}/{repo}/git/ref/heads/main")
        sha = ref["object"]["sha"]
        return self._request(
            "POST",
            f"/repos/{owner}/{repo}/git/refs",
            json={"ref": f"refs/heads/{branch_name}", "sha": sha},
        )

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