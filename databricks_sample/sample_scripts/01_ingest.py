"""Create a tiny sample source table for the bundle workflow."""

from __future__ import annotations

import argparse
import re

from pyspark.sql import SparkSession


def table_name(value: str) -> str:
    """Validate a three-part Unity Catalog table identifier."""
    parts = value.split(".")
    if len(parts) != 3 or any(not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", part) for part in parts):
        raise argparse.ArgumentTypeError(
            "table must be a simple catalog.schema.table identifier"
        )
    return ".".join(f"`{part}`" for part in parts)


def main() -> None:
    """Write deterministic demo records to the configured raw table."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--table", required=True, type=table_name)
    args = parser.parse_args()

    spark = SparkSession.builder.getOrCreate()
    rows = [
        (101, "Ada Lovelace", 125.50),
        (102, "Grace Hopper", 80.00),
        (103, "Katherine Johnson", 210.25),
    ]
    frame = spark.createDataFrame(rows, ["customer_id", "customer_name", "amount"])
    frame.write.mode("overwrite").saveAsTable(args.table)
    print(f"Wrote {frame.count()} sample rows to {args.table}.")


if __name__ == "__main__":
    main()
