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
   approved release commit and re-check every Jira approval immediately before
   deployment. A previous PR check is not sufficient because approval may have
   changed since it ran.
4. **Treat a release as the deployment unit.** Resolve the exact commit range
   since the previous release, require one Jira key on every commit,
   validate every distinct change request, and publish that manifest for review.
   A feature-at-a-time release is the same process with one Jira key.
5. **Separate deploy result from runtime result.** `bundle deploy` success means
   configuration/resources were applied. A subsequent job run or app health
   check is a separate result and must have its own native run identifier.
6. **Treat this as deployer-reported evidence.** A CI record proves what the
   deployment path reported, not independent Databricks observation. Block 6
   will reconcile it against Databricks system tables and audit events.
7. **Never rely on a mutable resource tag as the historical deployment log.**
   Tags may help classify managed resources, but the durable event record must
   live outside the currently deployed resource configuration.

Databricks documents that Bundles track deployed resource IDs in workspace
state, and `databricks bundle summary` reports bundle/target identity and
resource links. Bundle deployment commands also expose deployment state and
operation details. These are useful primary identifiers for the evidence
record, where supported by the installed CLI version.

## Proposed execution flow

### Production deployment

1. Publish a GitHub Release after the release commit set is assembled. The
   workflow resolves its tag to an immutable commit SHA and compares it with
   the preceding published release (or the configured initial baseline tag).
2. Validate every commit in that range, including merge commits. Each must
   reference exactly one configured Jira issue key, and each distinct Jira
   Change Request must pass the current Block 1 approval policy.
3. Publish the release manifest and Jira approval snapshot as a CI artifact
   and workflow summary. A human release approver reviews this complete change
   set using the protected `databricks-dev` GitHub environment gate. GitHub
   Actions is the source of truth for the gatekeeper's identity and decision;
   the final evidence records that environment protection passed and links to
   the run's deployment history.
4. After the gate is approved, re-fetch and validate every Jira issue again.
   This catches approval changes while the release waited for human review.
5. Check out the exact release SHA saved in the validated manifest. Never
   resolve the tag again after approval because a tag can be moved.
6. Authenticate to Databricks as a dedicated deployment service principal
   using OAuth machine-to-machine (M2M) client credentials. Store its client
   secret in the CI secret store and use separate identities/permissions for
   non-production and production.
7. Install or select a pinned Databricks CLI version. Record the exact version.
8. Run `databricks bundle validate --target prod` and capture its outcome.
   Validation failure prevents deployment.
9. Build/publish an immutable artifact when the bundle includes buildable
   outputs (for example a wheel). Record its SHA-256 digest and artifact URI.
10. Run `databricks bundle deploy --target prod`; capture start/end time, exit
   code, command output summary, and Databricks resource IDs/links from the
   bundle summary or deployment operation API/CLI.
11. If this change requires execution, run the deployed resource as a distinct
   step and capture its `job_run_id` or app health-check result separately.
   Do not mark the deploy itself as an execution success.
12. Emit and retain the versioned deployment evidence record, even on failure.
    Link it to the GitHub workflow run and PR/check evidence.

Do not deploy on a PR event or on every merge. Deploy after a release candidate
has been assembled and reviewed, with a protected GitHub environment approval
before any Databricks operation.

### Development/test deployment

Use separate Bundle targets and workspace environments. The Jira Change ID may
be absent for genuinely non-governed development work, but if one is supplied,
preserve it and validate it consistently. A development deployment must not
share production credentials, workspace target, or environment approval.

## Identity and metadata propagation

