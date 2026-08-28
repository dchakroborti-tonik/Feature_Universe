"""
bq_fast_download.py

Fast BigQuery -> pandas DataFrame utility.

Strategy (no permanent/named destination table needed):
1. Run the query as a normal query job (no explicit destination). BigQuery
   automatically writes results to its own hidden anonymous temp table,
   which (unlike an explicit destination table) allows duplicate column
   names in the result set. This avoids the "Duplicate column names ...
   destination table is present" error entirely.
2. Export that anonymous temp table directly to GCS as sharded Parquet
   files using `extract_table`. The extract job itself has no BigQuery
   processing cost (you're only billed for the original query's bytes
   scanned); the only cost is the GCS storage the shards occupy briefly
   and standard egress if you download cross-region.
3. Download the Parquet shards from GCS in parallel (ThreadPoolExecutor,
   configurable worker count) into a local temp dir.
4. Combine + read all shards into a single DataFrame using DuckDB
   (fast, multi-threaded, handles many files via glob in one call).
5. Clean up: delete the GCS shards and local temp files. Nothing to clean
   up on the BigQuery side -- the anonymous temp table is managed and
   expired automatically by BigQuery (~24h), and it was never named or
   billed as a stored table.

Usage
-----
from util.bq_fast_download import bq_to_df

df = bq_to_df('''
    SELECT *
    FROM `prj-prod-dataplatform.some_dataset.some_table`
    WHERE date >= "2026-01-01"
''')
"""

import os
import uuid
import shutil
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

import duckdb
import pandas as pd
from google.cloud import bigquery
from google.cloud import storage

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# ---- Defaults (override via function args if needed) ----
DEFAULT_PROJECT = "prj-prod-dataplatform"
DEFAULT_BUCKET = "prod-asia-southeast1-tonik-aiml-workspace"
DEFAULT_GCS_FOLDER = "DC/Parquet_files"
DEFAULT_LOCATION = "asia-southeast1"
DEFAULT_MAX_WORKERS = 16


def bq_to_df(
    query: str,
    project: str = DEFAULT_PROJECT,
    bucket_name: str = DEFAULT_BUCKET,
    gcs_folder: str = DEFAULT_GCS_FOLDER,
    max_workers: int = DEFAULT_MAX_WORKERS,
    keep_gcs_files: bool = False,
    local_tmp_dir: str = None,
    dataset_location: str = DEFAULT_LOCATION,
) -> pd.DataFrame:
    """
    Run a BigQuery query and return the result as a pandas DataFrame,
    using GCS Parquet export + parallel download + DuckDB read for speed.
    Does NOT create any named/permanent BigQuery table.

    Parameters
    ----------
    query : str
        The SQL query to run.
    project : str
        GCP project ID (billing project).
    bucket_name : str
        GCS bucket name (no gs:// prefix).
    gcs_folder : str
        Folder path inside the bucket to stage parquet files.
    max_workers : int
        Number of parallel threads for downloading Parquet shards from GCS.
    keep_gcs_files : bool
        If True, do not delete the exported Parquet files from GCS afterwards.
    local_tmp_dir : str
        Local directory to stage downloaded parquet files. Defaults to a
        unique folder under the system tmp dir, auto-cleaned afterwards.
    dataset_location : str
        BigQuery region/location (e.g. "asia-southeast1") to run the query in.
        Should match the location of the source tables.

    Returns
    -------
    pd.DataFrame
    """
    bq_client = bigquery.Client(project=project, location=dataset_location)
    storage_client = storage.Client(project=project)
    bucket = storage_client.bucket(bucket_name)

    run_id = uuid.uuid4().hex[:12]
    gcs_prefix = f"{gcs_folder.rstrip('/')}/{run_id}"
    gcs_uri = f"gs://{bucket_name}/{gcs_prefix}/tmp_result-*.parquet"

    local_dir = local_tmp_dir or os.path.join("/tmp", f"bq_download_{run_id}")
    os.makedirs(local_dir, exist_ok=True)

    try:
        # ---- 1. Run the query with NO explicit destination table ----
        # BigQuery writes results to its own hidden anonymous temp table,
        # which permits duplicate column names in the result set.
        logger.info("Running query (anonymous destination, no named table)")
        query_job = bq_client.query(query)
        query_job.result()  # wait for completion

        anon_table = query_job.destination
        logger.info(
            "Query finished. Anonymous result table: %s.%s.%s",
            anon_table.project, anon_table.dataset_id, anon_table.table_id,
        )

        # ---- 2. Export the anonymous temp table to GCS as Parquet ----
        logger.info("Extracting results to %s", gcs_uri)
        extract_job = bq_client.extract_table(
            anon_table,
            gcs_uri,
            job_config=bigquery.job.ExtractJobConfig(destination_format="PARQUET"),
        )
        extract_job.result()

        # ---- 3. List and download shards in parallel ----
        blobs = list(bucket.list_blobs(prefix=gcs_prefix))
        if not blobs:
            raise RuntimeError(f"No parquet files found at gs://{bucket_name}/{gcs_prefix}")

        logger.info("Downloading %d parquet shard(s) with %d workers", len(blobs), max_workers)

        local_paths = []

        def _download(blob):
            local_path = os.path.join(local_dir, os.path.basename(blob.name))
            blob.download_to_filename(local_path)
            return local_path

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(_download, blob): blob.name for blob in blobs}
            for future in as_completed(futures):
                blob_name = futures[future]
                try:
                    local_paths.append(future.result())
                except Exception as e:
                    logger.error("Failed downloading %s: %s", blob_name, e)
                    raise

        # ---- 4. Combine + read all shards into a single DataFrame via DuckDB ----
        logger.info("Combining %d local parquet file(s) via DuckDB", len(local_paths))
        glob_path = os.path.join(local_dir, "*.parquet")
        df = duckdb.sql(f"SELECT * FROM read_parquet('{glob_path}')").df()

        logger.info("Loaded DataFrame with shape %s", df.shape)
        return df

    finally:
        # ---- 5. Cleanup: local files + GCS files ----
        # (No BigQuery cleanup needed -- the anonymous temp table was never
        # named/stored by us and auto-expires on Google's side.)
        try:
            shutil.rmtree(local_dir, ignore_errors=True)
        except Exception as e:
            logger.warning("Could not remove local temp dir %s: %s", local_dir, e)

        if not keep_gcs_files:
            try:
                blobs_to_delete = list(bucket.list_blobs(prefix=gcs_prefix))
                for blob in blobs_to_delete:
                    blob.delete()
                logger.info("Deleted %d GCS parquet file(s)", len(blobs_to_delete))
            except Exception as e:
                logger.warning("Could not delete GCS files at %s: %s", gcs_prefix, e)