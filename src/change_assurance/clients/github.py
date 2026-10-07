"""GitHub API client used to read pull request commits."""

from __future__ import annotations

import json
import re
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
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
            payload, headers = self._get_json(url)
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

    def _get_json(self, url: str) -> tuple[Any, Any]:
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
                f"GitHub API returned HTTP {exc.code} while reading PR commits.",
                result="ERROR",
            ) from exc
        except (URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise ValidationFailure(
                "GITHUB_API_UNAVAILABLE",
                "Could not retrieve commits from GitHub.",
                result="ERROR",
            ) from exc
