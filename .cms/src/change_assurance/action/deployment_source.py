"""Resolve and validate the merged PR that supplies a deployment revision."""

from __future__ import annotations

from datetime import datetime, timezone
import fnmatch
import json
import os
from pathlib import Path
import re
import sys
from typing import Any

from ..clients.github import GitHubClient
from ..models.action import ActionSettings, PullRequest, ValidationFailure
from ..policy.validation import ChangeIdPolicy


MERGE_SHA = re.compile(r"^(?:[0-9a-fA-F]{40}|[0-9a-fA-F]{64})$")


def run() -> int:
    """Resolve a merged production PR, validate its identity, and save metadata.

    The PR number is an operator input. The Change ID and merge SHA are read
    from GitHub and are never accepted as caller-supplied values.

    Returns
    -------
    int
        Zero when the merged PR and all included commits meet the Block 2
        identity contract; nonzero otherwise.
    """
    settings = ActionSettings()
    output_path = Path(
        settings.get("DEPLOYMENT_SOURCE_PATH", "deployment-source.json")
    )
    record: dict[str, Any] = {
        "schema_version": "1.0",
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "result": "ERROR",
        "change_id": None,
        "source": None,
        "reason": None,
    }
    resolved_outputs: dict[str, str] = {}

    try:
        repository = settings.require("GITHUB_REPOSITORY")
        try:
            pull_request_number = int(settings.require("DEPLOYMENT_PULL_REQUEST_NUMBER"))
        except ValueError as exc:
            raise ValidationFailure(
                "PULL_REQUEST_NUMBER_INVALID",
                "The deployment input must be a positive pull request number.",
            ) from exc
        if pull_request_number < 1:
            raise ValidationFailure(
                "PULL_REQUEST_NUMBER_INVALID",
                "The deployment input must be a positive pull request number.",
            )

        github = GitHubClient(settings)
        pull_data = github.get_pull_request(repository, pull_request_number)
        if pull_data.get("merged") is not True:
            raise ValidationFailure(
                "PR_NOT_MERGED", f"Pull request #{pull_request_number} is not merged."
            )

        base = pull_data.get("base") or {}
        head = pull_data.get("head") or {}
        base_branch = str(base.get("ref") or "")
        if not any(
            fnmatch.fnmatchcase(base_branch, pattern)
            for pattern in settings.production_branches()
        ):
            raise ValidationFailure(
                "PR_NOT_PRODUCTION_BOUND",
                "The merged pull request targets a branch outside the configured production branch list.",
            )

        merge_sha = str(pull_data.get("merge_commit_sha") or "")
        if not MERGE_SHA.fullmatch(merge_sha):
            raise ValidationFailure(
                "PR_MERGE_COMMIT_MISSING",
                "GitHub did not provide a valid merge commit SHA for this pull request.",
            )

        pr = PullRequest(
            number=pull_request_number,
            repository=repository,
            url=pull_data.get("html_url"),
            title=str(pull_data.get("title") or ""),
            body=str(pull_data.get("body") or ""),
            branch=str(head.get("ref") or ""),
            base_branch=base_branch,
            head_sha=str(head.get("sha") or ""),
        )
        source = {
            "repository": repository,
            "pull_request": pull_request_number,
            "pull_request_url": pr.url,
            "pull_request_title": pr.title,
            "source_branch": pr.branch,
            "target_branch": pr.base_branch,
            "head_sha": pr.head_sha,
            "merge_commit_sha": merge_sha,
            "commit_shas": [],
        }
        record["source"] = source
        change_id = ChangeIdPolicy.extract(pr)
        record["change_id"] = change_id
        commit_records = github.get_pull_request_commits(pr)
        commit_shas = ChangeIdPolicy.validate_commits(commit_records, change_id)
        source["commit_shas"] = commit_shas
        record.update(result="PASS", change_id=change_id, source=source)
        resolved_outputs = {
            "change_id": change_id,
            "pull_request_number": str(pull_request_number),
            "merge_commit_sha": merge_sha,
        }
        exit_code = 0
    except ValidationFailure as exc:
        record.update(
            result=exc.result,
            reason={"code": exc.code, "message": str(exc)},
        )
        exit_code = 1
    except Exception as exc:  # Avoid leaking access tokens or API response data.
        record["reason"] = {
            "code": "DEPLOYMENT_SOURCE_ERROR",
            "message": f"Could not resolve deployment source ({type(exc).__name__}).",
        }
        exit_code = 1

    try:
        output_path.write_text(
            json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        if exit_code == 0:
            output_file = settings.require("GITHUB_OUTPUT")
            with open(output_file, "a", encoding="utf-8") as stream:
                for key, value in resolved_outputs.items():
                    stream.write(f"{key}={value}\n")
    except (OSError, ValidationFailure) as exc:
        print(
            f"Could not persist deployment source evidence ({type(exc).__name__}).",
            file=sys.stderr,
        )
        return 1

    if record["reason"]:
        print(
            f"Deployment source validation failed: {record['reason']['code']}: "
            f"{record['reason']['message']}",
            file=sys.stderr,
        )
    return exit_code


if __name__ == "__main__":
    sys.exit(run())
