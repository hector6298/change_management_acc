"""Jira Cloud REST API client and Jira-field value normalization."""

from __future__ import annotations

from datetime import datetime
import json
from typing import Any, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urljoin
from urllib.request import Request, urlopen

from ..models.action import ActionSettings, ValidationFailure


class JiraClient:
    """Read Jira issues with OAuth credentials for a service account.

    Parameters
    ----------
    settings : ActionSettings
        Settings containing the Jira Cloud ID and OAuth client credentials.
    """

    def __init__(self, settings: ActionSettings) -> None:
        self.cloud_id = settings.require("JIRA_CLOUD_ID")
        self.client_id = settings.require("JIRA_OAUTH_CLIENT_ID")
        self.client_secret = settings.require("JIRA_OAUTH_CLIENT_SECRET")
        self.base_url = (
            "https://api.atlassian.com/ex/jira/"
            + quote(self.cloud_id, safe="")
            + "/"
        )
        self.token = self._get_access_token()

    def _get_access_token(self) -> str:
        """Exchange service-account credentials for a short-lived token.

        Returns
        -------
        str
            Jira Cloud bearer access token.

        Raises
        ------
        ValidationFailure
            If Atlassian rejects the credentials or returns an invalid response.
        """
        request = Request(
            "https://auth.atlassian.com/oauth/token",
            data=urlencode(
                {
                    "grant_type": "client_credentials",
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                }
            ).encode("utf-8"),
            headers={
                "Accept": "application/json",
                "Content-Type": "application/x-www-form-urlencoded",
                "User-Agent": "change-assurance-accelerator",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=20) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            raise ValidationFailure(
                "JIRA_OAUTH_FAILED",
                f"Atlassian OAuth token endpoint returned HTTP {exc.code}.",
                result="ERROR",
            ) from exc
        except (URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise ValidationFailure(
                "JIRA_OAUTH_UNAVAILABLE",
                "Could not obtain an OAuth access token from Atlassian.",
                result="ERROR",
            ) from exc

        access_token = payload.get("access_token") if isinstance(payload, dict) else None
        if not isinstance(access_token, str) or not access_token:
            raise ValidationFailure(
                "JIRA_OAUTH_RESPONSE_INVALID",
                "Atlassian returned an invalid OAuth token response.",
                result="ERROR",
            )
        return access_token

    def get_issue(self, change_id: str, fields: list[str]) -> dict[str, Any]:
        """Fetch a Jira issue with only the requested fields.

        Parameters
        ----------
        change_id : str
            Jira issue key.
        fields : list of str
            Jira field names or custom-field IDs to request.

        Returns
        -------
        dict[str, Any]
            Jira issue response object.

        Raises
        ------
        ValidationFailure
            If the issue is missing, access is denied, Jira is unavailable, or
            Jira returns an invalid response.
        """
        endpoint = urljoin(
            self.base_url, f"rest/api/3/issue/{quote(change_id, safe='')}"
        )
        endpoint += "?" + urlencode({"fields": ",".join(fields)})
        request = Request(
            endpoint,
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {self.token}",
                "User-Agent": "change-assurance-accelerator",
            },
        )
        try:
            with urlopen(request, timeout=20) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            if exc.code == 404:
                raise ValidationFailure(
                    "JIRA_ISSUE_NOT_FOUND",
                    f"Jira issue `{change_id}` was not found or is not visible to the integration account.",
                ) from exc
            if exc.code in {401, 403}:
                raise ValidationFailure(
                    "JIRA_ACCESS_DENIED",
                    "Jira rejected the configured credentials or the account cannot browse this issue.",
                    result="ERROR",
                ) from exc
            raise ValidationFailure(
                "JIRA_API_ERROR",
                f"Jira API returned HTTP {exc.code}.",
                result="ERROR",
            ) from exc
        except (URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise ValidationFailure(
                "JIRA_API_UNAVAILABLE",
                "Could not retrieve the Change Request from Jira.",
                result="ERROR",
            ) from exc

        if not isinstance(payload, dict) or not isinstance(payload.get("fields"), dict):
            raise ValidationFailure(
                "JIRA_RESPONSE_INVALID",
                "Jira returned an invalid issue response.",
                result="ERROR",
            )
        return payload

    def get_issue_changelogs(self, change_id: str) -> list[dict[str, Any]]:
        """Fetch every paginated changelog entry for a Jira issue.

        Parameters
        ----------
        change_id : str
            Jira issue key.

        Returns
        -------
        list of dict[str, Any]
            Changelog groups containing field changes, author, and timestamp.

        Raises
        ------
        ValidationFailure
            If Jira denies the request, is unavailable, or returns malformed
            changelog data.
        """
        endpoint = urljoin(
            self.base_url, f"rest/api/3/issue/{quote(change_id, safe='')}/changelog"
        )
        start_at = 0
        histories: list[dict[str, Any]] = []
        while True:
            url = endpoint + "?" + urlencode({"startAt": start_at, "maxResults": 100})
            request = Request(
                url,
                headers={
                    "Accept": "application/json",
                    "Authorization": f"Bearer {self.token}",
                    "User-Agent": "change-assurance-accelerator",
                },
            )
            try:
                with urlopen(request, timeout=20) as response:
                    payload = json.loads(response.read().decode("utf-8"))
            except HTTPError as exc:
                if exc.code in {401, 403}:
                    raise ValidationFailure(
                        "JIRA_ACCESS_DENIED",
                        "Jira denied access to the issue changelog.",
                        result="ERROR",
                    ) from exc
                raise ValidationFailure(
                    "JIRA_CHANGELOG_ERROR",
                    f"Jira changelog API returned HTTP {exc.code}.",
                    result="ERROR",
                ) from exc
            except (URLError, TimeoutError, json.JSONDecodeError) as exc:
                raise ValidationFailure(
                    "JIRA_CHANGELOG_UNAVAILABLE",
                    "Could not retrieve the Jira issue changelog.",
                    result="ERROR",
                ) from exc

            page_values = (
                payload.get("values", payload.get("histories"))
                if isinstance(payload, dict)
                else None
            )
            if not isinstance(page_values, list):
                raise ValidationFailure(
                    "JIRA_CHANGELOG_INVALID",
                    "Jira returned an invalid issue changelog response.",
                    result="ERROR",
                )
            page = [item for item in page_values if isinstance(item, dict)]
            histories.extend(page)
            try:
                total = int(payload.get("total", start_at + len(page)))
            except (TypeError, ValueError) as exc:
                raise ValidationFailure(
                    "JIRA_CHANGELOG_INVALID",
                    "Jira changelog response contains an invalid total count.",
                    result="ERROR",
                ) from exc
            if not page or start_at + len(page) >= total:
                return histories
            start_at += len(page)


def select_value(value: Any) -> Optional[str]:
    """Normalize Jira select, user-picker, and multi-select values.

    Parameters
    ----------
    value : Any
        Custom-field value returned by Jira.

    Returns
    -------
    str or None
        Display value, or ``None`` when the Jira field is unset.
    """
    if isinstance(value, dict):
        for key in ("value", "name", "displayName", "accountId"):
            if value.get(key) is not None:
                return str(value[key])
    if isinstance(value, list):
        if not value:
            return None
        if len(value) == 1:
            return select_value(value[0])
        return ",".join(filter(None, (select_value(item) for item in value)))
    return None if value is None else str(value)


def bool_value(value: Any) -> bool:
    """Normalize a Jira checkbox value to a Python boolean.

    Parameters
    ----------
    value : Any
        Jira checkbox, boolean, select, or list response.

    Returns
    -------
    bool
        ``True`` when the value is checked or selected.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, list):
        return any(bool_value(item) for item in value)
    if isinstance(value, dict):
        return bool_value(value.get("value", value.get("name", False)))
    if isinstance(value, (int, float)):
        return value != 0
    return str(value or "").strip().lower() in {"true", "yes", "y", "1", "checked"}


def parse_timestamp(value: Any) -> Optional[datetime]:
    """Parse an ISO timestamp and require an explicit timezone.

    Parameters
    ----------
    value : Any
        Jira date-time field value.

    Returns
    -------
    datetime or None
        Parsed timezone-aware value, or ``None`` for an unset field.

    Raises
    ------
    ValidationFailure
        If the value is malformed or does not include a timezone offset.
    """
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValidationFailure(
            "JIRA_CHANGELOG_TIMESTAMP_INVALID",
            "Jira timestamp is invalid.",
        ) from exc
    if parsed.tzinfo is None:
        raise ValidationFailure(
            "JIRA_CHANGELOG_TIMEZONE_MISSING",
            "Jira timestamp must include a timezone.",
        )
    return parsed
