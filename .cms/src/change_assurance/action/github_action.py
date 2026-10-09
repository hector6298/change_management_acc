"""Run Block 2 validation from the GitHub Actions workflow.

This file is intentionally small. API clients, data records, policy, and
reporting live in separate modules so each part can be understood independently.

Security note
------------
The workflow uses ``pull_request_target`` to access Jira credentials for fork
pull requests. It must check out and execute trusted base-branch code only.
Never check out, install, or execute code from a pull request head in this job.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import sys
from typing import Any

from ..clients.github import GitHubClient
from ..models.action import ActionSettings, EvidenceRecord, PullRequest, ValidationFailure
from ..policy.validation import ChangeIdPolicy, JiraApprovalPolicy
from ..reporting.workflow import WorkflowReporter


class ChangeAssuranceAction:
    """Coordinate one PR validation and persist the result.

    Parameters
    ----------
    settings : ActionSettings or None, default=None
        Runtime configuration. Defaults to process environment variables.
    """

    def __init__(self, settings: ActionSettings | None = None) -> None:
        self.settings = settings or ActionSettings()
        self.reporter = WorkflowReporter(self.settings)

    def run(self) -> int:
        """Run validation and return the workflow process exit code.

        Returns
        -------
        int
            ``0`` for ``PASS`` or ``SKIPPED``; ``1`` for ``FAILURE`` or
            ``ERROR``. GitHub uses this code to set the required check result.
        """
        evidence = EvidenceRecord()
        try:
            pr = self._load_pull_request()
            production_bound = pr.is_production_bound(
                self.settings.production_branches()
            )
            evidence.github = pr.to_evidence(production_bound)
            self._add_run_identifiers(evidence)

            if not production_bound:
                evidence.result = "SKIPPED"
                evidence.reason_codes.append(
                    {
                        "code": "NON_PRODUCTION_BRANCH",
                        "message": "Base branch is not in the configured production branch list.",
                    }
                )
            else:
                self._validate_production_change(pr, evidence)
                evidence.result = "PASS"
        except ValidationFailure as exc:
            evidence.result = exc.result
            evidence.jira = exc.details
            evidence.reason_codes.append({"code": exc.code, "message": str(exc)})
        except Exception as exc:  # Avoid leaking secrets in unexpected errors.
            evidence.result = "ERROR"
            evidence.reason_codes.append(
                {
                    "code": "UNEXPECTED_ERROR",
                    "message": f"Unexpected validator error: {type(exc).__name__}",
                }
            )
        finally:
            evidence.observed_at = datetime.now(timezone.utc).isoformat()
            self.reporter.write(evidence)

        return 0 if evidence.result in {"PASS", "SKIPPED"} else 1

    def _load_pull_request(self) -> PullRequest:
        """Load and normalize the current PR event.

        Returns
        -------
        PullRequest
            Normalized pull request event fields.

        Raises
        ------
        ValidationFailure
            If the event file is unavailable or does not contain a PR.
        """
        event_path = self.settings.require("GITHUB_EVENT_PATH")
        try:
            with open(event_path, encoding="utf-8") as stream:
                event: Any = json.load(stream)
        except (OSError, json.JSONDecodeError) as exc:
            raise ValidationFailure(
                "EVENT_UNREADABLE",
                "GitHub event payload could not be read.",
                result="ERROR",
            ) from exc
        if not isinstance(event, dict):
            raise ValidationFailure(
                "EVENT_INVALID",
                "GitHub event payload is not an object.",
                result="ERROR",
            )
        return PullRequest.from_event(
            event, self.settings.get("GITHUB_REPOSITORY")
        )

    def _validate_production_change(
        self, pr: PullRequest, evidence: EvidenceRecord
    ) -> None:
        """Validate PR identity, commits, and Jira approval.

        Parameters
        ----------
        pr : PullRequest
            Normalized pull request.
        evidence : EvidenceRecord
            Record to populate with the validated change and Jira snapshot.

        Raises
        ------
        ValidationFailure
            If any Block 2 production rule fails.
        """
        change_id = ChangeIdPolicy.extract(pr)
        evidence.change_id = change_id

        github = GitHubClient(self.settings)
        commits = github.get_pull_request_commits(pr)
        evidence.github["commit_shas"] = ChangeIdPolicy.validate_commits(
            commits, change_id
        )

        jira = JiraApprovalPolicy(self.settings)
        evidence.jira = jira.validate(change_id).to_dict()

    def _add_run_identifiers(self, evidence: EvidenceRecord) -> None:
        """Add GitHub workflow run identity to the evidence record.

        Parameters
        ----------
        evidence : EvidenceRecord
            Evidence record whose GitHub section is already populated.
        """
        if evidence.github is None:
            return
        evidence.github["workflow_run_id"] = self.settings.get("GITHUB_RUN_ID")
        try:
            evidence.github["workflow_run_attempt"] = int(
                self.settings.get("GITHUB_RUN_ATTEMPT", "1")
            )
        except ValueError:
            evidence.github["workflow_run_attempt"] = 1


def main() -> int:
    """Run the Action and return its process exit code.

    Returns
    -------
    int
        Exit code consumed by GitHub Actions.
    """
    return ChangeAssuranceAction().run()


if __name__ == "__main__":
    sys.exit(main())
