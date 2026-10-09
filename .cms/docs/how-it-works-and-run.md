# How Change Assurance Works and How to Run It

This guide covers the current Block 2 GitHub Action. It checks that a
production-bound pull request (PR) has one consistent Jira Change Request ID,
that its commits reference that ID, and that Jira records the required
production approval. It then writes a JSON evidence record and a run summary.

## How the code is organized

```text
.cms/
  src/change_assurance/
    action/github_action.py   # Coordinates one validation run
    clients/github.py         # Reads PR commits from the GitHub API
    clients/jira.py           # Reads configured fields from Jira Cloud
    models/action.py          # Settings, PR, evidence, and error records
    models/change_identity.py # Shared Block 1 Change Request contract
    policy/validation.py      # Change ID and Jira approval rules
    reporting/workflow.py    # Evidence JSON and Markdown run summary
  config/change-request.yml # Jira fields and approval policy
```

The Action coordinator loads the pull-request event, then follows this flow:

1. It checks the PR target branch against `PRODUCTION_BRANCHES` (defaults to
   `main`). A PR targeting another branch gets `SKIPPED`; Jira approval is not
   checked for that PR.
2. For a production-bound PR, it requires exactly one `Change-ID: KEY` line in
   the PR body. The same Jira key must begin the PR title and source branch.
3. It retrieves the PR's commits from GitHub. Each non-merge commit message
   must contain that Jira key and no other Jira issue key.
4. It retrieves the mapped Jira issue fields and the paginated issue changelog.
   It validates the Change Request type, all required Jira fields, and the
   configured Approval State value. It derives the
   approver and approval time from the latest Approval State field change.
   Workflow status is recorded as evidence but does not gate approval.
5. It records `PASS`, `FAILURE`, `ERROR`, or `SKIPPED`, writes
   `change-assurance-evidence.json`, and writes a Markdown summary when
   `GITHUB_STEP_SUMMARY` is set.

`PASS` and `SKIPPED` exit with code 0. `FAILURE` and `ERROR` exit with code 1,
which makes the GitHub Actions job fail. A policy rejection is `FAILURE`; a
missing configuration value, inaccessible API, or invalid event is `ERROR`.

## Run through GitHub Actions

The workflow is [`.github/workflows/change-assurance.yml`](../../.github/workflows/change-assurance.yml).
It starts on PR open, edit, synchronize, reopen, ready-for-review, and
converted-to-draft events. It runs `change_assurance.action.github_action` on
the trusted target branch and uploads the evidence JSON as an artifact for 30
days.

Before the first run, configure the repository or organization settings:

| Setting | Kind | Example / purpose |
|---|---|---|
| `CHANGE_ASSURANCE_PRODUCTION_BRANCHES` | Actions variable | `main,release/*`; defaults to `main` |
| `CHANGE_REQUEST_CONFIG` | Actions variable | Contract YAML path relative to `.cms/`; defaults to `config/change-request.yml` |
| `JIRA_CLOUD_ID` | Actions variable | Cloud ID for the Jira site |
| `JIRA_OAUTH_CLIENT_ID` | Actions secret | OAuth client ID for the Atlassian service account |
| `JIRA_OAUTH_CLIENT_SECRET` | Actions secret | OAuth client secret for the Atlassian service account |

The Jira service account needs permission to browse the Change Request project. The
workflow supplies `GITHUB_TOKEN` with read access to repository contents and
PRs. Add the workflow check, **Change assurance / Jira validation**, to branch
protection after it has appeared on a PR.

For production-bound changes, use the same key in the branch, commit, PR title,
and PR body:

```text
Branch:    DEMO-12-add-risk-feature
Commit:    DEMO-12: add risk feature
PR title:  DEMO-12 Add risk feature
PR body:   Change-ID: DEMO-12
```

After opening or updating the PR, inspect the **Jira validation** job summary
for the result and remediation details. Download the
`change-assurance-<PR>-<run>-<attempt>` artifact to review the JSON evidence.

## Run locally

Install the pinned YAML parser dependency before running locally. A local run
makes live GitHub and Jira API calls, so provide a real
PR event payload and credentials with the required read permissions.

1. Save the JSON payload for a GitHub `pull_request` event to a file, for
   example `/tmp/pull_request.json`. The payload must include the PR title,
   body, source branch, target branch, number, and head SHA.
2. From the repository root, change into `.cms/` and set the environment below. Keep credentials in
   your shell environment or secret manager; do not commit them or paste them
   into source files.

```sh
cd .cms
python3 -m pip install -r requirements.txt

export PYTHONPATH=src
export CHANGE_REQUEST_CONFIG=config/change-request.yml
export GITHUB_API_URL=https://api.github.com
export GITHUB_REPOSITORY=OWNER/REPOSITORY
export GITHUB_EVENT_PATH=/tmp/pull_request.json
export GITHUB_TOKEN=your_github_read_token
export PRODUCTION_BRANCHES=main

export JIRA_CLOUD_ID=your_jira_cloud_id
export JIRA_OAUTH_CLIENT_ID=your_service_account_oauth_client_id
export JIRA_OAUTH_CLIENT_SECRET=your_service_account_oauth_client_secret

python3 -m change_assurance.action.github_action
```

