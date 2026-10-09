"""Resolve and validate the immutable commit set for a published release."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
from typing import Any

from ..clients.github import GitHubClient
from ..models.action import ActionSettings, ValidationFailure
from ..policy.validation import ChangeIdPolicy


def _parse_time(value: Any) -> datetime | None:
    """Parse a GitHub timestamp into an aware datetime."""
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _base_release(
    releases: list[dict[str, Any]], current_tag: str, current_time: datetime,
    initial_base_tag: str,
) -> str:
    """Select the immediately preceding published release or configured baseline."""
    published = [
        item for item in releases
        if not item.get("draft") and not item.get("prerelease")
        and isinstance(item.get("tag_name"), str)
        and _parse_time(item.get("published_at")) is not None
    ]
    current = next((item for item in published if item["tag_name"] == current_tag), None)
    if current is None:
        raise ValidationFailure(
            "RELEASE_NOT_PUBLISHED", "The triggering tag is not a published GitHub Release."
        )
    ordered = sorted(published, key=lambda item: _parse_time(item["published_at"]) or current_time)
    newer = [item for item in ordered if (_parse_time(item["published_at"]) or current_time) > current_time]
    if newer:
        raise ValidationFailure(
            "RELEASE_NOT_LATEST",
            "Only the most recently published release can start a deployment.",
        )
    earlier = [
        item for item in ordered
        if item["tag_name"] != current_tag
        and (_parse_time(item["published_at"]) or current_time) < current_time
    ]
    if earlier:
        return str(earlier[-1]["tag_name"])
    if initial_base_tag and initial_base_tag != current_tag:
        return initial_base_tag
    raise ValidationFailure(
        "RELEASE_BASELINE_MISSING",
        "No earlier published release exists. Set CHANGE_ASSURANCE_BASE_RELEASE_TAG to the baseline tag for the first release.",
    )


def run() -> int:
    """Write a validated release manifest for downstream review and deployment."""
    settings = ActionSettings()
    output_path = Path(settings.get("DEPLOYMENT_SOURCE_PATH", "release-source.json"))
    observed_at = datetime.now(timezone.utc).isoformat()
    record: dict[str, Any] = {
        "schema_version": "1.0",
        "observed_at": observed_at,
        "result": "ERROR",
        "change_id": None,
        "change_ids": [],
        "source": None,
        "reason": None,
    }
    resolved: dict[str, str] = {}
    exit_code = 1
    try:
        repository = settings.require("GITHUB_REPOSITORY")
        release_tag = settings.require("RELEASE_TAG")
        release_time = _parse_time(settings.require("RELEASE_PUBLISHED_AT"))
        if release_time is None:
            raise ValidationFailure("RELEASE_TIME_INVALID", "GitHub did not provide a valid release publication time.")
        github = GitHubClient(settings)
        releases = github.get_releases(repository)
        base_tag = _base_release(
            releases,
            release_tag,
            release_time,
            settings.get("CHANGE_ASSURANCE_BASE_RELEASE_TAG"),
        )
        if base_tag.startswith("-") or release_tag.startswith("-"):
            raise ValidationFailure("RELEASE_TAG_INVALID", "Release tags cannot begin with a hyphen.")

        release_sha = github.get_ref_commit(repository, release_tag)
        commits = github.compare_commits(repository, base_tag, release_tag)
        commit_shas, identities = ChangeIdPolicy.validate_release_commits(commits)
        change_ids = sorted({identity["change_id"] for identity in identities})
        source = {
            "repository": repository,
            "release_tag": release_tag,
            "base_release_tag": base_tag,
            "release_commit_sha": release_sha,
            "commit_shas": commit_shas,
            "commit_identities": identities,
            "change_ids": change_ids,
        }
        record.update(
            result="PASS", change_id=None, change_ids=change_ids, source=source
        )
        resolved = {
            "release_tag": release_tag,
            "release_commit_sha": release_sha,
            "change_ids_json": json.dumps(change_ids, separators=(",", ":")),
        }
        exit_code = 0
    except ValidationFailure as exc:
        record.update(
            result=exc.result,
            reason={"code": exc.code, "message": str(exc)},
        )
    except Exception as exc:  # Keep credentials and API response data out of logs.
        record["reason"] = {
            "code": "RELEASE_SOURCE_ERROR",
            "message": f"Could not resolve or validate the release ({type(exc).__name__}).",
        }

    try:
        output_path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        if exit_code == 0:
            output_file = settings.require("GITHUB_OUTPUT")
            with open(output_file, "a", encoding="utf-8") as stream:
                for key, value in resolved.items():
                    stream.write(f"{key}={value}\n")
    except (OSError, ValidationFailure) as exc:
        print(f"Could not persist release source evidence ({type(exc).__name__}).", file=sys.stderr)
        return 1

    if record["reason"]:
        print(f"Release validation failed: {record['reason']['code']}: {record['reason']['message']}", file=sys.stderr)
    return exit_code


if __name__ == "__main__":
    sys.exit(run())
