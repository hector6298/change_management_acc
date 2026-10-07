# Block 3 — Databricks Deployment Evidence

## Goal

Record what the approved CI/CD workflow attempted to deploy to Databricks,
which exact source revision and target it used, what Databricks resources it
reported creating/updating, and whether the deployment step succeeded.

This block extends the Block 1/2 chain:

```text
Jira Change Request
  → GitHub PR and merged commit
  → CI/CD workflow run
  → Databricks deployment operation
  → Databricks resource IDs and deployment result
```

The Jira key remains the business correlation key. Use native immutable IDs for
the other systems: repository, PR, commit SHA, CI run, Databricks workspace,
bundle/target, and Databricks resource IDs. Do not generate another change
management ID.

## Design decisions

1. **Use Declarative Automation Bundles (formerly Asset Bundles) for the
   initial Databricks deployment path.** Keep target configuration in version
   control and deploy with the Databricks CLI from CI/CD.
2. **Use GitHub Actions as the initial runner only if that is the project's
   selected CI/CD system.** Keep the evidence schema runner-neutral so another
   CI/CD product can emit the same contract.
3. **Revalidate before production deployment.** The workflow must bind to the
   approved PR's merge commit and re-check Jira approval immediately before
   deployment. A previous PR check is not sufficient because approval may have
   changed since it ran.
4. **Separate deploy result from runtime result.** `bundle deploy` success means
   configuration/resources were applied. A subsequent job run or app health
   check is a separate result and must have its own native run identifier.
5. **Treat this as deployer-reported evidence.** A CI record proves what the
   deployment path reported, not independent Databricks observation. Block 6
   will reconcile it against Databricks system tables and audit events.
6. **Never rely on a mutable resource tag as the historical deployment log.**
   Tags may help classify managed resources, but the durable event record must
   live outside the currently deployed resource configuration.

Databricks documents that Bundles track deployed resource IDs in workspace
state, and `databricks bundle summary` reports bundle/target identity and
resource links. Bundle deployment commands also expose deployment state and
operation details. These are useful primary identifiers for the evidence
record, where supported by the installed CLI version.

## Proposed execution flow

### Production deployment

1. Start only from a protected production branch after the Block 2 required
   check passes. The workflow must run against the merge commit SHA, not a
   mutable branch name.
2. Resolve the Jira key from the validated PR/commit evidence. Confirm the key,
   PR, merge SHA, and repository are consistent with the approved change.
3. Fetch the Jira issue again and verify it still exists, is the configured
   Change Request type, targets Production, and is approved. Preserve the
   approval state and observation timestamp in the deployment record.
4. Authenticate to Databricks as a dedicated deployment service principal.
   Prefer workload identity federation/OIDC where the cloud and CI/CD setup
   supports it; otherwise use a short-lived secret from the CI secret store.
   Use separate identities/permissions for non-production and production.
5. Install or select a pinned Databricks CLI version. Record the exact version.
6. Run `databricks bundle validate --target prod` and capture its outcome.
   Validation failure prevents deployment.
7. Build/publish an immutable artifact when the bundle includes buildable
   outputs (for example a wheel). Record its SHA-256 digest and artifact URI.
8. Run `databricks bundle deploy --target prod`; capture start/end time, exit
   code, command output summary, and Databricks resource IDs/links from the
   bundle summary or deployment operation API/CLI.
9. If this change requires execution, run the deployed resource as a distinct
   step and capture its `job_run_id` or app health-check result separately.
   Do not mark the deploy itself as an execution success.
10. Emit and retain the versioned deployment evidence record, even on failure.
    Link it to the GitHub workflow run and PR/check evidence.

Do not run the production deployment for a PR `pull_request` event. Production
deployment should occur after merge in a trusted `push`/workflow-dispatch path
with protected GitHub environment approval if that is part of the customer's
release policy.

### Development/test deployment

Use separate Bundle targets and workspace environments. The Jira Change ID may
be absent for genuinely non-governed development work, but if one is supplied,
preserve it and validate it consistently. A development deployment must not
share production credentials, workspace target, or environment approval.

## Identity and metadata propagation

| Value | Source | Propagation/use |
|---|---|---|
| `change_id` | Jira issue key, validated in Block 2 | CI environment/context and evidence; never mint another change ID |
| `repository` | GitHub repository | Evidence field |
| `pull_request` | GitHub PR | Evidence link to authorization/code review |
| `merge_commit_sha` | GitHub merge event / API | Exact deployed source revision |
| `ci_run_id` | CI/CD platform | Stable identifier for this deployment attempt; not a business change ID |
| `environment` | Protected CI environment + Bundle target | Must agree (`production` ↔ `prod`) |
| `bundle_name`, `bundle_target` | `databricks.yml` and CLI | Namespaced deployment identity |
| `workspace_id`, `workspace_host` | Databricks target/API | Identifies deployment destination |
| `deployment_operation_id` | Bundle deployment API/CLI when available | Native Databricks deployment operation reference |
| `resource_ids` | Bundle summary/deployment state/API | Jobs, pipelines, apps, or other deployed assets |
| `artifact_digest` | CI build output | Cryptographic link to the packaged artifact, when applicable |
| `job_run_id` | Jobs run response, if launched | Separate runtime execution evidence |

