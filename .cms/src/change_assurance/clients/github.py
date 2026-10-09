"""GitHub API client used to read pull request commits."""

from __future__ import annotations

import json
import re
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urljoin, urlparse
from urllib.request import Request, urlopen

from ..models.action import ActionSettings, PullRequest, ValidationFailure


NEXT_PAGE_LINK = re.compile(r'<([^>]+)>;\s*rel="next"')


class GitHubClient:
    """Read PR commit metadata from the GitHub REST API.

    Parameters
    ----------
    settings : ActionSettings
        Settings containing the GitHub API URL and workflow token.
    """

    def __init__(self, settings: ActionSettings) -> None:
        self.api_url = settings.require("GITHUB_API_URL").rstrip("/") + "/"
        self.token = settings.require("GITHUB_TOKEN")
        self.expected_host = urlparse(self.api_url).netloc

    def get_pull_request(self, repository: str, number: int) -> dict[str, Any]:
        """Fetch pull request metadata from the GitHub REST API.

        Parameters
        ----------
        repository : str
            Repository name in ``owner/name`` form.
        number : int
            Pull request number.

        Returns
        -------
        dict[str, Any]
            GitHub pull request object.

        Raises
        ------
        ValidationFailure
            If the API request fails or returns an invalid response.
        """
        url = urljoin(self.api_url, f"repos/{repository}/pulls/{number}")
        payload, _ = self._get_json(url, subject="pull request")
        if not isinstance(payload, dict):
            raise ValidationFailure(
                "GITHUB_RESPONSE_INVALID",
                "GitHub returned invalid pull request metadata.",
                result="ERROR",
            )
        return payload

    def get_pull_request_commits(self, pr: PullRequest) -> list[dict[str, Any]]:
        """Fetch all commit records associated with a pull request.

        Parameters
        ----------
        pr : PullRequest
            Pull request whose commits should be retrieved.

        Returns
        -------
        list of dict[str, Any]
            GitHub commit API records, including messages and parent SHAs.

        Raises
        ------
        ValidationFailure
            If GitHub returns an error, malformed response, or unsafe page link.
        """
        url = urljoin(
            self.api_url,
            f"repos/{pr.repository}/pulls/{pr.number}/commits?per_page=100",
        )
        commits: list[dict[str, Any]] = []
        while url:
            if urlparse(url).netloc != self.expected_host:
                raise ValidationFailure(
                    "GITHUB_PAGINATION_INVALID",
                    "GitHub returned an unexpected pagination host.",
                    result="ERROR",
                )
            payload, headers = self._get_json(url, subject="pull request commits")
            if not isinstance(payload, list):
                raise ValidationFailure(
                    "GITHUB_RESPONSE_INVALID",
                    "GitHub returned an invalid PR commits response.",
                    result="ERROR",
                )
            commits.extend(item for item in payload if isinstance(item, dict))
            next_page = NEXT_PAGE_LINK.search(headers.get("Link", ""))
            url = next_page.group(1) if next_page else ""
        return commits

    def get_releases(self, repository: str) -> list[dict[str, Any]]:
        """List published releases, following GitHub pagination."""
        url = urljoin(self.api_url, f"repos/{repository}/releases?per_page=100")
        releases: list[dict[str, Any]] = []
        while url:
            if urlparse(url).netloc != self.expected_host:
                raise ValidationFailure(
                    "GITHUB_PAGINATION_INVALID",
                    "GitHub returned an unexpected pagination host.",
                    result="ERROR",
                )
            payload, headers = self._get_json(url, subject="repository releases")
            if not isinstance(payload, list):
                raise ValidationFailure(
                    "GITHUB_RESPONSE_INVALID",
                    "GitHub returned an invalid releases response.",
                    result="ERROR",
                )
            releases.extend(item for item in payload if isinstance(item, dict))
            next_page = NEXT_PAGE_LINK.search(headers.get("Link", ""))
            url = next_page.group(1) if next_page else ""
        return releases

    def compare_commits(
        self, repository: str, base: str, head: str
    ) -> list[dict[str, Any]]:
        """Return commits between two Git refs using GitHub's compare API."""
        url = urljoin(
            self.api_url,
            f"repos/{repository}/compare/{quote(base, safe='')}...{quote(head, safe='')}?per_page=100",
        )
        commits: list[dict[str, Any]] = []
        while url:
            if urlparse(url).netloc != self.expected_host:
                raise ValidationFailure(
                    "GITHUB_PAGINATION_INVALID",
                    "GitHub returned an unexpected pagination host.",
                    result="ERROR",
                )
            payload, headers = self._get_json(url, subject="release commit range")
            if not isinstance(payload, dict) or not isinstance(payload.get("commits"), list):
                raise ValidationFailure(
                    "GITHUB_RESPONSE_INVALID",
                    "GitHub returned an invalid commit comparison.",
                    result="ERROR",
                )
            if payload.get("status") != "ahead":
                raise ValidationFailure(
                    "RELEASE_RANGE_INVALID",
                    "The release tag must be ahead of and descend from its baseline release tag.",
                )
            commits.extend(item for item in payload["commits"] if isinstance(item, dict))
            next_page = NEXT_PAGE_LINK.search(headers.get("Link", ""))
            url = next_page.group(1) if next_page else ""
        return commits

    def get_ref_commit(self, repository: str, ref: str) -> str:
        """Resolve a branch or tag name to its commit SHA."""
        url = urljoin(self.api_url, f"repos/{repository}/commits/{quote(ref, safe='')}")
        payload, _ = self._get_json(url, subject="release commit")
        sha = payload.get("sha") if isinstance(payload, dict) else None
        if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-fA-F]{40,64}", sha):
            raise ValidationFailure(
                "RELEASE_COMMIT_INVALID",
                "GitHub did not resolve the release tag to a valid commit SHA.",
            )
        return sha

    def _get_json(
        self, url: str, *, subject: str = "pull request data"
    ) -> tuple[Any, Any]:
        """Request one GitHub API page and decode its JSON response.

        Parameters
        ----------
        url : str
            Absolute GitHub API URL on the configured API host.

        Returns
        -------
        tuple
            Decoded JSON response and response headers.

        Raises
        ------
        ValidationFailure
            If the API denies the request, returns an HTTP error, or is
            unreachable.
        """
        request = Request(
            url,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self.token}",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "change-assurance-accelerator",
            },
        )
        try:
            with urlopen(request, timeout=20) as response:
                payload = json.loads(response.read().decode("utf-8"))
                return payload, response.headers
        except HTTPError as exc:
            code = "GITHUB_API_FORBIDDEN" if exc.code in {401, 403} else "GITHUB_API_ERROR"
            raise ValidationFailure(
                code,
                f"GitHub API returned HTTP {exc.code} while reading {subject}.",
                result="ERROR",
            ) from exc
        except (URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise ValidationFailure(
                "GITHUB_API_UNAVAILABLE",
                "Could not complete the GitHub API request.",
                result="ERROR",
            ) from exc
