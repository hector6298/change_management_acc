"""Write validation evidence and human-readable GitHub Actions summaries."""

from __future__ import annotations

import json
from pathlib import Path

from ..models.action import ActionSettings, EvidenceRecord


class WorkflowReporter:
    """Persist evidence JSON and a concise Markdown run summary.

    Parameters
    ----------
    settings : ActionSettings
        Settings containing the optional ``GITHUB_STEP_SUMMARY`` file path.
    """

    EVIDENCE_PATH = Path("change-assurance-evidence.json")

    def __init__(self, settings: ActionSettings) -> None:
        self.settings = settings

    def write(self, evidence: EvidenceRecord) -> None:
        """Write the evidence artifact and Actions step summary.

        Parameters
        ----------
        evidence : EvidenceRecord
            Completed validation record.
        """
        self.EVIDENCE_PATH.write_text(
            json.dumps(evidence.to_dict(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        summary_path = self.settings.get("GITHUB_STEP_SUMMARY")
        if summary_path:
            Path(summary_path).write_text(self._format_summary(evidence), encoding="utf-8")

    @staticmethod
    def _format_summary(evidence: EvidenceRecord) -> str:
        """Format the result, identifiers, and remediation as Markdown.

        Parameters
        ----------
        evidence : EvidenceRecord
            Completed validation record.

        Returns
        -------
        str
            Markdown content for the GitHub Actions run summary.
        """
        summaries = {
            "PASS": "Change is approved for production-bound merge.",
            "FAILURE": "Policy failed; merge should remain blocked.",
            "ERROR": "Validation could not complete; merge should remain blocked.",
            "SKIPPED": "Target branch is outside the configured production policy.",
        }
        lines = [
            "## Change assurance",
            "",
            f"**Result:** `{evidence.result}` — "
            f"{summaries.get(evidence.result, 'Validation result is unavailable.')}",
            f"**Change ID:** `{evidence.change_id or '(not resolved)'}`",
        ]
        if evidence.github:
            number = evidence.github["pull_request"]
            url = evidence.github.get("pull_request_url")
            pr = f"[#{number}]({url})" if url else f"#{number}"
            lines.extend(
                [
                    f"**Pull request:** {pr} → `{evidence.github['base_branch']}`",
                    f"**Head commit:** `{evidence.github.get('head_sha') or 'unknown'}`",
                ]
            )
        if evidence.jira and evidence.jira.get("issue_url"):
            lines.extend(
                [
                    f"**Jira:** {evidence.jira['issue_url']}",
                    f"**Approval:** `{evidence.jira.get('approval_state') or 'unset'}` "
                    f"(status `{evidence.jira.get('status') or 'unset'}`)",
                ]
            )
        if evidence.reason_codes:
            lines.extend(["", "### Details", ""])
            for reason in evidence.reason_codes:
                message = _escape_markdown(str(reason.get("message", "")))
                lines.append(f"- `{reason.get('code', 'UNKNOWN')}` — {message}")
        return "\n".join(lines) + "\n"


def _escape_markdown(value: str) -> str:
    """Escape untrusted single-line text before Markdown rendering.

    Parameters
    ----------
    value : str
        Text originating from Jira or an API error.

    Returns
    -------
    str
        Escaped, single-line summary text.
    """
    value = value.replace("\n", " ").replace("\r", " ")
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("`", "&#96;")
        .replace("|", "&#124;")
    )
