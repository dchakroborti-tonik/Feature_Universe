"""
bq_type_fix.py
--------------
Drop-in helpers to work around DuckDB's lack of support for BigQuery types:
  • TIME WITH TIME ZONE
  • DATETIME  (BigQuery-specific, not standard SQL TIMESTAMP)
  • JSON      (BQ STRING subtype that round-trips as JSON)
  • INTERVAL  (not supported by Parquet/DuckDB)

Strategy
--------
Before exporting to Parquet we inspect the BQ result-table schema and wrap
any unsupported column in a SAFE_CAST(col AS STRING) so the Parquet file
only contains types DuckDB can read.

Usage
-----
Replace your current duckdb.sql(read_parquet(...)) call with the helpers
in this file.  Everything else in your pipeline stays the same.
"""

from __future__ import annotations

import logging
import os
import re
import tempfile
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional

import duckdb
import pandas as pd
from google.cloud import bigquery, storage
from google.cloud.exceptions import NotFound

logger = logging.getLogger(__name__)

# ── BigQuery field types that Parquet / DuckDB cannot handle natively ─────────
_UNSUPPORTED_BQ_TYPES = {
    "TIME",         # BQ TIME WITH TIME ZONE becomes TIME in the schema object
    "DATETIME",     # BQ DATETIME has no timezone — not the same as TIMESTAMP
    "JSON",         # stored as STRING in BQ but tagged as JSON mode
    "INTERVAL",     # not supported by Parquet
}


# ---------------------------------------------------------------------------
# Schema inspection helpers
# ---------------------------------------------------------------------------

def _get_query_schema(
    client: bigquery.Client,
    query: str,
) -> list[bigquery.SchemaField]:
    """
    Return the output schema of *query* without fetching any rows.
    Uses a DRY_RUN job — zero bytes billed.
    """
    job_config          = bigquery.QueryJobConfig(dry_run=True, use_query_cache=False)
    dry_run_job         = client.query(query, job_config=job_config)
    return list(dry_run_job.schema)


def _build_safe_select(schema: list[bigquery.SchemaField]) -> str:
    """
    Build a SELECT clause that casts unsupported columns to STRING.

    Rules
    -----
    TIME / DATETIME / JSON / INTERVAL  → CAST(col AS STRING)
    Everything else                    → col  (untouched)

    Returns a comma-separated column list suitable for:
        SELECT <result> FROM (<original_query>)
    """
    parts = []
    for field in schema:
        col   = f"`{field.name}`"          # back-tick for reserved-word safety
        ftype = field.field_type.upper()   # e.g. "TIME", "DATETIME", "STRING"

        if ftype in _UNSUPPORTED_BQ_TYPES:
            parts.append(f"CAST({col} AS STRING) AS `{field.name}`")
            logger.debug("  Casting column '%s' (%s → STRING)", field.name, ftype)
        else:
            parts.append(col)

    return ",\n  ".join(parts)


def _wrap_query_for_safe_export(
    client: bigquery.Client,
    query: str,
) -> tuple[str, list[str]]:
    """
    Wrap *query* so that unsupported BQ types are cast to STRING.

    Returns
    -------
    (safe_query, cast_columns)
        safe_query    : SQL string ready to hand to BQ for export
        cast_columns  : list of column names that were cast (for logging)
    """
    schema      = _get_query_schema(client, query)
    cast_cols   = [f.name for f in schema if f.field_type.upper() in _UNSUPPORTED_BQ_TYPES]

    if not cast_cols:
        logger.info("No unsupported column types found — exporting as-is.")
        return query, []

    logger.info(
        "Casting %d column(s) to STRING before export: %s",
        len(cast_cols), cast_cols,
    )
    select_clause = _build_safe_select(schema)
    # Strip trailing semicolon so it can be used as a sub-query
    inner = query.rstrip().rstrip(";").strip()
    safe_query = f"SELECT\n  {select_clause}\nFROM (\n  {inner}\n)"
    return safe_query, cast_cols


# ---------------------------------------------------------------------------
# GCS helpers (object-level only — no bucket.get)
# ---------------------------------------------------------------------------

def _verify_gcs_access(project_id: str, bucket_name: str, prefix: str) -> None:
    client   = storage.Client(project=project_id)
    bucket   = client.bucket(bucket_name)
    sentinel = bucket.blob(f"{prefix}.sentinel")
    try:
        sentinel.upload_from_string(b"ok")
        sentinel.download_as_bytes()
        sentinel.delete()
    except NotFound as exc:
        raise RuntimeError(f"Bucket gs://{bucket_name} not found. {exc}") from exc
    except Exception as exc:
        raise RuntimeError(f"GCS access check failed: {exc}") from exc


def _download_blob(blob_name: str, bucket_name: str, project_id: str, local_dir: Path) -> Path:
    client     = storage.Client(project=project_id)
    blob       = client.bucket(bucket_name).blob(blob_name)
    local_path = local_dir / Path(blob_name).name
    blob.download_to_filename(str(local_path), checksum="md5")
    return local_path


def _delete_blob(blob_name: str, bucket_name: str, project_id: str) -> None:
    client = storage.Client(project=project_id)
    client.bucket(bucket_name).blob(blob_name).delete()


# ---------------------------------------------------------------------------
# Core pipeline: query → Parquet → DuckDB → DataFrame
# ---------------------------------------------------------------------------

_BASE_PREFIX     = "DC/Parquet_files"
_DEFAULT_WORKERS = 16


