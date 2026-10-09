"""Revalidate Jira approval immediately before a production deployment."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
from typing import Any

from ..models.action import ActionSettings, ValidationFailure
from ..policy.validation import JiraApprovalPolicy


def _timestamp(value: Any) -> str | None:
    """Convert a datetime or timestamp value to ISO-8601 text."""
    if value is None:
        return None
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def run() -> int:
    """Validate Jira and persist the authorization snapshot for this attempt.

    Returns
    -------
    int
        Zero only when Jira confirms the currently configured approval policy.
    """
    output_path = Path(
        os.environ.get("DEPLOYMENT_AUTHORIZATION_PATH", "deployment-authorization.json")
    )
    observed_at = datetime.now(timezone.utc).isoformat()
    record: dict[str, Any] = {
        "schema_version": "1.0",
        "observed_at": observed_at,
        "result": "ERROR",
        "authorization": {
            "jira_issue_url": None,
            "approval_state": None,
            "approved_by": None,
            "approved_at": None,
            "revalidated_at": observed_at,
        },
        "change_requests": [],
        "jira": None,
        "reason": None,
    }
    try:
        source_path = os.environ.get("DEPLOYMENT_SOURCE_PATH", "deployment-source.json")
        change_ids: list[str] = []
        try:
            with open(source_path, encoding="utf-8") as stream:
                source_record = json.load(stream)
            source = source_record.get("source") or {}
            candidates = source_record.get("change_ids") or source.get("change_ids") or []
            if isinstance(candidates, list):
                change_ids = [item.strip() for item in candidates if isinstance(item, str) and item.strip()]
        except FileNotFoundError:
            pass
        if not change_ids:
            change_id = os.environ.get("CHANGE_ID", "").strip()
            if change_id:
                change_ids = [change_id]
        if not change_ids:
            raise ValidationFailure(
                "CHANGE_ID_MISSING", "A Jira Change ID must be present in the deployment source manifest."
            )
        results: list[dict[str, Any]] = []
        for change_id in dict.fromkeys(change_ids):
            try:
                snapshot = JiraApprovalPolicy(ActionSettings()).validate(change_id)
                authorization = {
                    "jira_issue_url": snapshot.issue_url,
                    "approval_state": snapshot.approval_state,
                    "approved_by": snapshot.approved_by,
                    "approved_at": _timestamp(snapshot.approved_at),
                    "revalidated_at": observed_at,
                }
                results.append({
                    "change_id": change_id,
                    "result": "PASS",
                    "authorization": authorization,
                    "jira": snapshot.to_dict(),
                    "reason": None,
                })
            except ValidationFailure as exc:
                jira = exc.details or {}
                authorization = {
                    "jira_issue_url": jira.get("issue_url"),
                    "approval_state": jira.get("approval_state"),
                    "approved_by": jira.get("approved_by"),
                    "approved_at": _timestamp(jira.get("approved_at")),
                    "revalidated_at": observed_at,
                }
                results.append({
                    "change_id": change_id,
                    "result": exc.result,
                    "authorization": authorization,
                    "jira": jira or None,
                    "reason": {"code": exc.code, "message": str(exc)},
                })
        failures = [item for item in results if item["result"] != "PASS"]
        record["change_requests"] = results
        record["result"] = "FAILURE" if failures else "PASS"
        if len(results) == 1:
            record["authorization"] = results[0]["authorization"]
            record["jira"] = results[0]["jira"]
        elif results:
            record["authorization"] = {
                "jira_issue_url": None,
                "approval_state": "Approved" if not failures else "Not approved",
                "approved_by": None,
                "approved_at": None,
                "revalidated_at": observed_at,
            }
        if failures:
            failed_ids = ", ".join(item["change_id"] for item in failures)
            record["reason"] = {
                "code": "JIRA_RELEASE_APPROVAL_FAILED",
                "message": f"Jira approval validation failed for: {failed_ids}.",
            }
            exit_code = 1
        else:
            exit_code = 0
    except ValidationFailure as exc:
        jira = exc.details or {}
        record.update(
            result=exc.result,
            jira=jira or None,
            authorization={
                "jira_issue_url": jira.get("issue_url"),
                "approval_state": jira.get("approval_state"),
                "approved_by": jira.get("approved_by"),
                "approved_at": _timestamp(jira.get("approved_at")),
                "revalidated_at": observed_at,
            },
            reason={"code": exc.code, "message": str(exc)},
        )
        exit_code = 1
    except Exception as exc:  # Keep credentials and response bodies out of logs.
        record["reason"] = {
            "code": "DEPLOYMENT_PREFLIGHT_ERROR",
            "message": f"Jira preflight could not complete ({type(exc).__name__}).",
        }
        exit_code = 1

    try:
        output_path.write_text(
            json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    except OSError as exc:
        print(f"Could not persist deployment authorization evidence ({type(exc).__name__}).", file=sys.stderr)
        return 1

    if record["reason"]:
        print(f"Jira deployment preflight failed: {record['reason']['code']}: {record['reason']['message']}", file=sys.stderr)
    return exit_code


if __name__ == "__main__":
    sys.exit(run())
