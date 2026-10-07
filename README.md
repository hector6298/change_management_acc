# Databricks Change Assurance Accelerator

Reusable governance evidence for production changes, connecting Jira, GitHub,
CI/CD, and Databricks while leaving each system as the authority for its own
records.

## Block 1: Change Identity

Jira is authoritative for change requests. The Jira issue key (for example,
`DEMO-12`) is the canonical `change_id`; do not create another ID in this
accelerator. See [the Jira demo setup and contract](docs/block-1-change-identity.md).