def bq_to_df_fix(
    query: str,
    project: str                  = "prj-prod-dataplatform",
    bucket_name: str              = "prod-asia-southeast1-tonik-aiml-workspace",
    gcs_folder: str               = _BASE_PREFIX,
    max_workers: int              = _DEFAULT_WORKERS,
    keep_gcs_files: bool          = False,
    local_tmp_dir: Optional[str]  = None,
    dataset_location: str         = "asia-southeast1",
) -> pd.DataFrame:
    """
    Run a BigQuery SQL query and return the result as a pandas DataFrame.

    Handles unsupported DuckDB types automatically:
      TIME WITH TIME ZONE, DATETIME, JSON, INTERVAL  →  cast to STRING

    Flow
    ----
    1. Dry-run the query to inspect schema (free)
    2. Wrap query to cast any unsupported types → STRING
    3. Run the safe query and save result to a BQ anonymous table
    4. Export anonymous table → GCS Parquet (no bytes billed)
    5. Download shards in parallel
    6. Delete GCS files immediately
    7. Read Parquet into DataFrame via DuckDB

    Parameters
    ----------
    query           : Any valid BigQuery SQL (SELECT, WITH, subqueries, etc.)
    project         : GCP project ID
    bucket_name     : GCS bucket for staging
    gcs_folder      : Prefix inside bucket (default DC/Parquet_files)
    max_workers     : Parallel GCS threads (default 16)
    keep_gcs_files  : If True, don't delete GCS files after download
    local_tmp_dir   : Override temp directory for Parquet shards
    dataset_location: BigQuery region

    Returns
    -------
    pd.DataFrame
    """
    bq_client = bigquery.Client(project=project)
    run_id    = uuid.uuid4().hex[:12]
    prefix    = f"{gcs_folder}/{run_id}/tmp_result"

    # ── Step 1 & 2: inspect schema, wrap query for safe export ────────────
    safe_query, cast_columns = _wrap_query_for_safe_export(bq_client, query)

    # ── Step 3: run the query → anonymous destination table ───────────────
    logger.info("Running query (anonymous destination, no named table)")
    job_config = bigquery.QueryJobConfig(
        use_query_cache          = True,
        allow_large_results      = True,
        create_disposition       = bigquery.CreateDisposition.CREATE_IF_NEEDED,
        write_disposition        = bigquery.WriteDisposition.WRITE_TRUNCATE,
    )
    query_job = bq_client.query(safe_query, job_config=job_config, location=dataset_location)
    query_job.result()

    dest_table = query_job.destination
    logger.info("Query finished. Anonymous result table: %s", dest_table)

    # ── Step 4: export anonymous table → GCS Parquet ──────────────────────
    dest_uri   = f"gs://{bucket_name}/{prefix}-*.parquet"
    logger.info("Extracting results to %s", dest_uri)

    extract_config = bigquery.ExtractJobConfig(
        destination_format = bigquery.DestinationFormat.PARQUET,
        compression        = bigquery.Compression.SNAPPY,
    )
    extract_job = bq_client.extract_table(
        dest_table, dest_uri,
        job_config=extract_config,
        location=dataset_location,
    )
    extract_job.result()

    # List the shards written
    gcs_client = storage.Client(project=project)
    blobs      = list(gcs_client.bucket(bucket_name).list_blobs(prefix=f"{gcs_folder}/{run_id}/"))
    logger.info("Downloading %d parquet shard(s) with %d workers", len(blobs), max_workers)

    # ── Step 5: parallel download ──────────────────────────────────────────
    use_tmp = local_tmp_dir is None
    tmp_ctx  = tempfile.TemporaryDirectory(prefix="bq2df_") if use_tmp else None
    local_dir = Path(tmp_ctx.name if use_tmp else local_tmp_dir)
    local_dir.mkdir(parents=True, exist_ok=True)

    local_paths: list[Path] = []
    failed: list[str] = []

    with ThreadPoolExecutor(max_workers=min(max_workers, len(blobs))) as pool:
        futures = {
            pool.submit(_download_blob, b.name, bucket_name, project, local_dir): b.name
            for b in blobs
        }
        for fut in as_completed(futures):
            try:
                local_paths.append(fut.result())
            except Exception as exc:
                failed.append(futures[fut])
                logger.error("Failed to download %s: %s", futures[fut], exc)

    if failed:
        raise RuntimeError(f"Download failed for: {failed}")

    # ── Step 6: delete GCS files in parallel ──────────────────────────────
    if not keep_gcs_files:
        with ThreadPoolExecutor(max_workers=min(max_workers, len(blobs))) as pool:
            futs = [pool.submit(_delete_blob, b.name, bucket_name, project) for b in blobs]
            for f in as_completed(futs):
                try:
                    f.result()
                except Exception as exc:
                    logger.warning("GCS delete warning: %s", exc)
        logger.info("Deleted %d GCS parquet file(s)", len(blobs))

    # ── Step 7: read Parquet → DataFrame via DuckDB ───────────────────────
    logger.info("Combining %d local parquet file(s) via DuckDB", len(local_paths))
    glob_path = str(local_dir / "*.parquet")

    con = duckdb.connect()
    con.execute(f"PRAGMA threads={os.cpu_count() or 4}")
    try:
        df = con.execute(f"SELECT * FROM read_parquet('{glob_path}')").df()
    finally:
        con.close()
        if use_tmp and tmp_ctx:
            tmp_ctx.cleanup()

    logger.info("Loaded DataFrame with shape %s", df.shape)

    # ── Log type casting summary ───────────────────────────────────────────
    if cast_columns:
        logger.info(
            "Note: %d column(s) were cast to string during export "
            "(TIME WITH TIME ZONE / DATETIME / JSON / INTERVAL): %s",
            len(cast_columns), cast_columns,
        )

    return df