"""Block 1 Change Identity contract, independent of Jira's API and SDKs."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
import os
from pathlib import Path
import re
from typing import Any, Optional

import yaml


class ContractViolation(ValueError):
    """Raised when a change request violates the Block 1 contract."""


@dataclass(frozen=True)
class JiraFieldRule:
    """Configuration for one Jira field read by the approval policy."""

    field_id: str
    value_type: str
    required: bool
    approved_value: Optional[str] = None


@dataclass(frozen=True)
class ChangeRequestContract:
    """Configurable rules for validating normalized Change Requests.

    Contract values are loaded from ``config/change-request.yml`` by default.
    Set ``CHANGE_REQUEST_CONFIG`` to select a different YAML file.
    """

    schema_version: str
    issue_type: str
    issue_key_pattern: str
    approved_state: str
    jira_fields: dict[str, JiraFieldRule]

    @classmethod
    def load(cls, path: Optional[str] = None) -> "ChangeRequestContract":
        """Load and validate contract rules from a YAML file.

        Parameters
        ----------
        path : str or None, default=None
            YAML path. If omitted, use ``CHANGE_REQUEST_CONFIG`` or the
            repository's ``config/change-request.yml``.

        Returns
        -------
        ChangeRequestContract
            Immutable validated contract settings.

        Raises
        ------
        ContractViolation
            If the file is unreadable or has missing/invalid contract values.
        """
        config_path = Path(
            path
            or os.environ.get("CHANGE_REQUEST_CONFIG")
            or Path(__file__).resolve().parents[3] / "config" / "change-request.yml"
        )
        try:
            with config_path.open(encoding="utf-8") as stream:
                values: Any = yaml.safe_load(stream)
        except (OSError, yaml.YAMLError) as exc:
            raise ContractViolation(
                f"could not load ChangeRequest YAML configuration: {config_path}"
            ) from exc
        try:
            jira_field_values = values["jira_fields"]
            if not isinstance(jira_field_values, dict):
                raise TypeError("jira_fields must be a mapping")
            jira_fields: dict[str, JiraFieldRule] = {}
            for name, field_values in jira_field_values.items():
                if not isinstance(field_values, dict):
                    raise TypeError(f"jira_fields.{name} must be a mapping")
                required = field_values.get("required", False)
                if not isinstance(required, bool):
                    raise TypeError(f"jira_fields.{name}.required must be a boolean")
                approved_value = field_values.get("approved_value")
                if approved_value is not None and not isinstance(approved_value, str):
                    raise TypeError(f"jira_fields.{name}.approved_value must be a string")
                jira_fields[str(name)] = JiraFieldRule(
                    field_id=str(field_values["id"]),
                    value_type=str(field_values.get("type", "select")),
                    required=required,
                    approved_value=approved_value,
                )
            approval_rule = jira_fields.get("approval_state")
            contract = cls(
                schema_version=str(values["schema_version"]),
                issue_type=str(values["issue_type"]),
                issue_key_pattern=str(values["issue_key_pattern"]),
                approved_state=str(approval_rule.approved_value or "")
                if approval_rule
                else "",
                jira_fields=jira_fields,
            )
        except (AttributeError, KeyError, TypeError) as exc:
            raise ContractViolation(
                f"invalid ChangeRequest YAML configuration: {config_path}"
            ) from exc

        if not contract.schema_version or not contract.issue_type:
            raise ContractViolation("schema_version and issue_type must be non-empty")
        try:
            re.compile(contract.issue_key_pattern)
        except re.error as exc:
            raise ContractViolation("issue_key_pattern is not a valid regular expression") from exc
        if "approval_state" not in contract.jira_fields:
            raise ContractViolation(
                "jira_fields.approval_state must be configured for production approval"
            )
        for name, rule in contract.jira_fields.items():
            if not rule.field_id or rule.field_id == "None":
                raise ContractViolation(f"jira_fields.{name}.id must be configured")
            if rule.value_type not in {"select", "text", "boolean", "date_time", "raw"}:
                raise ContractViolation(
                    f"jira_fields.{name}.type must be select, text, boolean, date_time, or raw"
                )
        if contract.jira_fields["approval_state"].value_type != "select":
            raise ContractViolation("jira_fields.approval_state.type must be select")
        if not contract.approved_state:
            raise ContractViolation(
                "jira_fields.approval_state.approved_value must be configured"
            )
        return contract


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
    risk: Optional[str] = None
    approved_by: Optional[str] = None
    approved_at: Optional[datetime] = None
    description: str = ""
    jira_url: Optional[str] = None
    schema_version: Optional[str] = None

    def validate(
        self, contract: Optional[ChangeRequestContract] = None
    ) -> "ChangeRequest":
        """Validate normalized Jira data and return this immutable instance."""
        contract = contract or ChangeRequestContract.load()
        if not isinstance(self.change_id, str) or not re.fullmatch(contract.issue_key_pattern, self.change_id):
            raise ContractViolation("change_id does not match the configured Jira issue-key pattern")
        if self.issue_type != contract.issue_type:
            raise ContractViolation(f"issue_type must be {contract.issue_type!r}")
        if not self.summary or not self.summary.strip():
            raise ContractViolation("summary is required")
        if self.schema_version not in (None, contract.schema_version):
            raise ContractViolation("unsupported schema_version")
        for name, value in (
            ("status", self.status),
            ("approval_state", self.approval_state),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ContractViolation(f"{name} is required")
        for name, value in (("risk", self.risk),):
            if value is not None and (not isinstance(value, str) or not value.strip()):
                raise ContractViolation(f"{name} must be non-empty when provided")
        if self.approved_at is not None and self.approved_at.tzinfo is None:
            raise ContractViolation("approved_at must include a timezone")
        return self

    def require_production_approval(
        self, contract: Optional[ChangeRequestContract] = None
    ) -> "ChangeRequest":
        """Require approval when this request is treated as production-bound."""
        contract = contract or ChangeRequestContract.load()
        self.validate(contract)
        if self.approval_state != contract.approved_state:
            raise ContractViolation(
                f"production change requires approval_state={contract.approved_state!r}"
            )
        if not self.approved_by or not self.approved_by.strip():
            raise ContractViolation("approved_by must be extractable from Jira history")
        if self.approved_at is None:
            raise ContractViolation("approved_at must be extractable from Jira history")
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
