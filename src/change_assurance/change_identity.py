"""Block 1 Change Identity contract, independent of Jira's API and SDKs."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
import re
from typing import Optional


ISSUE_KEY_PATTERN = re.compile(r"^[A-Z][A-Z0-9]+-[1-9][0-9]*$")
APPROVAL_STATES = {"Pending", "Approved", "Rejected", "Emergency Approved"}
RISKS = {"Low", "Medium", "High", "Critical"}
ENVIRONMENTS = {"Development", "Test", "Production"}


class ContractViolation(ValueError):
    """Raised when a change request violates the Block 1 contract."""


@dataclass(frozen=True)
class ChangeRequest:
    """Normalized view of one Jira Change Request issue.

    `change_id` must be the Jira issue key. Jira-specific custom field IDs and
    API responses should be mapped to this model by a future connector.
    """

    change_id: str
    issue_type: str
    summary: str
    status: str
    approval_state: str
    risk: str
    target_environment: str
    emergency_change: bool = False
    approved_by: Optional[str] = None
    approved_at: Optional[datetime] = None
    description: str = ""
    jira_url: Optional[str] = None
    schema_version: str = "1.0"

    def validate(self) -> "ChangeRequest":
        """Validate normalized Jira data and return this immutable instance."""
        if not isinstance(self.change_id, str) or not ISSUE_KEY_PATTERN.fullmatch(self.change_id):
            raise ContractViolation("change_id must be a Jira issue key such as DEMO-12")
        if self.issue_type != "Change Request":
            raise ContractViolation("issue_type must be 'Change Request'")
        if not self.summary or not self.summary.strip():
            raise ContractViolation("summary is required")
        if self.schema_version != "1.0":
            raise ContractViolation("unsupported schema_version")
        if self.approval_state not in APPROVAL_STATES:
            raise ContractViolation(f"approval_state must be one of {sorted(APPROVAL_STATES)}")
        if self.risk not in RISKS:
            raise ContractViolation(f"risk must be one of {sorted(RISKS)}")
        if self.target_environment not in ENVIRONMENTS:
            raise ContractViolation(f"target_environment must be one of {sorted(ENVIRONMENTS)}")
        if not isinstance(self.emergency_change, bool):
            raise ContractViolation("emergency_change must be a boolean")
        if self.approved_at is not None and self.approved_at.tzinfo is None:
            raise ContractViolation("approved_at must include a timezone")
        if self.approval_state in {"Approved", "Emergency Approved"}:
            if not self.approved_by or not self.approved_by.strip():
                raise ContractViolation("approved_by is required for an approved change")
            if self.approved_at is None:
                raise ContractViolation("approved_at is required for an approved change")
        if self.approval_state == "Emergency Approved" and not self.emergency_change:
            raise ContractViolation("Emergency Approved requires emergency_change=true")
        if self.emergency_change and self.approval_state == "Approved":
            raise ContractViolation("emergency changes must use Emergency Approved")
        if self.status == "Rejected" and self.approval_state != "Rejected":
            raise ContractViolation("Rejected status requires Rejected approval_state")
        return self

    def require_production_approval(self) -> "ChangeRequest":
        """Enforce the approval gate only for production-targeted changes."""
        self.validate()
        if self.target_environment != "Production":
            return self
        accepted = "Emergency Approved" if self.emergency_change else "Approved"
        if self.approval_state != accepted:
            raise ContractViolation(
                f"production change requires approval_state={accepted!r}; "
                f"got {self.approval_state!r}"
            )
        return self


@dataclass(frozen=True)
class DeployedChange:
    """A Change Request identity after a production deployment is recorded."""

    request: ChangeRequest
    deployment_id: str
    deployed_at: datetime

    def __post_init__(self) -> None:
        self.request.require_production_approval()
        if not self.deployment_id or not self.deployment_id.strip():
            raise ContractViolation("deployment_id is required")
        if self.deployed_at.tzinfo is None:
            raise ContractViolation("deployed_at must include a timezone")
        if self.request.approved_at is None or self.request.approved_at > self.deployed_at:
            raise ContractViolation("approval must be recorded before production deployment")

    def amend_request(self, updated: ChangeRequest) -> "DeployedChange":
        """Permit metadata updates while preserving the deployed Jira identity."""
        if updated.change_id != self.request.change_id:
            raise ContractViolation("change_id is immutable after deployment")
        updated.require_production_approval()
        return replace(self, request=updated)