The CI run ID is a deployment-attempt identifier, not a replacement Change ID.
Retries should retain the Jira key and commit SHA but get their own CI run and,
where available, Databricks operation IDs. Keep a failed attempt as evidence;
do not overwrite it with a later successful retry.

Bundles support tags on supported resources. A stable tag such as
`managed_by=change-assurance` or a service/team tag can help identify managed
assets. A per-change tag is optional metadata only: the current resource
configuration may overwrite it on the next deployment, so it cannot serve as
the historical record of all changes.

## Deployment evidence contract

Emit one immutable record per deployment attempt, including validation or
deployment failures. Suggested shape:

```json
{
  "schema_version": "1.0",
  "event_type": "databricks_deployment_attempt",
  "deployment_attempt_id": "github:org/repo:run-987654:attempt-2",
  "change_id": "DEMO-12",
  "authorization": {
    "jira_issue_url": "https://example.atlassian.net/browse/DEMO-12",
    "approval_state": "Approved",
    "approved_by": "approver-account-id",
    "approved_at": "2026-10-06T21:40:00Z",
    "revalidated_at": "2026-10-06T22:10:00Z"
  },
  "source": {
    "repository": "org/demo",
    "pull_request": 12,
    "merge_commit_sha": "abc123def456",
    "branch": "main"
  },
  "ci": {
    "provider": "github_actions",
    "run_id": "987654",
    "run_attempt": 2,
    "run_url": "https://github.com/org/demo/actions/runs/987654",
    "started_at": "2026-10-06T22:10:00Z",
    "completed_at": "2026-10-06T22:14:00Z"
  },
  "databricks": {
    "workspace_id": "6051000018419999",
    "workspace_host": "https://example.cloud.databricks.com",
    "cli_version": "1.x.y",
    "bundle_name": "risk-platform",
    "bundle_target": "prod",
    "deployment_operation_id": "deployments/abc",
    "validation_result": "SUCCESS",
    "deployment_result": "SUCCESS",
    "resources": [
      {"resource_type": "job", "resource_key": "score_customer", "resource_id": "206000809187888", "url": "https://example.cloud.databricks.com/jobs/206000809187888"}
    ],
    "artifact_digest": "sha256:..."
  },
  "execution": {
    "result": "NOT_RUN",
    "job_run_id": null,
    "health_check_result": null
  },
  "reason_codes": [],
  "policy_version": "1"
}
```

Use UTC timestamps and stable reason codes. Redact tokens and avoid recording
full environment variables, secrets, or unnecessary personal data. Store the
record in an access-controlled CI artifact initially and export it to a durable
evidence destination before artifact retention expires. A future Databricks
pipeline can ingest these immutable events into bronze evidence.

Suggested result vocabulary:

- `validation_result`: `SUCCESS`, `FAILURE`, `NOT_RUN`
- `deployment_result`: `SUCCESS`, `FAILURE`, `NOT_RUN`
- `execution.result`: `SUCCESS`, `FAILURE`, `NOT_RUN`, `NOT_APPLICABLE`

These are separate control results. Missing deployment evidence is not the same
as a failed deployment.

## Minimal CI/CD layout (proposal only)

```text
.github/workflows/
  deploy-databricks.yml
databricks.yml
resources/
  jobs.yml
  pipelines.yml
deployment-evidence/
  schema.json
```

The workflow should call reusable steps/scripts for Jira revalidation, bundle
validation/deployment, resource summary, and evidence serialization. Keep the
policy and evidence schema versioned. Do not put Jira credentials or
Databricks secrets in `databricks.yml`.

## Relationship to later blocks

```text
Block 3 deployer-reported record
  ├── Jira key + approval snapshot
  ├── GitHub PR + exact merged commit
  ├── CI run + Bundle target/operation
  └── Databricks resource IDs
            │
            ├── Block 4: ingest this record into bronze evidence
            ├── Block 5: normalize deployment/change records in the ledger
            ├── Block 6: compare the expected deployment with independently
            │            observed Databricks activity and audit events
            └── Block 7: map deployed assets to Unity Catalog lineage/impact
                         for Block 8's compliance dashboard
```

For Block 6, use the workspace/resource/run IDs and time interval to help
reconcile the declared deployment against observed platform activity. Do not
make a CI-generated record the only proof that Databricks activity occurred.
System-table rows may be delayed and have defined retention/availability
windows; ingestion/reconciliation policy belongs to the later evidence-pipeline
block.

## Demo acceptance criteria

- A production workflow refuses to deploy without a current approved Jira
  Change Request and a validated merged commit.
- The record identifies the exact Jira key, PR, merge SHA, CI attempt, workspace,
  Bundle target, and Databricks resources.
- Validation failure, deployment failure, success, and retry are represented
  as distinct immutable attempts.
- A deploy with no runtime execution says `NOT_RUN`; it is not reported as a
  successful job execution.
- The evidence artifact contains no credentials and can be ingested later
  without scraping CI logs or the Jira UI.
