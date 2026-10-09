"""Normalize the sample raw table and write its curated counterpart."""

from __future__ import annotations

import argparse
import re

from pyspark.sql import SparkSession
from pyspark.sql import functions as F


def table_name(value: str) -> str:
    """Validate a three-part Unity Catalog table identifier."""
    parts = value.split(".")
    if len(parts) != 3 or any(not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", part) for part in parts):
        raise argparse.ArgumentTypeError(
            "table must be a simple catalog.schema.table identifier"
        )
    return ".".join(f"`{part}`" for part in parts)


def main() -> None:
    """Transform names and amounts from the raw table."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-table", required=True, type=table_name)
    parser.add_argument("--target-table", required=True, type=table_name)
    args = parser.parse_args()

    spark = SparkSession.builder.getOrCreate()
    source = spark.table(args.source_table)
    curated = source.select(
        "customer_id",
        F.lower(F.trim(F.col("customer_name"))).alias("customer_name"),
        F.col("amount").cast("double").alias("amount"),
    )
    curated.write.mode("overwrite").saveAsTable(args.target_table)
    print(f"Wrote {curated.count()} curated rows to {args.target_table}.")


if __name__ == "__main__":
    main()
