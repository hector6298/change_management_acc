# Block 1 — Jira Change Identity (demo setup)

## System of record and contract

- Jira owns the change request and its lifecycle.
- The Jira issue key (such as `DEMO-12`) is the only `change_id` used across
  GitHub, CI/CD, Databricks, and evidence. Do not mint an accelerator ID.
- A governed production deployment requires an existing Jira issue of the
  configured change-request type, explicit approval, and production as its
  target environment.
- Approval must precede production deployment. A Jira status alone is not
  approval unless the configured workflow makes the approved status reachable
  only through the approval transition.
- Once a deployment is recorded, the issue key is immutable. Do not reuse one
  change request for unrelated changes; create a distinct Jira issue for each
  independently governed change.
- Emergency requests use the same issue key and identity. They still need an
  explicit approval state; the expedited approval path should be labeled
  `Emergency Approved` and captured as such.

## Suggested demo fields

Create a Jira work type/issue type named **Change Request** and add these fields
to its create and view layouts. Use existing Jira fields where noted.

| Display name | Jira field type | Demo values / use |
|---|---|---|
| Change ID | Issue key (built in) | Automatically assigned, e.g. `DEMO-12`; never create a second ID field |
| Summary | Summary (built in) | Short statement of the change |
| Description | Description (built in) | Scope, reason, and implementation notes |
| Status | Workflow status (built in) | `Draft`, `Awaiting Approval`, `Approved`, `Rejected`, `Implemented`; `Emergency Approved` for the expedited path |
| Approval State | Single-select custom field | `Pending`, `Approved`, `Rejected`, `Emergency Approved`; keep separate from generic workflow status for an unambiguous demo contract |
| Approved By | User Picker (single user) | Person who approved; populate only when approval is granted |
| Approved At | Date Time Picker | Approval timestamp; populate only when approval is granted |
| Risk | Single-select custom field | `Low`, `Medium`, `High`, `Critical` |
| Target Environment | Single-select custom field | `Development`, `Test`, `Production` |
| Emergency Change | Checkbox (or single-select Yes/No) | Marks expedited requests; does not waive approval |

For an initial demo, make Summary, Approval State, Risk, and Target Environment
required on the Change Request create form. Start Approval State at `Pending`.
Do not make Approved By/Approved At required at creation; require them as part
of the approval procedure. Only Jira admins/project admins should be able to
approve, as supported by the project/workflow plan.

### Configure a company-managed project

1. In project settings, create the **Change Request** work type if it is not
   already available, then associate it with the project.
2. Create the custom fields from the table in Jira settings → Work items/Issues
   → Fields. Add them to the Change Request create/view screens and layout.
3. In project settings → Workflows, edit the workflow used by Change Request.
   Add the statuses above and transitions `Submit for Approval`, `Approve`,
   `Reject`, and `Implement` (plus `Emergency Approve` if needed). Restrict
   approval transitions to the approver role where the Jira plan/workflow editor
   supports that condition.
4. On approval, set Approval State to `Approved` (or `Emergency Approved`) and
   populate Approved By and Approved At. On rejection, set it to `Rejected`.
   Configure workflow transition screens/validators or a Jira automation rule
   to collect/update these fields.
5. Publish the workflow and create a sample issue. Verify an ordinary user
   cannot approve if that restriction is part of the demo requirement.

### Configure a team-managed project

Use Project settings → Work types to add **Change Request**, configure its
fields and required fields, then use the project's workflow editor to add the
statuses/transitions. Add custom fields to the project/work type where needed.
Team-managed and company-managed projects expose different workflow and field
controls; if the editor cannot restrict approvers or populate approval metadata,
show those as controlled demo steps and do not claim Jira enforces them.

Jira Cloud menus and capabilities vary by project type and plan. Atlassian's
current approval-step guide describes company-managed workflow approval setup:
[Set up approval steps](https://support.atlassian.com/jira-software-cloud/docs/set-up-approval-steps/).

## Production decision rules

| Request | Production allowed? |
|---|---|
| Missing/malformed Change ID or issue not found | No |
| Wrong issue type | No |
| Approval state is Pending/Rejected | No |
| Production target without Approved state and approval metadata | No |
| Production target with Approved state and approver/time | Yes, subject to later Block 2 validation |
| Emergency production target with Emergency Approved state and approver/time | Yes, subject to configured emergency procedure |
| Development/Test target | Production approval rule does not apply |

The local contract validates request data and deployment eligibility. It does
not query Jira, enforce Jira workflow permissions, or prevent a user with Jira
admin rights from editing an issue. Those require Jira configuration and, in a
later integration, authenticated API checks.

## Local contract model

`src/change_assurance/change_identity.py` provides:

- Jira issue-key format validation and canonical `change_id` normalization.
- Required data and allowed approval/risk/environment value checks.
- Production eligibility checks requiring approval metadata.
- A deployed identity wrapper that rejects changing the Change ID after
  deployment.

The versioned JSON Schema in `schemas/change-request.schema.json` documents the
normalized record expected by later GitHub and Databricks evidence ingestion.
Jira custom-field IDs are deliberately not hard-coded: map actual field IDs to
these normalized names in a future Jira connector.
