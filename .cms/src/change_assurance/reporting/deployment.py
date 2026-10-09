"""Persistence for Databricks deployment-attempt evidence."""

from __future__ import annotations

import json
from pathlib import Path

from ..models.deployment import DeploymentEvidence


class DeploymentEvidenceReporter:
    """Write a deployment record as a standalone JSON artifact."""

    def __init__(self, output_path: str = "databricks-deployment-evidence.json") -> None:
        self.output_path = Path(output_path)

    def write(self, evidence: DeploymentEvidence) -> None:
        """Persist a complete JSON record, replacing any prior local file.

        CI must upload each run attempt under a unique artifact name so a later
        retry does not replace an earlier attempt in durable storage.
        """
        self.output_path.write_text(
            json.dumps(evidence.to_dict(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
