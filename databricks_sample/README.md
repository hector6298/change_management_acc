# Databricks sample bundle

This development-only bundle demonstrates one Databricks workflow with three
Python tasks:

1. `01_ingest.py` overwrites a small raw Unity Catalog table with deterministic
sample rows.
2. `02_transform.py` normalizes the rows and overwrites a curated table.
3. `03_quality_check.py` fails the job if the curated table is empty or has
   invalid values.

## Configure and run

Authenticate the Databricks CLI using your workspace's approved profile or
workload identity. The bundle does not contain workspace URLs, credentials, or
production settings. Update `sample_catalog` and `sample_schema` defaults in
`databricks.yml` to an existing development catalog and schema where your
identity can create or replace tables.

From this directory:

```sh
databricks bundle validate --target dev
databricks bundle deploy --target dev
databricks bundle run change_assurance_sample_workflow --target dev
```

`bundle deploy` creates or updates the workflow definition. `bundle run`
executes it. Each run replaces the two sample tables, so keep the configured
schema dedicated to development examples. This bundle has no production
target.

The repository's [Databricks release deployment workflow](../.github/workflows/deploy-databricks-sample.yml)
runs when a GitHub Release is published. It checks every commit since the
previous release, requires one Jira key per commit, validates current
Jira approval for every change, and makes a release manifest available for
review. Deployment pauses for a required reviewer on the `databricks-dev`
GitHub environment, then revalidates Jira and deploys the exact release commit.
Configure its service-principal secrets and required reviewers as described in
[the Block 3 guide](../.cms/docs/block-3-databricks-deployment-evidence.md).
