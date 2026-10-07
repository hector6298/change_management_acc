# Block 1 — Jira Change Identity (demo setup)

## System of record and contract

- Jira owns the change request and its lifecycle.
- The Jira issue key (such as `DEMO-12`) is the only `change_id` used across
  GitHub, CI/CD, Databricks, and evidence. Do not mint an accelerator ID.
- A governed production deployment requires an existing Jira issue of the
  configured change-request type, explicit approval, and production as its
  target environment.
- Approval must precede production deployment. The current Approval State
  must match the configured `approved_value`, and Jira history must identify
  who changed it and when. Workflow status is recorded but does not determine
  approval.
- Once a deployment is recorded, the issue key is immutable. Do not reuse one
  change request for unrelated changes; create a distinct Jira issue for each
  independently governed change.

## Suggested demo fields

Create a Jira work type/issue type named **Change Request** and add these fields
to its create and view layouts. Use existing Jira fields where noted.

| Display name | Jira field type | Demo values / use |
|---|---|---|
| Change ID | Issue key (built in) | Automatically assigned, e.g. `DEMO-12`; never create a second ID field |
| Summary | Summary (built in) | Short statement of the change |
| Description | Description (built in) | Scope, reason, and implementation notes |
| Status | Workflow status (built in) | Jira workflow lifecycle; observed by the Action but not used as the approval gate |
| Approval State | Single-select custom field | A value selected by the team; the configured `approved_value` is the one value that authorizes production |
| Risk | Single-select custom field | `Low`, `Medium`, `High`, `Critical` |
| Target Environment | Single-select custom field | `Development`, `Test`, `Production` |

For an initial demo, make Summary, Approval State, Risk, and Target Environment
required on the Change Request create form. Start Approval State at `Pending`.
The Jira issue history records who changed Approval State and when. The
validator uses that history as approval evidence, so separate Approved By and
Approved At fields are unnecessary. Restrict the approval transition and
Approval State edit to authorized approvers, as supported by the project and
workflow plan; the history alone records the editor but does not decide whether
that person was authorized. The current policy uses one configured approved
value and does not distinguish a separate emergency approval state.

### Configure a company-managed project

1. In project settings, create the **Change Request** work type if it is not
   already available, then associate it with the project.
2. Create the custom fields from the table in Jira settings → Work items/Issues
   → Fields. Add them to the Change Request create/view screens and layout.
3. In project settings → Workflows, edit the workflow used by Change Request.
   Add the statuses above and transitions `Submit for Approval`, `Approve`,
   `Reject`, and `Implement`. Restrict
   approval transitions to the approver role where the Jira plan/workflow editor
   supports that condition.
4. On approval, transition the workflow and set Approval State to the
   configured approved value. On rejection, set it to a non-approved value. Jira records
   the field change, actor, and timestamp in the issue history; no separate
   approver/time fields or automation are needed.
5. Publish the workflow and create a sample issue. Verify an ordinary user
   cannot approve if that restriction is part of the demo requirement.

### Configure a team-managed project

Use Project settings → Work types to add **Change Request**, configure its
fields and required fields, then use the project's workflow editor to add the
statuses/transitions. Add custom fields to the project/work type where needed.
Team-managed and company-managed projects expose different workflow and field
controls; if the editor cannot restrict approvers, show approval as a
controlled demo step and do not claim Jira enforces it.

Jira Cloud menus and capabilities vary by project type and plan. Atlassian's
current approval-step guide describes company-managed workflow approval setup:
[Set up approval steps](https://support.atlassian.com/jira-software-cloud/docs/set-up-approval-steps/).

## Production decision rules

| Request | Production allowed? |
|---|---|
| Missing/malformed Change ID or issue not found | No |
| Wrong issue type | No |
| Approval State does not equal the configured approved value | No |
| Production target without a matching approval history entry and actor/time | No |
| Production target with the configured approved value and approver/time in issue history | Yes, subject to later Block 2 validation |
| Development/Test target | Production approval rule does not apply |

The local contract validates request data and deployment eligibility. It does
not query Jira, enforce Jira workflow permissions, or prevent a user with Jira
admin rights from editing an issue. Those require Jira configuration and, in a
later integration, authenticated API checks.

## Local contract model

`src/change_assurance/models/change_identity.py` provides:

- Jira issue-key format validation and canonical `change_id` normalization.
- Required identity and non-empty normalized fields.
- Production eligibility checks requiring the configured Approval State and
  extractable actor/timestamp from issue history.
- A deployed identity wrapper that rejects changing the Change ID after
  deployment.

The runtime rules are loaded from [`config/change-request.yml`](../config/change-request.yml).
It defines the issue type, schema version, Jira key pattern, production
environment, Jira field mappings, and one `approved_value`. Other Jira field
values are required or optional according to `jira_fields`; their values are
not restricted to enumerated lists. The Action and local `ChangeRequest` model
read this same file. Set `CHANGE_REQUEST_CONFIG` to use another YAML path.
Keep the file in the trusted base branch because it helps determine the merge
decision.

Jira custom-field IDs are configured in the `jira_fields` section of the YAML;
Jira credentials stay in GitHub Actions secrets. The versioned JSON Schema in
`schemas/change-request.schema.json` documents the default normalized record
expected by later GitHub and Databricks evidence ingestion.
