"""Databricks deployment-attempt evidence contract."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional


@dataclass(frozen=True)
class DeploymentEvidence:
    """One immutable CI/CD record for a Databricks deployment attempt.

    Parameters
    ----------
    deployment_attempt_id : str
        Stable identifier for this individual CI run attempt.
    change_id : str or None
        Jira issue key authorizing the production change.
    authorization, source, ci, databricks, execution : dict
        Evidence snapshots from the relevant systems.
    release_gate : dict
        GitHub environment protection outcome and workflow link.
    reason_codes : list of dict
        Stable reason codes and human-readable details for unsuccessful steps.
    policy_version : str
        Version of the deployment policy used by the caller.
    observed_at : str
        UTC time when this record was written.
    """

    deployment_attempt_id: str
    change_id: Optional[str]
    authorization: dict[str, Any]
    source: dict[str, Any]
    ci: dict[str, Any]
    databricks: dict[str, Any]
    execution: dict[str, Any]
    release_gate: dict[str, Any] = field(default_factory=dict)
    reason_codes: list[dict[str, str]] = field(default_factory=list)
    policy_version: str = "1"
    observed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        """Serialize evidence using the versioned JSON contract."""
        return {
            "schema_version": "1.1",
            "event_type": "databricks_deployment_attempt",
            **asdict(self),
        }
