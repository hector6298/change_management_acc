"""Shared settings and data records for the GitHub change assurance Action."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import fnmatch
import os
from typing import Any, Optional


class ValidationFailure(Exception):
    """Represent a validation failure or an unavailable dependency.

    Parameters
    ----------
    code : str
        Stable machine-readable reason code.
    message : str
        Human-readable explanation for the workflow summary.
    result : str, default="FAILURE"
        Evidence outcome. Use ``ERROR`` when validation could not complete.
    details : dict[str, Any] or None, default=None
        Optional Jira snapshot to preserve when a returned issue fails policy.
    """

    def __init__(
        self,
        code: str,
        message: str,
        *,
        result: str = "FAILURE",
        details: Optional[dict[str, Any]] = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.result = result
        self.details = details


@dataclass(frozen=True)
class ActionSettings:
    """Read Action configuration and provide validated environment values.

    Parameters
    ----------
    values : dict[str, str]
        Environment variables captured when the Action starts.
    """

    values: dict[str, str] = field(default_factory=lambda: dict(os.environ))

    def get(self, name: str, default: str = "") -> str:
        """Return one trimmed setting, or its default when unset.

        Parameters
        ----------
        name : str
            Environment variable name.
        default : str, default=""
            Value used when the variable is missing or blank.

        Returns
        -------
        str
            Trimmed setting value.
        """
        return self.values.get(name, default).strip() or default

    def require(self, name: str) -> str:
        """Return a required setting or raise a configuration error.

        Parameters
        ----------
        name : str
            Required environment variable name.

        Returns
        -------
        str
            Non-empty setting value.

        Raises
        ------
        ValidationFailure
            If the setting is missing or blank.
        """
        value = self.get(name)
        if not value:
            raise ValidationFailure(
                "CONFIG_MISSING",
                f"Required configuration is missing: {name}",
                result="ERROR",
            )
        return value

    def production_branches(self) -> list[str]:
        """Return branch patterns requiring Jira approval.

        Returns
        -------
        list of str
            Patterns from the comma-separated ``PRODUCTION_BRANCHES`` value.
            Defaults to ``main``.
        """
        value = self.get("PRODUCTION_BRANCHES", "main")
        return [pattern.strip() for pattern in value.split(",") if pattern.strip()]


@dataclass(frozen=True)
class PullRequest:
    """Normalized pull request event fields used by the Action.

    Parameters
    ----------
    number : int
        Pull request number.
    repository : str
        Base repository in ``owner/name`` form.
    url : str or None
        Browser URL for the pull request.
    title : str
        Pull request title.
    body : str
        Pull request description.
    branch : str
        Source branch name.
    base_branch : str
        Target branch name.
    head_sha : str
        Current source commit SHA.
    """

    number: int
    repository: str
    url: Optional[str]
    title: str
    body: str
    branch: str
    base_branch: str
    head_sha: str

    @classmethod
    def from_event(cls, event: dict[str, Any], repository: str) -> "PullRequest":
        """Create a normalized PR from GitHub's event payload.

        Parameters
        ----------
        event : dict[str, Any]
            Parsed event JSON from ``GITHUB_EVENT_PATH``.
        repository : str
            Repository name from ``GITHUB_REPOSITORY``.

        Returns
        -------
        PullRequest
            Normalized pull request record.

        Raises
        ------
        ValidationFailure
            If the event does not contain a usable pull request.
        """
        data = event.get("pull_request")
        if not isinstance(data, dict):
            raise ValidationFailure(
                "PULL_REQUEST_MISSING",
                "This workflow event does not contain a pull request.",
                result="ERROR",
            )
        base = data.get("base") or {}
        head = data.get("head") or {}
        try:
            number = int(data.get("number") or event.get("number") or 0)
        except (TypeError, ValueError) as exc:
            raise ValidationFailure(
                "PULL_REQUEST_INVALID",
                "GitHub event contains an invalid pull request number.",
                result="ERROR",
            ) from exc
        if not number or not repository:
            raise ValidationFailure(
                "PULL_REQUEST_INVALID",
                "GitHub event is missing the pull request number or repository.",
                result="ERROR",
            )
        return cls(
            number=number,
            repository=repository,
            url=data.get("html_url"),
            title=str(data.get("title") or ""),
            body=str(data.get("body") or ""),
            branch=str(head.get("ref") or ""),
            base_branch=str(base.get("ref") or ""),
            head_sha=str(head.get("sha") or ""),
        )

    def is_production_bound(self, patterns: list[str]) -> bool:
        """Check whether the base branch matches a production pattern.

        Parameters
        ----------
        patterns : list of str
            Branch names or shell-style wildcard patterns.

        Returns
        -------
        bool
            ``True`` when this PR targets a governed production branch.
        """
        return any(fnmatch.fnmatchcase(self.base_branch, item) for item in patterns)

    def to_evidence(self, production_bound: bool) -> dict[str, Any]:
        """Serialize PR metadata for the evidence record.

        Parameters
        ----------
        production_bound : bool
            Whether the target branch is production-bound.

        Returns
        -------
        dict[str, Any]
            JSON-compatible GitHub evidence fields.
        """
        return {
            "repository": self.repository,
            "pull_request": self.number,
            "pull_request_url": self.url,
            "title": self.title,
            "branch": self.branch,
            "base_branch": self.base_branch,
            "head_sha": self.head_sha,
            "is_production_bound": production_bound,
        }


@dataclass
class EvidenceRecord:
    """Accumulate one versioned validation result.

    Parameters
    ----------
    policy_version : str, default="1"
        Version of the configured governance policy.
    validator_version : str, default="1.0"
        Version of the evidence contract.
    """

    policy_version: str = "1"
    validator_version: str = "1.0"
    change_id: Optional[str] = None
    github: Optional[dict[str, Any]] = None
    jira: Optional[dict[str, Any]] = None
    result: str = "ERROR"
    reason_codes: list[dict[str, str]] = field(default_factory=list)
    observed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        """Return the JSON-compatible evidence representation.

        Returns
        -------
        dict[str, Any]
            Record matching ``github-change-validation.schema.json``.
        """
        return {
            "schema_version": "1.0",
            "event_type": "github_change_validation",
            "observed_at": self.observed_at,
            "result": self.result,
            "reason_codes": self.reason_codes,
            "change_id": self.change_id,
            "github": self.github,
            "jira": self.jira,
            "policy_version": self.policy_version,
            "validator_version": self.validator_version,
        }
