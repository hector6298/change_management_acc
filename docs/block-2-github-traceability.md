# Block 2 — GitHub Change Traceability, using Jira Development

## Decision

Use Jira's connected development tools as the native cross-linking and review
experience. Keep the Jira issue key from Block 1 as the single correlation ID.
Put that same key into the GitHub branch, pull request title, and commit
messages so Jira can associate the development records with the Change Request.

This avoids building a second link registry or replacing Jira's development
panel. It does **not** make the Jira panel a production merge control or a
complete compliance evidence store. A GitHub check still validates the PR and
Jira approval; branch protection still decides whether merge is allowed.

## Jira/GitHub setup

1. Ask a Jira admin to connect the Jira site to GitHub and authorize the
   organization/repositories containing the demo code. Grant the team the
   Jira permission to view development information.
2. Confirm the repository is connected to the intended Jira software project.
3. Open a Change Request in Jira and use its actual uppercase issue key,
   e.g. `DEMO-12`, in all development references below.
4. Push a branch/commit and open a PR. Allow a few minutes for Jira to sync,
   then confirm the Development panel shows the expected branch, commit, and PR.

Atlassian documents that PRs link when the issue key is in the PR title **or**
source branch, and commits link when the key is in the commit message. Therefore
the recommended accelerator convention is intentionally redundant:

```text
Branch:       DEMO-12-add-risk-feature
Commit:       DEMO-12: add risk feature
PR title:     DEMO-12 Add risk feature
PR body:      Change-ID: DEMO-12
```

The PR title and body marker serve different practical purposes: the title
links natively in Jira, while the exact body marker is easy for an Action to
parse. The branch and commit conventions help Jira associate the full code
history. All four must use the same one Jira issue key. Atlassian notes that
keys must be correctly formatted in uppercase and that initial sync can take
several minutes.

