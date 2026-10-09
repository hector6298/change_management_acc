"""Change ID and Jira approval policy for production-bound pull requests."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import re
from typing import Any, Optional

from ..clients.jira import JiraClient, bool_value, parse_timestamp, select_value
from ..models.action import ActionSettings, PullRequest, ValidationFailure
from ..models.change_identity import (
    ChangeRequest,
    ChangeRequestContract,
    ContractViolation,
    JiraFieldRule,
)


class ChangeIdPolicy:
    """Enforce one Jira identity across PR metadata and commits."""

    @staticmethod
    def extract(pr: PullRequest) -> str:
        """Extract the canonical Change ID and reject conflicting references.

        Parameters
        ----------
        pr : PullRequest
            Pull request metadata from GitHub.

        Returns
        -------
        str
            Jira issue key consistently present in the PR body, title, and
            source branch.

        Raises
        ------
        ValidationFailure
            If the ID is missing, malformed, duplicated, or conflicting.
        """
        contract = _load_change_request_contract()
        key_pattern = _unanchored_pattern(contract.issue_key_pattern)
        marker_lines = [
            line
            for line in pr.body.splitlines()
            if line.strip().lower().startswith("change-id:")
        ]
        body_line_pattern = re.compile(
            rf"^(?i:Change-ID):\s*({key_pattern})\s*$"
        )
        body_matches = [
            match.group(1)
            for line in pr.body.splitlines()
            if (match := body_line_pattern.fullmatch(line))
        ]
        if len(marker_lines) != 1 or len(body_matches) != 1:
            raise ValidationFailure(
                "CHANGE_ID_BODY_MISSING_OR_DUPLICATE",
                "PR body must contain exactly one line in the form `Change-ID: DEMO-12`.",
            )
        change_id = body_matches[0]
        title_match = re.match(rf"^({key_pattern})(?:\s|:|$)", pr.title)
        branch_match = re.match(rf"^({key_pattern})(?:[-/])", pr.branch)
        title_id = title_match.group(1) if title_match else None
        branch_id = branch_match.group(1) if branch_match else None

        if title_id != change_id:
            raise ValidationFailure(
                "CHANGE_ID_TITLE_MISMATCH",
                "PR title must begin with the same Jira key as the Change-ID body line.",
            )
        if branch_id != change_id:
            raise ValidationFailure(
                "CHANGE_ID_BRANCH_MISMATCH",
                "Source branch must begin with the same Jira key, for example `DEMO-12-add-feature`.",
            )
        token_pattern = re.compile(rf"\b{key_pattern}\b")
        branch_keys = {match.group(0) for match in token_pattern.finditer(pr.branch)}
        if branch_keys != {change_id}:
            raise ValidationFailure(
                "CHANGE_ID_BRANCH_CONFLICT",
                "Source branch contains another Jira issue key; use one Change Request per PR.",
            )
        title_keys = {match.group(0) for match in token_pattern.finditer(pr.title)}
        if title_keys != {change_id}:
            raise ValidationFailure(
                "CHANGE_ID_TITLE_CONFLICT",
                "PR title contains another Jira issue key; use one Change Request per PR.",
            )
        return change_id

    @staticmethod
    def validate_commits(
        commits: list[dict[str, Any]], change_id: str
    ) -> list[str]:
        """Require the canonical ID in every non-merge commit message.

        Parameters
        ----------
        commits : list of dict[str, Any]
            Commit records returned by GitHub.
        change_id : str
            Jira issue key parsed from the PR.

        Returns
        -------
        list of str
            SHAs for validated non-merge commits.

        Raises
        ------
        ValidationFailure
            If a commit is missing the key, includes another issue key, or no
            non-merge commits are present.
        """
        if not commits:
            raise ValidationFailure(
                "PR_HAS_NO_COMMITS", "No commits were returned for this pull request."
            )
        commit_shas: list[str] = []
        contract = _load_change_request_contract()
        token_pattern = re.compile(rf"\b{_unanchored_pattern(contract.issue_key_pattern)}\b")
        for item in commits:
            commit = item.get("commit") or {}
            message = commit.get("message") or ""
            if len(item.get("parents") or []) > 1:
                continue
            issue_keys = {match.group(0) for match in token_pattern.finditer(message)}
            sha = str(item.get("sha") or "unknown")[:12]
            if issue_keys != {change_id}:
                raise ValidationFailure(
                    "COMMIT_CHANGE_ID_MISMATCH",
                    f"Commit `{sha}` must reference `{change_id}` and no other Jira issue key.",
                )
            commit_shas.append(str(item.get("sha") or ""))
        if not commit_shas:
            raise ValidationFailure(
                "PR_HAS_NO_CHANGE_COMMITS",
                "No non-merge commits were available to validate.",
            )
        return commit_shas

    @staticmethod
    def validate_release_commits(
        commits: list[dict[str, Any]],
    ) -> tuple[list[str], list[dict[str, str]]]:
        """Require one configured Jira key in every release commit.

        Parameters
        ----------
        commits : list of dict[str, Any]
            Commit records returned by GitHub's compare API.

        Returns
        -------
        tuple
            Ordered commit SHAs and their corresponding Change IDs.

        Raises
        ------
        ValidationFailure
            If a commit has no Jira key, has conflicting keys, or the range is
            empty.
        """
        if not commits:
            raise ValidationFailure(
                "RELEASE_HAS_NO_COMMITS",
                "The release contains no commits after its baseline release.",
            )
        contract = _load_change_request_contract()
        key_pattern = _unanchored_pattern(contract.issue_key_pattern)
        token_pattern = re.compile(rf"\b{key_pattern}\b")
        commit_shas: list[str] = []
        identities: list[dict[str, str]] = []
        for item in commits:
            commit = item.get("commit") or {}
            message = str(commit.get("message") or "")
            issue_keys = {match.group(0) for match in token_pattern.finditer(message)}
            sha = str(item.get("sha") or "")
            short_sha = sha[:12] or "unknown"
            if not re.fullmatch(r"[0-9a-fA-F]{40,64}", sha):
                raise ValidationFailure(
                    "RELEASE_COMMIT_SHA_INVALID",
                    f"Release commit `{short_sha}` has an invalid GitHub SHA.",
                    result="ERROR",
                )
            if len(issue_keys) != 1:
                raise ValidationFailure(
                    "RELEASE_COMMIT_CHANGE_ID_INVALID",
                    f"Release commit `{short_sha}` must reference exactly one Jira issue key.",
                )
            change_id = next(iter(issue_keys))
            commit_shas.append(sha)
            identities.append({"commit_sha": sha, "change_id": change_id})
        if not identities:
            raise ValidationFailure(
                "RELEASE_HAS_NO_CHANGE_COMMITS",
                "The release range has no commits to validate.",
            )
        return commit_shas, identities


def _unanchored_pattern(pattern: str) -> str:
    """Return the configured key expression without full-match anchors."""
    return pattern.removeprefix("^").removesuffix("$")


def _load_change_request_contract() -> ChangeRequestContract:
    """Load contract configuration as a workflow-friendly validation error."""
    try:
        return ChangeRequestContract.load()
    except ContractViolation as exc:
        raise ValidationFailure(
            "CHANGE_REQUEST_CONFIG_INVALID", str(exc), result="ERROR"
        ) from exc


@dataclass(frozen=True)
class JiraChangeSnapshot:
    """Normalized Jira fields observed during a PR validation.

    Parameters
    ----------
    issue_url : str
        Browser URL for the Jira issue.
    issue_type : str
        Jira issue type name.
    status : str
        Current Jira workflow status.
    approval_state : str or None
        Configured Jira approval field value.
    approved_by : str or None
        Jira account ID of the person who changed the approval field.
    approved_at : datetime or None
        Approval timestamp, when present.
    risk : str or None
        Configured risk field value.
    required_fields : dict[str, Any]
        Values of required Jira fields, keyed by their configuration names.
    """

    issue_url: str
    issue_type: str
    status: str
    approval_state: Optional[str]
    approval_history_state: Optional[str]
    approved_by: Optional[str]
    approved_at: Optional[datetime]
    risk: Optional[str]
    required_fields: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        """Serialize the Jira snapshot for evidence.

        Returns
        -------
        dict[str, Any]
            JSON-compatible Jira evidence.
        """
        return {
            "issue_url": self.issue_url,
            "issue_type": self.issue_type,
            "status": self.status,
            "approval_state": self.approval_state,
            "approval_history_state": self.approval_history_state,
            "approved_by": self.approved_by,
            "approved_at": self.approved_at.isoformat() if self.approved_at else None,
            "risk": self.risk,
            "required_fields": self.required_fields,
        }


class JiraApprovalPolicy:
    """Map configured Jira fields and enforce production approval rules."""

    def __init__(self, settings: ActionSettings, client: Optional[JiraClient] = None) -> None:
        """Create the policy validator and Jira client.

        Parameters
        ----------
        settings : ActionSettings
            Jira field mappings and issue type configuration.
        client : JiraClient or None, default=None
            Optional Jira client override.
        """
        self.settings = settings
        self.client = client or JiraClient(settings)

    def validate(self, change_id: str) -> JiraChangeSnapshot:
        """Confirm Jira authorizes this change for production.

        Parameters
        ----------
        change_id : str
            Canonical issue key parsed from the GitHub PR.

        Returns
        -------
        JiraChangeSnapshot
            Normalized Jira state observed during validation.

        Raises
        ------
        ValidationFailure
            If Jira data does not meet Block 1 approval policy.
        """
        contract = _load_change_request_contract()
        field_rules = contract.jira_fields
        issue = self.client.get_issue(
            change_id,
            ["issuetype", "status", "summary"]
            + [rule.field_id for rule in field_rules.values()],
        )
        if issue.get("key") != change_id:
            raise ValidationFailure(
                "JIRA_KEY_MISMATCH",
                f"Jira resolved `{change_id}` to a different issue key; use the current key.",
            )

        fields = issue["fields"]
        configured_values = {
            name: _normalize_configured_field(fields.get(rule.field_id), rule)
            for name, rule in field_rules.items()
        }
        approval_state = configured_values.get("approval_state")
        approval_history = _approval_history_metadata(
            self.client.get_issue_changelogs(change_id),
            field_rules["approval_state"].field_id,
        )
        issue_type = (fields.get("issuetype") or {}).get("name", "")
        status = (fields.get("status") or {}).get("name", "")
        snapshot = JiraChangeSnapshot(
            issue_url=self.client.base_url.rstrip("/") + f"/browse/{change_id}",
            issue_type=issue_type,
            status=status,
            approval_state=approval_state,
            approval_history_state=approval_history["approval_state"],
            approved_by=approval_history["approved_by"],
            approved_at=approval_history["approved_at"],
            risk=configured_values.get("risk"),
            required_fields={
                name: configured_values[name]
                for name, rule in field_rules.items()
                if rule.required
            },
        )
        self._enforce_policy(change_id, snapshot, str(fields.get("summary") or ""))
        return snapshot

    def _enforce_policy(
        self, change_id: str, snapshot: JiraChangeSnapshot, summary: str
    ) -> None:
        """Apply Block 1 contract checks to a normalized Jira issue.

        Parameters
        ----------
        change_id : str
            Jira issue key.
        snapshot : JiraChangeSnapshot
            Normalized issue state.
        summary : str
            Jira issue summary, required by the shared Change Request model.

        Raises
        ------
        ValidationFailure
            If the issue is not the configured production-approved request.
        """
        details = snapshot.to_dict()
        contract = _load_change_request_contract()

        for name, rule in contract.jira_fields.items():
            value = snapshot.required_fields.get(name)
            if rule.required and not _is_configured_value(value):
                raise ValidationFailure(
                    "JIRA_REQUIRED_FIELD_MISSING",
                    f"Required Jira field `{name}` is empty.",
                    details=details,
                )
        expected_type = contract.issue_type
        if snapshot.issue_type != expected_type:
            raise ValidationFailure(
                "JIRA_WRONG_ISSUE_TYPE",
                f"`{change_id}` is `{snapshot.issue_type or 'unknown'}`; expected a Change Request.",
                details=details,
            )
        if snapshot.approval_state != contract.approved_state:
            raise ValidationFailure(
                "JIRA_NOT_APPROVED",
                f"`{change_id}` approval is `{snapshot.approval_state or 'unset'}`; required `{contract.approved_state}`.",
                details=details,
            )
        if snapshot.approval_history_state != snapshot.approval_state:
            raise ValidationFailure(
                "JIRA_APPROVAL_HISTORY_MISMATCH",
                f"`{change_id}` current Approval State does not match its latest changelog entry.",
                details=details,
            )
        if not snapshot.approved_by or snapshot.approved_at is None:
            raise ValidationFailure(
                "JIRA_APPROVAL_HISTORY_MISSING",
                f"`{change_id}` has no changelog entry identifying who approved it and when.",
                details=details,
            )
        request = ChangeRequest(
            change_id=change_id,
            issue_type=snapshot.issue_type,
            summary=summary,
            status=snapshot.status,
            approval_state=snapshot.approval_state or "",
            risk=snapshot.risk,
            approved_by=snapshot.approved_by,
            approved_at=snapshot.approved_at,
            jira_url=snapshot.issue_url,
        )
        try:
            request.require_production_approval(contract)
        except ContractViolation as exc:
            raise ValidationFailure(
                "JIRA_CONTRACT_INVALID", str(exc), details=details
            ) from exc
        if (
            snapshot.approved_at is not None
            and snapshot.approved_at > datetime.now(timezone.utc)
        ):
            raise ValidationFailure(
                "JIRA_APPROVAL_IN_FUTURE",
                "Jira approval timestamp is in the future.",
                details=details,
            )


def _approval_history_metadata(
    histories: list[dict[str, Any]], approval_field_id: str
) -> dict[str, Any]:
    """Extract the latest Approval State change's author, value, and time."""
    changes: list[tuple[datetime, dict[str, Any], dict[str, Any]]] = []
    for history in histories:
        for item in history.get("items") or []:
            if not isinstance(item, dict):
                continue
            if item.get("fieldId") == approval_field_id:
                created = parse_timestamp(history.get("created"))
                if created is None:
                    continue
                author = history.get("author")
                if not isinstance(author, dict):
                    author = {}
                changes.append((created, author, item))

    if not changes:
        return {"approval_state": None, "approved_by": None, "approved_at": None}

    created, author, item = max(changes, key=lambda change: change[0])
    account_id = author.get("accountId")
    display_name = author.get("displayName")
    return {
        "approval_state": item.get("toString"),
        "approved_by": str(account_id or display_name) if account_id or display_name else None,
        "approved_at": created,
    }


def _normalize_configured_field(value: Any, rule: JiraFieldRule) -> Any:
    """Normalize configured Jira field values for validation and evidence."""
    if value is None:
        return None
    if rule.value_type == "select":
        return select_value(value)
    if rule.value_type == "boolean":
        return bool_value(value)
    if rule.value_type == "date_time":
        parsed = parse_timestamp(value)
        return parsed.isoformat() if parsed else None
    if rule.value_type == "text":
        return _jira_text(value)
    return value


def _jira_text(value: Any) -> str:
    """Extract text from scalar values or Jira's nested document format."""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        return " ".join(filter(None, (_jira_text(item) for item in value)))
    if isinstance(value, dict):
        if isinstance(value.get("text"), str):
            return value["text"].strip()
        return " ".join(
            filter(None, (_jira_text(item) for item in value.get("content", [])))
        )
    return "" if value is None else str(value).strip()


def _is_configured_value(value: Any) -> bool:
    """Return whether a Jira field has a meaningful configured value."""
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, dict)):
        return bool(value)
    return True
