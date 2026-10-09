"""Fail the sample workflow if the curated table violates basic checks."""

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
    """Check that the curated output has rows and valid values."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--table", required=True, type=table_name)
    args = parser.parse_args()

    spark = SparkSession.builder.getOrCreate()
    frame = spark.table(args.table)
    invalid_rows = frame.filter(
        F.col("customer_id").isNull()
        | F.col("customer_name").isNull()
        | (F.length(F.col("customer_name")) == 0)
        | F.col("amount").isNull()
        | (F.col("amount") < 0)
    ).count()
    row_count = frame.count()
    if row_count == 0 or invalid_rows:
        raise ValueError(
            f"Quality checks failed for {args.table}: "
            f"rows={row_count}, invalid_rows={invalid_rows}."
        )
    print(f"Quality checks passed for {row_count} rows in {args.table}.")


if __name__ == "__main__":
    main()
