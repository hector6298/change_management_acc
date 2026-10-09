"""Create Block 3 evidence from deployment workflow environment values.

This module does not deploy resources or authenticate to Databricks. The
trusted deployment workflow supplies the recorded identifiers and outcomes.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
from typing import Any, Optional
from urllib.parse import parse_qs, urlparse

from ..models.deployment import DeploymentEvidence
from ..reporting.deployment import DeploymentEvidenceReporter


def _optional(name: str) -> Optional[str]:
    """Return a trimmed environment value, or ``None`` when it is blank."""
    return os.environ.get(name, "").strip() or None


def _integer(name: str, default: Optional[int] = None) -> Optional[int]:
    """Read an optional integer environment value."""
    value = _optional(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc


def _json_list(name: str) -> list[Any]:
    """Read a JSON array from an environment value, defaulting to empty."""
    raw_value = _optional(name)
    if raw_value is None:
        return []
    value = json.loads(raw_value)
    if not isinstance(value, list):
        raise ValueError(f"{name} must contain a JSON array")
    return value


def _authorization_snapshot() -> dict[str, Any]:
    """Load the result emitted by the deployment Jira preflight, if present."""
    path = _optional("DEPLOYMENT_AUTHORIZATION_PATH") or "deployment-authorization.json"
    try:
        with open(path, encoding="utf-8") as stream:
            value = json.load(stream)
    except FileNotFoundError:
        return {}
    if not isinstance(value, dict):
        raise ValueError("deployment authorization record must be a JSON object")
    return value


def _read_record(path_name: str, default_path: str) -> dict[str, Any]:
    """Read an optional JSON object written by an earlier workflow step."""
    path = _optional(path_name) or default_path
    try:
        with Path(path).open(encoding="utf-8") as stream:
            value = json.load(stream)
    except FileNotFoundError:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"{path_name} must point to a JSON object")
    return value


def _resource_entries(resources: Any) -> list[dict[str, Any]]:
    """Normalize common bundle-summary resource shapes."""
    entries: list[dict[str, Any]] = []
    if isinstance(resources, list):
        candidates = [(str(item.get("resource_type") or "resource"), None, item)
                      for item in resources if isinstance(item, dict)]
    elif isinstance(resources, dict):
        candidates = []
        for resource_type, group in resources.items():
            if isinstance(group, dict):
                candidates.extend(
                    (str(resource_type).rstrip("s"), str(key), item)
                    for key, item in group.items()
                    if isinstance(item, dict)
                )
            elif isinstance(group, list):
                candidates.extend(
                    (str(resource_type).rstrip("s"), None, item)
                    for item in group if isinstance(item, dict)
                )
    else:
        return entries

    for resource_type, resource_key, item in candidates:
        url = item.get("url") or item.get("deployment_url")
        if not isinstance(url, str):
            continue
        resource_id = item.get("resource_id") or item.get("id")
        if resource_id is None:
            path_parts = [part for part in urlparse(url).path.split("/") if part]
            if path_parts:
                resource_id = path_parts[-1]
        entries.append(
            {
                "resource_type": str(item.get("resource_type") or resource_type),
                "resource_key": str(item.get("resource_key") or item.get("key") or resource_key or "unknown"),
                "resource_id": str(resource_id) if resource_id is not None else None,
                "url": url,
            }
        )
    return entries


def _bundle_summary() -> tuple[dict[str, Any], list[dict[str, str]]]:
    """Extract workspace and resource metadata from an optional CLI summary."""
    path = _optional("DATABRICKS_BUNDLE_SUMMARY_PATH")
    if not path:
        return {}, []
    try:
        with Path(path).open(encoding="utf-8") as stream:
            summary = json.load(stream)
    except FileNotFoundError:
        return {}, []
    except (OSError, json.JSONDecodeError):
        return {}, [{"code": "BUNDLE_SUMMARY_UNAVAILABLE", "message": "Could not read the Databricks bundle summary."}]
    if not isinstance(summary, dict):
        return {}, [{"code": "BUNDLE_SUMMARY_INVALID", "message": "Databricks bundle summary is not a JSON object."}]

    workspace = summary.get("workspace")
    if not isinstance(workspace, dict):
        workspace = {}
    host = workspace.get("host") or summary.get("workspace_host")
    workspace_id = workspace.get("workspace_id") or summary.get("workspace_id")
    bundle = summary.get("bundle")
    if not isinstance(bundle, dict):
        bundle = {}
    if isinstance(host, str):
        query_workspace_id = parse_qs(urlparse(host).query).get("o", [None])[0]
        workspace_id = workspace_id or query_workspace_id
    return {
        "workspace_host": host,
        "workspace_id": str(workspace_id) if workspace_id is not None else None,
        "bundle_name": summary.get("name") or bundle.get("name"),
        "bundle_target": summary.get("target"),
        "resources": _resource_entries(summary.get("resources")),
    }, []


def build_evidence() -> DeploymentEvidence:
    """Build evidence from explicitly supplied CI and Databricks metadata.

    Raises
    ------
    ValueError
        If required CI identity, outcome enums, or JSON arrays are malformed.
    """
    repository = _optional("GITHUB_REPOSITORY")
    run_id = _optional("GITHUB_RUN_ID")
    if not repository or not run_id:
        raise ValueError("GITHUB_REPOSITORY and GITHUB_RUN_ID are required")

    attempt = _integer("GITHUB_RUN_ATTEMPT", 1) or 1
    run_url = None
    server_url = _optional("GITHUB_SERVER_URL")
    if server_url:
        run_url = f"{server_url.rstrip('/')}/{repository}/actions/runs/{run_id}"

    validation_result = (_optional("DATABRICKS_VALIDATION_RESULT") or "NOT_RUN").upper()
    deployment_result = (_optional("DATABRICKS_DEPLOYMENT_RESULT") or "NOT_RUN").upper()
    execution_result = (_optional("DATABRICKS_EXECUTION_RESULT") or "NOT_RUN").upper()
    allowed = {"SUCCESS", "FAILURE", "NOT_RUN"}
    if validation_result not in allowed or deployment_result not in allowed:
        raise ValueError("Databricks validation and deployment results must be SUCCESS, FAILURE, or NOT_RUN")
    if execution_result not in allowed | {"NOT_APPLICABLE"}:
        raise ValueError("Databricks execution result must be SUCCESS, FAILURE, NOT_RUN, or NOT_APPLICABLE")

    resources = _json_list("DATABRICKS_DEPLOYMENT_RESOURCES_JSON")
    reason_codes = _json_list("DEPLOYMENT_REASON_CODES_JSON")
    if any(not isinstance(item, dict) for item in resources + reason_codes):
        raise ValueError("resource and reason-code entries must be JSON objects")
    for item in reason_codes:
        if not isinstance(item.get("code"), str) or not isinstance(item.get("message"), str):
            raise ValueError("each reason code must include string code and message fields")

    source_record = _read_record("DEPLOYMENT_SOURCE_PATH", "deployment-source.json")
    source_data = source_record.get("source") or {}
    if source_record.get("reason"):
        reason_codes.append(source_record["reason"])

    authorization_record = _authorization_snapshot()
    authorization = authorization_record.get("authorization") or {}
    if authorization_record.get("reason"):
        reason_codes.append(authorization_record["reason"])
    if (
        authorization_record.get("jira")
        and not _optional("CHANGE_ID")
        and not source_data.get("change_ids")
    ):
        raise ValueError("CHANGE_ID is required when a Jira authorization record exists")

    bundle_summary, summary_reasons = _bundle_summary()
    reason_codes.extend(summary_reasons)
    if not resources:
        resources = bundle_summary.get("resources", [])

    workspace_host = _optional("DATABRICKS_HOST") or bundle_summary.get("workspace_host")
    if workspace_host:
        workspace_host = workspace_host.rstrip("/")
    change_id = source_record.get("change_id") or _optional("CHANGE_ID")
    source_commit = (
        source_data.get("release_commit_sha")
        or source_data.get("merge_commit_sha")
        or _optional("MERGE_COMMIT_SHA")
        or (
            _optional("GITHUB_SHA")
            if _optional("GITHUB_EVENT_NAME") == "push"
            else None
        )
    )
    source_branch = source_data.get("target_branch")
    if source_branch is None and _optional("GITHUB_EVENT_NAME") == "push":
        source_branch = _optional("GITHUB_REF_NAME")
    return DeploymentEvidence(
        deployment_attempt_id=f"github:{repository}:run-{run_id}:attempt-{attempt}",
        change_id=change_id,
        authorization={
            "result": authorization_record.get("result"),
            "jira_issue_url": authorization.get("jira_issue_url") or _optional("JIRA_ISSUE_URL"),
            "approval_state": authorization.get("approval_state") or _optional("JIRA_APPROVAL_STATE"),
            "approved_by": authorization.get("approved_by") or _optional("JIRA_APPROVED_BY"),
            "approved_at": authorization.get("approved_at") or _optional("JIRA_APPROVED_AT"),
            "revalidated_at": authorization.get("revalidated_at") or _optional("JIRA_REVALIDATED_AT"),
            "change_requests": [
                {
                    "change_id": item.get("change_id"),
                    "result": item.get("result"),
                    **(item.get("authorization") or {}),
                }
                for item in authorization_record.get("change_requests", [])
                if isinstance(item, dict)
            ],
        },
        source={
            "repository": source_data.get("repository") or repository,
            "pull_request": source_data.get("pull_request") or _integer("PULL_REQUEST_NUMBER"),
            "merge_commit_sha": source_data.get("merge_commit_sha") or source_commit,
            "branch": source_data.get("release_tag") or source_branch,
            "pull_request_url": source_data.get("pull_request_url"),
            "pull_request_title": source_data.get("pull_request_title"),
            "source_branch": source_data.get("source_branch"),
            "target_branch": source_data.get("target_branch"),
            "head_sha": source_data.get("head_sha"),
            "commit_shas": source_data.get("commit_shas", []),
            "release_tag": source_data.get("release_tag"),
            "base_release_tag": source_data.get("base_release_tag"),
            "release_commit_sha": source_data.get("release_commit_sha"),
            "change_ids": source_data.get("change_ids", []),
            "commit_identities": source_data.get("commit_identities", []),
        },
        ci={
            "provider": "github_actions",
            "run_id": run_id,
            "run_attempt": attempt,
            "run_url": run_url,
            "started_at": _optional("DEPLOYMENT_STARTED_AT"),
            "completed_at": datetime.now(timezone.utc).isoformat(),
        },
        databricks={
            "workspace_id": _optional("DATABRICKS_WORKSPACE_ID") or bundle_summary.get("workspace_id"),
            "workspace_host": workspace_host,
            "cli_version": _optional("DATABRICKS_CLI_VERSION"),
            "bundle_name": _optional("DATABRICKS_BUNDLE_NAME") or bundle_summary.get("bundle_name"),
            "bundle_target": _optional("DATABRICKS_BUNDLE_TARGET") or bundle_summary.get("bundle_target"),
            "deployment_operation_id": _optional("DATABRICKS_DEPLOYMENT_OPERATION_ID"),
            "validation_result": validation_result,
            "deployment_result": deployment_result,
            "resources": resources,
            "artifact_digest": _optional("DEPLOYMENT_ARTIFACT_DIGEST"),
        },
        execution={
            "result": execution_result,
            "job_run_id": _optional("DATABRICKS_JOB_RUN_ID"),
            "health_check_result": _optional("DATABRICKS_HEALTH_CHECK_RESULT"),
        },
        release_gate={
            "environment": _optional("RELEASE_GATE_ENVIRONMENT"),
            "protection_result": _optional("RELEASE_GATE_RESULT") or "NOT_APPLICABLE",
            "workflow_run_url": run_url,
        },
        reason_codes=reason_codes,
        policy_version=_optional("DEPLOYMENT_POLICY_VERSION") or "1",
    )


def main() -> int:
    """Write deployment evidence and return a process status."""
    try:
        evidence = build_evidence()
        output_path = _optional("DEPLOYMENT_EVIDENCE_PATH") or "databricks-deployment-evidence.json"
        DeploymentEvidenceReporter(output_path).write(evidence)
        return 0
    except (ValueError, json.JSONDecodeError, OSError) as exc:
        # Avoid including arbitrary environment values in workflow logs.
        print(f"Could not write deployment evidence: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