Replace the owner, repository, Cloud ID, and token with values from your
environment. Configure sample custom-field IDs in the YAML contract. To also write the Actions-style Markdown
summary locally, set `GITHUB_STEP_SUMMARY` to a writable file path. The JSON
evidence is written to `change-assurance-evidence.json` in the current working
directory; the command's process exit code matches the Action result.

The Action reads Jira's paginated issue changelog and uses the latest change to
the configured Approval State field as the approval actor and timestamp. The
current field value must match that changelog entry. Ensure Jira permissions
and workflow rules restrict approval to authorized users.

To customize the normalized Change Request contract, edit the scalar settings
in the YAML file and the `jira_fields` mapping. The workflow checks out this
configuration from the trusted target branch, so changes to the policy should
receive the same review as changes to the validator code.

Jira custom-field mappings are in `jira_fields`. Replace the example IDs with
your Jira field IDs. To make another field mandatory, add an entry such as:

```yaml
jira_fields:
  change_reason:
    id: customfield_12349
    type: text
    required: true
```

Configure `approval_state` because the production policy needs it to verify
authorization. Production targeting comes from the PR's GitHub base branch,
matched against `PRODUCTION_BRANCHES`; Jira target-environment fields are not
used by this Action. `risk` and any additional Jira fields can be included or
omitted according to your contract. Set each
field's `required` flag independently to control the generic required-field
check. The approval policy still needs a non-empty approved state. For example,
change `risk.required` to `false` to make Risk optional, or remove the
`risk` mapping if you do not use that Jira field.
Set `jira_fields.approval_state.approved_value` to the single value that
authorizes production, for example `Approved`. Other Approval State values
fail the check.
Supported field types are `select`, `text`, `boolean`, `date_time`, and `raw`.
Fields marked `required: true` are checked for a value and included in the
evidence JSON; there are no accepted-value lists. Approval requires the latest
Approval State changelog entry to match the current field value and include an extractable actor and
timestamp. OAuth client credentials remain in Actions secrets; do not put
credentials in the YAML file.

### Create an Atlassian service account

1. In [Atlassian Administration](https://admin.atlassian.com/), select your
   organization, then go to **Directory → Service accounts** and create a
   service account for this validator.
2. Grant it Jira product access and the minimum project permissions needed to
   browse Change Request issues and read their changelogs.
3. Open the service account, choose **Create credentials → OAuth 2.0**, and
   select the Jira `read:jira-work` scope. The validator only reads issue
   fields and changelogs, so it does not need Jira write scopes.
4. Find the Jira site's **Cloud ID** by opening
   `https://<your-jira-site>.atlassian.net/_edge/tenant_info` in a browser,
   replacing the hostname with the Jira site that contains your Change
   Request. The endpoint returns JSON such as
   `{"cloudId":"<your-cloud-id>"}`. Copy the `cloudId` value into
   `JIRA_CLOUD_ID`; do not use the organization ID. Atlassian documents this
   lookup in its [Cloud ID guide](https://support.atlassian.com/jira/kb/retrieve-my-atlassian-sites-cloud-id/).
5. Add `JIRA_CLOUD_ID` as a GitHub Actions variable. Add the OAuth client ID
   and secret as `JIRA_OAUTH_CLIENT_ID` and `JIRA_OAUTH_CLIENT_SECRET` Actions
   secrets. The client exchanges these credentials for a short-lived access
   token at the start of each run.
6. Verify the credential by exchanging it at
   `https://auth.atlassian.com/oauth/token` with the `client_credentials`
   grant, then use the returned bearer token to read a sample Change Request
   and its changelog through the Jira API gateway.

Atlassian service-account OAuth uses the client-credentials grant, a two-legged
flow. Access tokens are valid for 60 minutes; this Action obtains a fresh token
for each run and uses it as a bearer token through `api.atlassian.com` with the
site's Cloud ID. Service accounts still require Jira project permissions and
the configured token scopes. See Atlassian's guide to [OAuth 2.0 credentials
for service accounts](https://support.atlassian.com/user-management/docs/create-oauth-2-0-credential-for-service-accounts/).

## Evidence and limitations

The evidence record captures the change ID, PR and commit identifiers, Jira
approval snapshot, result, reason codes, and observation time. GitHub retains
the uploaded artifact for 30 days under the current workflow configuration;
copy it to durable storage if your audit requirements need longer retention.

The Jira Development panel helps users navigate between Jira issues and
branches, commits, and PRs. This Action separately checks identity and Jira
approval. It does not record a Databricks deployment or prove that deployment
occurred; deployment evidence belongs to Block 3.