Source: [Reference work items in your development spaces — Atlassian Support](https://support.atlassian.com/jira-software-cloud/docs/reference-issues-in-your-development-work/).

## What Jira Development provides

| Artifact | Jira association convention | What we use it for |
|---|---|---|
| Branch | Jira key in branch name | Navigation and a convention CI can check |
| Commit | Jira key in commit message | Commit-to-change traceability |
| Pull request | Jira key in title or source branch; use both | Native PR link plus deterministic convention |
| Approval | Jira Change Request workflow/fields from Block 1 | Authoritative authorization state, validated by CI |
| GitHub required check | Workflow job result for the PR | Merge gate when configured as required |

Jira's development panel is a projection of connected development-tool data.
It helps people navigate from the change to code and back. The Block 2 evidence
record should still preserve stable identifiers and the validation result; do
not assume that a visible Jira link proves approval, that all PR commits were
reviewed, or that a production deployment occurred.

Atlassian's reference page documents deployment linking for Bamboo and
Bitbucket Pipelines. Do not assume that a GitHub Actions deployment will appear
as a Jira deployment merely because a Jira key is present. Deployment evidence
is a later block and must be explicitly integrated and independently reconciled.

## Implemented GitHub Action

The starter implementation is:

- [`.github/workflows/change-assurance.yml`](../.github/workflows/change-assurance.yml)
  — required-check workflow on PR open/edit/update/reopen events.
- [`src/change_assurance/action/github_action.py`](../src/change_assurance/action/github_action.py)
  — small workflow coordinator and module entry point.
- [`src/change_assurance/clients/github.py`](../src/change_assurance/clients/github.py)
  — reads PR commit metadata from GitHub.
- [`src/change_assurance/clients/jira.py`](../src/change_assurance/clients/jira.py)
  — reads Jira issue fields and normalizes custom-field values.
- [`src/change_assurance/policy/validation.py`](../src/change_assurance/policy/validation.py)
  — enforces PR Change-ID consistency and Jira approval requirements; defines
  the normalized Jira snapshot dataclass.
- [`src/change_assurance/models/`](../src/change_assurance/models/)
  — shared settings, PR, evidence, change identity, and validation-error models.
- [`src/change_assurance/reporting/workflow.py`](../src/change_assurance/reporting/workflow.py)
  — writes evidence JSON and a concise Actions summary.
- [`schemas/github-change-validation.schema.json`](../schemas/github-change-validation.schema.json)
  — versioned evidence contract.

The workflow invokes the package with `PYTHONPATH=src python3 -m
change_assurance.action.github_action`; `github_action.py` only coordinates the
packages and sets the process exit code.

The workflow is named **Change assurance** and its job is named **Jira
validation**. GitHub displays the required check as
**`Change assurance / Jira validation`**. The workflow job result is the check;
the implementation does not create a separate GitHub App Check Run. Each
attempt writes a JSON evidence file and uploads it as a 30-day workflow
artifact. Export it to durable storage before the retention period expires if
you need long-term audit evidence.

The workflow uses `pull_request_target` so it can read Jira credentials for
fork PRs. This event runs with access to base-repository secrets, so the
workflow checks out only the PR target branch's base SHA and runs that trusted
validator. It does not check out, install, or execute pull-request code. Keep
that restriction if the workflow is changed. GitHub's security guidance warns
that executing PR code in a `pull_request_target` workflow can expose secrets:
[Securely using `pull_request_target`](https://docs.github.com/en/actions/reference/security/securely-using-pull_request_target).

### Workflow at a glance

```text
PR opened / edited / updated / reopened
                  │
                  ▼
       Check trusted target-branch code
                  │
       Production target branch?
          ┌───────┴────────┐
         No               Yes
          │                 │
       SKIPPED       Parse Change-ID from PR body
                            │
              Compare title + branch + commit keys
                            │
                 Read mapped Jira fields
                            │
             Approved for Production?
                   ┌────────┴────────┐
                  Yes                No/error
                   │                   │
              PASS check        FAILURE/ERROR check
                   └─────────┬─────────┘
                             ▼
               Write summary + JSON evidence
```

1. GitHub starts the workflow for the listed pull-request events. The policy
   checks the target/base branch against `CHANGE_ASSURANCE_PRODUCTION_BRANCHES`.
2. For a production-bound PR, it requires one `Change-ID: KEY` body line and
   the same key at the start of the title and source branch. It reads all PR
   commits from GitHub and requires each non-merge commit to reference only
   that key.
3. It calls Jira Cloud REST API v3 to read the configured fields and paginated
   issue changelog. It checks issue type, production target, required fields,
   and the configured approval value, then derives the approval actor/time from
   the latest Approval State field change. Workflow status is captured for
   evidence but does not decide approval.
4. The script writes a human-readable Actions summary and a versioned evidence
   JSON record. The workflow uploads the record even if validation fails.
5. The Python process exits `0` only for `PASS` or `SKIPPED`. `FAILURE` and
   `ERROR` exit non-zero, causing the workflow job check to fail.

### Result summary

| Result | Meaning | Workflow check |
|---|---|---|
| `PASS` | PR references are consistent and Jira confirms production approval | Succeeds |
| `FAILURE` | Missing/conflicting Change ID, Jira issue/policy mismatch, or unapproved change | Fails |
| `ERROR` | Configuration, permission, or API problem prevented validation | Fails closed |
| `SKIPPED` | PR targets a branch outside the configured production patterns | Succeeds; production approval policy was not evaluated |

The check summary includes the result, Change ID, PR/target branch, head SHA,
Jira link and observed approval/status when available, plus a reason code and
remediation message for failures. The evidence record additionally captures
workflow run ID/attempt, commit SHAs, and the Jira approval snapshot.

### Contributor workflow

For a production-bound PR, use the Jira key consistently:

```text
Branch:       DEMO-12-add-risk-feature
Commit:       DEMO-12: add risk feature
PR title:     DEMO-12 Add risk feature
PR body:      Change-ID: DEMO-12
```

After opening or updating the PR, wait for **Change assurance / Jira
validation**. If it fails, open the Actions summary, correct the referenced
field or Jira approval, and push/update the PR. Once the check passes, normal
review and branch protection rules still apply.

### Configure GitHub

1. Add the workflow and validator to the default/target branch. A
   `pull_request_target` workflow runs the trusted base-repository workflow;
   the validator is loaded from the target branch's base commit.
2. In repository or organization **Actions variables**, set:

   | Variable | Example | Required |
   |---|---|---|
   | `CHANGE_ASSURANCE_PRODUCTION_BRANCHES` | `main,release/*` | No; defaults to `main` |
   | `CHANGE_REQUEST_CONFIG` | `config/change-request.yml` | No; path to the trusted YAML contract |
   | `JIRA_CLOUD_ID` | Cloud ID of the Jira site | Yes |

   Replace each sample custom-field ID in `config/change-request.yml` with the
   actual field ID in your Jira site. Display names alone are not enough for
   the REST API mapping. Get `JIRA_CLOUD_ID` by opening
   `https://<your-jira-site>.atlassian.net/_edge/tenant_info` and copying the
   returned `cloudId` value. See [Cloud ID lookup instructions](how-it-works-and-run.md#create-an-atlassian-service-account).
   Use branch names that match your actual protected production branches.
3. Create an Atlassian service account, grant it read access to the Change
   Request project, and create an OAuth 2.0 credential with the `read:jira-work`
   scope. Add its client ID and secret as `JIRA_OAUTH_CLIENT_ID` and
   `JIRA_OAUTH_CLIENT_SECRET` Actions secrets. See [service account setup](how-it-works-and-run.md#create-an-atlassian-service-account).
   The Action exchanges these credentials using the client-credentials grant,
   then calls Jira Cloud REST API v3 through the Atlassian API gateway using
   the site's Cloud ID and the returned bearer token. It does not create or
   update Jira issues.
4. The workflow needs only `contents: read` and `pull-requests: read` on
   `GITHUB_TOKEN` to fetch the PR and its commits.
5. Open a sample PR to a configured production branch. After the workflow has
   reported the check once, add **`Change assurance / Jira validation`** to the
   required checks in branch protection/rulesets. Protect the workflow file and
   policy variables with the same review controls as production deployment
   policy.

The Action expects Jira values to meet the configured contract:

- The PR target branch matches a configured production branch; this is decided
  from GitHub metadata before Jira is queried.
- `Approval State` equals `jira_fields.approval_state.approved_value` in the
  YAML contract.
- The latest Approval State changelog entry matches the current value and
  records an actor and timestamp. The timestamp cannot be in the future.
- Every Jira field configured with `required: true` has a value.

For Jira Cloud, the Action exchanges the service account's OAuth client
credentials for an access token, then uses it over HTTPS through
`api.atlassian.com`. See Atlassian's official
[Jira Cloud issue REST API](https://developer.atlassian.com/cloud/jira/platform/rest/v3/api-group-issues/).

### What the check enforces

For production-bound PRs, the validator requires a single `Change-ID: KEY`
body line, the same key at the start of the PR title and branch, and the key in
each non-merge commit message. It then confirms that Jira returns the same key,
the configured issue type and production target, the configured approval
value, all configured mandatory fields, and the approver/time from the field changelog. Jira API
outages or permission failures are reported as `ERROR` and block the required check; missing/invalid/unapproved
changes are `FAILURE`. PRs targeting other branches report `SKIPPED` and do not
require Jira approval under this initial policy.

Every run writes `change-assurance-evidence.json`; failed runs still upload it.
The record contains the Jira state observed at validation time and GitHub PR,
head SHA, and commit IDs. It does not prove a Databricks deployment happened.

## PR and validation contract

For every governed production-bound PR:

1. Source branch includes exactly one relevant Jira Change Request key using
   the repository's configured project-key pattern.
2. PR title begins with that same key, for example `DEMO-12 Add risk feature`.
3. PR body contains exactly one structured line: `Change-ID: DEMO-12`.
4. Every commit intended to be part of the change includes that same key in its
   commit message. Merge commits can be handled by repository-specific policy;
   do not count them as a replacement for the underlying commits.
5. The Action checks format and consistency, fetches that Jira issue, verifies
   it is the configured Change Request type and verifies its production
   approval state according to Block 1.
6. GitHub reports the workflow job result as the PR check. Configure branch
   protection/rulesets to require `Change assurance / Jira validation` on
   production branches.

The CI check must not trust the Jira Development panel as its validation API.
It should read PR/branch/commit metadata from GitHub and fetch the authoritative
change status/approval from Jira. If Jira is unavailable, report validation as
unavailable/error rather than treating the request as valid or unapproved.

This strict convention provides deterministic evidence for the accelerator,
even though Jira natively accepts a narrower set of references. Development or
other non-production work can omit the governed change marker only when policy
confirms it cannot merge/deploy to production.

## Evidence emitted by Block 2

One versioned result per validation attempt, containing at least:

```json
{
  "schema_version": "1.0",
  "event_type": "github_change_validation",
  "observed_at": "2026-10-06T22:14:00Z",
  "result": "PASS",
  "change_id": "DEMO-12",
  "jira": {
    "issue_type": "Change Request",
    "status": "Approved",
    "approval_state": "Approved",
    "approved_by": "approver-account-id",
    "approved_at": "2026-10-06T21:40:00Z",
    "risk": "Medium",
    "required_fields": {
      "approval_state": "Approved",
      "risk": "Medium"
    },
    "issue_url": "https://example.atlassian.net/browse/DEMO-12"
  },
  "github": {
    "repository": "org/demo",
    "pull_request": 12,
    "pull_request_url": "https://github.com/org/demo/pull/12",
    "title": "DEMO-12 Add risk feature",
    "branch": "DEMO-12-add-risk-feature",
    "base_branch": "main",
    "head_sha": "abc123",
    "workflow_run_id": "987654",
    "workflow_run_attempt": 1,
    "commit_shas": ["abc123"],
    "is_production_bound": true
  },
  "reason_codes": [],
  "policy_version": "1",
  "validator_version": "1.0"
}
```

Capture the observed Jira approval state and time as a snapshot, along with the
PR/head SHA and check result. Do not copy Jira descriptions/comments or tokens
into the evidence. Store the record as a GitHub workflow artifact initially;
later ingestion can collect it or query GitHub/Jira APIs into Databricks bronze
evidence. The PR/commit identifiers make records joinable without scraping the
Jira UI.

## Later evidence joins

```text
Jira Change Request (change_id)
          │
          ├── Jira Development panel: linked branch / commits / PR
          │
          ├── GitHub PR + commit + required-check evidence (Block 2)
          │
          └── CI/CD deployment metadata (later block)
                       │
                       ├── Databricks system tables and audit events
                       ├── Unity Catalog lineage and governed assets
                       └── reconciliation → Change Ledger → dashboard
```

Databricks ingestion should preserve source-native IDs (Jira key, repository,
PR number, commit SHA, workflow run ID, deployment ID, Databricks event ID) and
timestamps. The Jira key is the primary business correlation key, while native
IDs distinguish each artifact and support independent reconciliation.

## Demo acceptance criteria

- Connected Jira issue shows the expected branch, commit, and PR after sync.
- A PR with matching title/body/branch/commit key and approved Jira request
  passes the required check.
- Missing, malformed, conflicting, nonexistent, wrong-type, or unapproved keys
  fail the check with a useful reason.
- Jira API outage produces an error/unavailable result.
- A merge to the protected production branch is blocked if the required check
  fails or is absent.
