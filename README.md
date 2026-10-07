# Databricks Change Assurance Accelerator

Reusable governance evidence for production changes, connecting Jira, GitHub,
CI/CD, and Databricks while leaving each system as the authority for its own
records.

## Block 1: Change Identity

Jira is authoritative for change requests. The Jira issue key (for example,
`DEMO-12`) is the canonical `change_id`; do not create another ID in this
accelerator. See [the Jira demo setup and contract](docs/block-1-change-identity.md).

## Block 2: GitHub Change Traceability

Jira's development panel is the native human-facing view of linked GitHub
branches, commits, and pull requests. The integration and evidence design is
in [the Block 2 framework](docs/block-2-github-traceability.md). The initial
GitHub Action implementation is in `.github/workflows/change-assurance.yml`.
Its Python code is organized into `action/`, `clients/`, `models/`, `policy/`,
and `reporting/` packages; see the Block 2 guide for the module map.
For the execution flow, GitHub/Jira configuration, and local run instructions,
see [How it works and how to run it](docs/how-it-works-and-run.md).

## Block 3: Databricks Deployment Evidence

The proposed CI/CD-to-Databricks deployment flow and evidence contract are in
[the Block 3 framework](docs/block-3-databricks-deployment-evidence.md).

Test change