| Value | Source | Propagation/use |
|---|---|---|
| `change_id` / `change_ids` | Jira issue key(s), validated in Blocks 1/2 | One ticket for a single-feature release or a ticket set for a broader release; never mint another change ID |
| `release_tag`, `base_release_tag` | GitHub Release and preceding published release | Defines the reviewed commit interval |
| `commit_identities` | GitHub compare API plus configured Jira key pattern | Complete commit-to-ticket manifest reviewed before deployment |
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
  "schema_version": "1.1",
  "event_type": "databricks_deployment_attempt",
  "deployment_attempt_id": "github:org/repo:run-987654:attempt-2",
  "change_id": null,
  "authorization": {
    "jira_issue_url": null,
    "approval_state": "Approved",
    "approved_by": null,
    "approved_at": null,
    "revalidated_at": "2026-10-06T22:10:00Z",
    "change_requests": [
      {
        "change_id": "DEMO-12",
        "result": "PASS",
        "jira_issue_url": "https://example.atlassian.net/browse/DEMO-12",
        "approval_state": "Approved",
        "approved_by": "approver-account-id",
        "approved_at": "2026-10-06T21:40:00Z",
        "revalidated_at": "2026-10-06T22:10:00Z"
      }
    ]
  },
  "source": {
    "repository": "org/demo",
    "pull_request": null,
    "merge_commit_sha": null,
    "branch": "v1.2.0",
    "release_tag": "v1.2.0",
    "base_release_tag": "v1.1.0",
    "release_commit_sha": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "commit_shas": ["bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"],
    "change_ids": ["DEMO-12"],
    "commit_identities": [
      {
        "commit_sha": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
        "change_id": "DEMO-12"
      }
    ]
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
  "release_gate": {
    "environment": "databricks-dev",
    "protection_result": "PASSED",
    "workflow_run_url": "https://github.com/org/demo/actions/runs/987654"
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

## Implemented reusable components

Block 3 now defines and emits a runner-neutral deployment-attempt record:

- [`schemas/databricks-deployment-attempt.schema.json`](../schemas/databricks-deployment-attempt.schema.json)
  defines the versioned JSON contract.
- [`src/change_assurance/action/deployment_preflight.py`](../src/change_assurance/action/deployment_preflight.py)
  re-reads the Jira Change Request and approval history immediately before a
  production deployment. It writes `deployment-authorization.json` and exits
  nonzero unless the current configured Jira policy passes.
- [`src/change_assurance/action/deployment_source.py`](../src/change_assurance/action/deployment_source.py)
  resolves a merged PR from GitHub, checks its target branch and Change ID
  contract, and records the exact merge commit.
- [`src/change_assurance/action/release_source.py`](../src/change_assurance/action/release_source.py)
  resolves a GitHub Release against the preceding release, validates the
  complete commit-to-ticket manifest, and pins the release SHA for deployment.
- [`src/change_assurance/action/deployment_evidence.py`](../src/change_assurance/action/deployment_evidence.py)
  combines source, Jira, CI, and Databricks bundle-summary metadata into
  `databricks-deployment-evidence.json`, including failed attempts.
- [`src/change_assurance/models/deployment.py`](../src/change_assurance/models/deployment.py)
  and [`src/change_assurance/reporting/deployment.py`](../src/change_assurance/reporting/deployment.py)
  define and persist the evidence record.
- [`.github/workflows/deploy-databricks-sample.yml`](../../.github/workflows/deploy-databricks-sample.yml)
  connects those components to the development sample bundle.

The release workflow validates each Jira key found on the commit range and then
revalidates every request after the human environment approval. It stores the
exact release SHA and commit-to-ticket mapping in a reviewable manifest.

Run the Jira preflight before requesting human release approval and again after
the gate, immediately before Databricks validation and deployment. Run the
evidence writer afterward with an unconditional step so failures are still
captured. The sample workflow starts when a GitHub Release is published. It
compares the release tag to its previous published release, validates every
commit and distinct Jira approval, uploads the candidate manifest for review,
waits for a required reviewer on the `databricks-dev` environment, then checks
out the exact release SHA, deploys the sample bundle, runs the sample job, and
uploads deployment evidence. The sample scripts overwrite two demo tables in
the configured development schema.

### Configure GitHub and Databricks

1. Configure the repository Jira variable and secrets described in the Block
   2 guide: `JIRA_CLOUD_ID`, `JIRA_OAUTH_CLIENT_ID`, and
   `JIRA_OAUTH_CLIENT_SECRET`. The validation job runs before the Databricks
   environment gate, so the Jira credentials must be repository-level secrets.
   Keep the change-request YAML in `.cms/config/`.
2. In the Databricks account, create a service principal for this deployment
   and assign it to the target workspace. Create an OAuth secret for that
   service principal. The principal needs permission to deploy the sample job
   and create or replace tables in the development catalog and schema. See
   Databricks' official [OAuth M2M service principal guide](https://docs.databricks.com/aws/en/dev-tools/auth/oauth-m2m)
   and [CLI authentication guide](https://docs.databricks.com/aws/en/dev-tools/cli/authentication).
3. Create a GitHub Actions environment named `databricks-dev`, add the
   following secrets, and configure one or more **Required reviewers**. Enable
   **Prevent self-review** if the account offers that setting. The reviewer is
   the release gatekeeper; Jira approval remains the business stakeholder
   approval for each individual change.

   | Environment setting | Value |
   |---|---|
   | Secret `DATABRICKS_HOST` | Workspace URL, for example `https://<workspace-host>` |
   | Secret `DATABRICKS_CLIENT_ID` | Databricks service principal application/client ID |
   | Secret `DATABRICKS_CLIENT_SECRET` | OAuth M2M secret created for that service principal |

   The workflow passes these values to the Databricks CLI, which obtains
   short-lived OAuth access tokens. Keep all three values in GitHub Secrets;
   do not put them in `databricks.yml` or deployment evidence. OIDC federation
   and the GitHub `id-token` permission are not required for this setup.
   GitHub's required-reviewer rule is available on Free, Pro, and Team plans
   only for public repositories; private or internal repositories need a plan
   that supports environment protection rules. See the official
   [required reviewer plan requirements](https://docs.github.com/en/actions/reference/workflows-and-actions/deployments-and-environments#required-reviewers).
4. Create GitHub Actions environment variables `DATABRICKS_SAMPLE_CATALOG` and
   `DATABRICKS_SAMPLE_SCHEMA` naming an existing development catalog and
   writable schema. Set the repository variable `CHANGE_ASSURANCE_BASE_RELEASE_TAG`
   to the baseline tag for the first deployment when no earlier GitHub Release
   exists. Once the first deployment is complete, remove this variable; later
   releases compare against the immediately preceding published release.
5. Merge this workflow to the repository's default branch, then publish a
   GitHub Release to create a release candidate. Release events only trigger
   this workflow if its file exists on the default branch. Every commit between
   the baseline and release tag must contain exactly one Jira
   issue key matching `.cms/config/change-request.yml`. Each Jira request must
   currently be approved and retain an approval history entry with approver and
   timestamp. The workflow summary and `release-candidate-*` artifact show the
   full commit-to-ticket mapping and Jira approvals before the gate.
6. The `deploy-release` job waits for a required reviewer on `databricks-dev`.
   Only after a reviewer approves does it revalidate Jira and access the
   Databricks secrets. Approval can be rejected or left pending to stop release.
7. Require **Change assurance / Jira validation** in branch protection for
   production branches. That PR check enforces the ticket metadata and
   commit-traceability contract before commits are eligible for a release.

The workflow uses `databricks/setup-cli@v1.10.0`, Databricks OAuth M2M client
credentials, and the Bundle's `dev` target. It does not have a production target.
The trusted workflow and policy code come from the default branch, while the
sample bundle is checked out at the immutable release SHA after approval. The
candidate artifact is available to reviewers before they approve the gated job.
The final artifact contains the release manifest, Jira revalidation snapshot,
and deployment evidence. The evidence writer reads
`databricks bundle summary --output json` to include workspace and resource
identifiers when the CLI returns them.

The remainder of this section shows the equivalent steps for a customer
workload repository. Run the preflight before bundle commands and run the
evidence writer afterward with an unconditional step:

```yaml
steps:
  - uses: actions/checkout@v7.0.1

  - name: Install Python dependencies
    working-directory: .cms
    run: python3 -m pip install -r requirements.txt

  - name: Revalidate Jira approval
    env:
      CHANGE_ID: ${{ env.CHANGE_ID }}
      CHANGE_REQUEST_CONFIG: config/change-request.yml
      JIRA_CLOUD_ID: ${{ vars.JIRA_CLOUD_ID }}
      JIRA_OAUTH_CLIENT_ID: ${{ secrets.JIRA_OAUTH_CLIENT_ID }}
      JIRA_OAUTH_CLIENT_SECRET: ${{ secrets.JIRA_OAUTH_CLIENT_SECRET }}
      PYTHONPATH: src
    working-directory: .cms
    run: python3 -m change_assurance.action.deployment_preflight

  # Install a pinned Databricks CLI. Provide OAuth M2M credentials through
  # DATABRICKS_HOST, DATABRICKS_CLIENT_ID, and DATABRICKS_CLIENT_SECRET.
  - name: Validate Databricks bundle
    id: bundle_validate
    run: databricks bundle validate --target prod

  - name: Deploy Databricks bundle
    id: bundle_deploy
    if: steps.bundle_validate.outcome == 'success'
    run: databricks bundle deploy --target prod

  - name: Write deployment evidence
    if: always()
    working-directory: .cms
    env:
      PYTHONPATH: src
      CHANGE_ID: ${{ env.CHANGE_ID }}
      DEPLOYMENT_AUTHORIZATION_PATH: deployment-authorization.json
      DATABRICKS_VALIDATION_RESULT: ${{ steps.bundle_validate.outcome == 'success' && 'SUCCESS' || steps.bundle_validate.outcome == 'failure' && 'FAILURE' || 'NOT_RUN' }}
      DATABRICKS_DEPLOYMENT_RESULT: ${{ steps.bundle_deploy.outcome == 'success' && 'SUCCESS' || steps.bundle_deploy.outcome == 'failure' && 'FAILURE' || 'NOT_RUN' }}
      DATABRICKS_HOST: ${{ secrets.DATABRICKS_HOST }}
      DATABRICKS_WORKSPACE_ID: ${{ vars.DATABRICKS_WORKSPACE_ID }}
      DATABRICKS_BUNDLE_TARGET: dev
    run: python3 -m change_assurance.action.deployment_evidence

  - name: Upload deployment evidence
    if: always()
    uses: actions/upload-artifact@v7.0.1
    with:
      name: databricks-deployment-${{ github.run_id }}-${{ github.run_attempt }}
      path: |
        .cms/deployment-authorization.json
        .cms/databricks-deployment-evidence.json
      if-no-files-found: warn
```

This customer-workload outline uses a production target. It gives command steps
IDs and maps GitHub's `success`/`failure`/
`skipped` outcomes to the contract's `SUCCESS`/`FAILURE`/`NOT_RUN` values. A
production workflow must also capture timestamps, Bundle summary resources,
and any operation ID. Do not pass tokens or full CLI output
to the evidence writer. The writer accepts these optional environment values:

| Variable | Use |
|---|---|
| `CHANGE_ID` | Jira key for this deployment |
| `PULL_REQUEST_NUMBER` | Merged PR number |
| `MERGE_COMMIT_SHA` | Exact source revision deployed; defaults to `GITHUB_SHA` |
| `DEPLOYMENT_STARTED_AT` | UTC deployment start timestamp |
| `DATABRICKS_VALIDATION_RESULT` | `SUCCESS`, `FAILURE`, or `NOT_RUN` |
| `DATABRICKS_DEPLOYMENT_RESULT` | `SUCCESS`, `FAILURE`, or `NOT_RUN` |
| `DATABRICKS_EXECUTION_RESULT` | `SUCCESS`, `FAILURE`, `NOT_RUN`, or `NOT_APPLICABLE` |
| `DATABRICKS_DEPLOYMENT_RESOURCES_JSON` | JSON array of resource type/key/ID/URL objects |
| `DATABRICKS_DEPLOYMENT_OPERATION_ID` | Native operation ID, when available |
| `DATABRICKS_JOB_RUN_ID` | Separate runtime job run ID, if launched |
| `DATABRICKS_CLI_VERSION`, `DATABRICKS_BUNDLE_NAME`, `DATABRICKS_BUNDLE_TARGET` | Bundle execution identity |
| `DEPLOYMENT_ARTIFACT_DIGEST` | SHA-256 digest of an immutable build artifact, when applicable |
| `DEPLOYMENT_EVIDENCE_PATH` | Optional output path; defaults to `databricks-deployment-evidence.json` |
| `DEPLOYMENT_REASON_CODES_JSON` | JSON array of `{ "code", "message" }` objects |

The GitHub run ID, attempt, repository, run URL, ref, and SHA are read from
standard Actions environment values. The preflight authorization file should
be uploaded with the final record so its full Jira snapshot and failure reason
are retained. Upload each run attempt under a unique artifact name; a retry is
a new evidence event, never an overwrite of the earlier attempt.

The root [`databricks_sample/`](../../databricks_sample/) folder contains an
example bundle with three Python tasks: create sample records, normalize them,
and run simple data quality checks. Its `dev` target is the only configured
target. The bundle has no workspace URL or credentials; configure Databricks
CLI authentication and an existing writable Unity Catalog catalog/schema
before validating or deploying it. The scripts overwrite two sample tables,
so point them only at a development schema. The sample is not a production
deployment workflow and does not claim a deployment happened.

## Sample bundle layout

```text
databricks_sample/
  databricks.yml
  sample_scripts/
    01_ingest.py
    02_transform.py
    03_quality_check.py
  resources/workflows/
    sample.yml
```

Keep Databricks credentials out of `databricks.yml`; provide them through a
Databricks CLI profile locally or OAuth M2M environment variables backed by
GitHub Actions variables and secrets in CI.

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
