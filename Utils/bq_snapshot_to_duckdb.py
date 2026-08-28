"""
bq_snapshot_to_duckdb.py
────────────────────────
Importable module. Cost-minimised BQ → DuckDB pipeline via GCS staging.

  BigQuery  ──(Export Job / $0 billed)──►  GCS Parquet shards
            ──(parallel download)       ──►  local tmp
            ──(DuckDB shard-by-shard)   ──►  DuckDB table
            ──(immediate GCS delete)        (no lingering storage cost)

Usage
─────
  from bq_snapshot_to_duckdb import run_pipeline

  tables = run_pipeline(
      bq_dataset  = "worktable_data_analysis",
      bq_table_id = "bscore_model_full_features_model_dataset_snapshot_20260713",
  )
  # returns list[dict] — every table now in my_database.db

All parameters have sensible defaults; override only what you need.
"""

import os
import uuid
import shutil
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Optional

import duckdb
from google.cloud import bigquery, storage


# ── Logging ───────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


# ── Config dataclass ──────────────────────────────────────────────────────────

@dataclass
class PipelineConfig:
    # BigQuery
    bq_dataset:     str = "worktable_data_analysis"
    bq_table_id:    str = "bscore_model_full_features_model_dataset_snapshot_20260713"
    bq_location:    str = "asia-southeast1"

    # GCP / GCS
    project:        str = "prj-prod-dataplatform"
    bucket_name:    str = "prod-asia-southeast1-tonik-aiml-workspace"
    gcs_folder:     str = "DC/Parquet_files"

    # DuckDB
    duckdb_path:    str = os.path.join(".", "duckdb", "my_database.db")
    duckdb_table:   Optional[str] = None   # defaults to bq_table_id
    memory_limit:   str = "4GB"
    duckdb_threads: int = 4

    # Pipeline
    max_workers:    int = 16
    local_tmp_root: str = os.path.join(".", "tmp_parquet")

    def __post_init__(self):
        # table name mirrors BQ table unless caller overrides
        if self.duckdb_table is None:
            self.duckdb_table = self.bq_table_id


# ─────────────────────────────────────────────────────────────────────────────
# Step 0 · GCS access check
# ─────────────────────────────────────────────────────────────────────────────

def _verify_gcs_access(bucket: storage.Bucket, prefix: str) -> None:
    """
    Sentinel write/read/delete.
    Works with object-level IAM (storage.objects.*) when
    bucket-level storage.buckets.get is NOT granted.
    """
    sentinel = bucket.blob(f"{prefix}/.sentinel")
    sentinel.upload_from_string(b"ok")
    sentinel.download_as_bytes()
    sentinel.delete()
    log.info("GCS access verified ✓")


# ─────────────────────────────────────────────────────────────────────────────
# Step 1 · Export BQ → GCS  ($0 bytes billed)
# ─────────────────────────────────────────────────────────────────────────────

def _export_bq_to_gcs(
    bq_client: bigquery.Client,
    cfg: PipelineConfig,
    gcs_prefix: str,
) -> None:
    """
    BQ Export Jobs bill ZERO bytes.
    Snappy Parquet: best speed/size trade-off for DuckDB reads.
    '*' wildcard lets BQ auto-shard large tables.
    """
    table_ref = bq_client.dataset(cfg.bq_dataset, project=cfg.project).table(cfg.bq_table_id)
    dest_uri  = f"gs://{cfg.bucket_name}/{gcs_prefix}/*.parquet"

    job_config = bigquery.ExtractJobConfig(
        destination_format=bigquery.DestinationFormat.PARQUET,
        compression=bigquery.Compression.SNAPPY,
    )

    log.info(f"Exporting  {cfg.bq_dataset}.{cfg.bq_table_id}  →  {dest_uri}")
    job = bq_client.extract_table(
        table_ref, dest_uri, job_config=job_config, location=cfg.bq_location
    )
    job.result()
    log.info("BQ export complete ✓")


# ─────────────────────────────────────────────────────────────────────────────
# Step 2 · List exported blobs
# ─────────────────────────────────────────────────────────────────────────────

def _list_parquet_blobs(bucket: storage.Bucket, cfg: PipelineConfig, prefix: str) -> list:
    blobs = [b for b in bucket.list_blobs(prefix=prefix) if b.name.endswith(".parquet")]
    if not blobs:
        raise RuntimeError(f"No Parquet files found under gs://{cfg.bucket_name}/{prefix}")
    log.info(f"Found {len(blobs)} Parquet shard(s) in GCS.")
    return blobs


# ─────────────────────────────────────────────────────────────────────────────
# Step 3 · Parallel download
# ─────────────────────────────────────────────────────────────────────────────

def _download_one(blob: storage.Blob, local_dir: str) -> str:
    local_path = os.path.join(local_dir, os.path.basename(blob.name))
    blob.download_to_filename(local_path)
    return local_path


def _download_parallel(blobs: list, local_dir: str, workers: int) -> list:
    os.makedirs(local_dir, exist_ok=True)
    local_paths, errors = [], []

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_download_one, b, local_dir): b for b in blobs}
        for fut in as_completed(futures):
            try:
                local_paths.append(fut.result())
            except Exception as exc:
                errors.append(exc)
                log.error(f"Download failed: {exc}")

    if errors:
        raise RuntimeError(f"{len(errors)} download(s) failed — aborting.")

    log.info(f"Downloaded {len(local_paths)} file(s) → {local_dir}  ✓")
    return local_paths


# ─────────────────────────────────────────────────────────────────────────────
# Step 4 · Delete GCS blobs immediately
# ─────────────────────────────────────────────────────────────────────────────

def _delete_parallel(blobs: list, workers: int) -> None:
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(b.delete): b for b in blobs}
        for fut in as_completed(futures):
            try:
                fut.result()
            except Exception as exc:
                log.warning(f"GCS delete failed (non-fatal): {exc}")
    log.info(f"Deleted {len(blobs)} GCS blob(s) ✓")


# ─────────────────────────────────────────────────────────────────────────────
# Step 5 · Load Parquet shards → DuckDB (memory-safe, one shard at a time)
# ─────────────────────────────────────────────────────────────────────────────

def _configure_duckdb(conn: duckdb.DuckDBPyConnection, cfg: PipelineConfig) -> None:
    """
    memory_limit   — hard cap; DuckDB raises before OOM-killing the process.
    temp_directory — spill-to-disk path; used automatically when limit nears.
    threads        — lower count = lower peak RAM per operation.
    """
    db_dir   = os.path.dirname(os.path.abspath(cfg.duckdb_path))
    temp_dir = os.path.join(db_dir, "duckdb_tmp").replace("\\", "/")
    os.makedirs(temp_dir, exist_ok=True)

    conn.execute(f"SET memory_limit   = '{cfg.memory_limit}'")
    conn.execute(f"SET temp_directory = '{temp_dir}'")
    conn.execute(f"SET threads        = {cfg.duckdb_threads}")

    log.info(
        f"DuckDB config — memory_limit={cfg.memory_limit}, "
        f"threads={cfg.duckdb_threads}, temp_directory={temp_dir}"
    )


def _load_to_duckdb(local_dir: str, cfg: PipelineConfig) -> int:
    """
    Shard-by-shard loader — peak RAM = 1 shard at any time.

    CREATE TABLE from shard[0]   → schema inferred, data loaded
    INSERT INTO  from shard[1…]  → one file per transaction
    temp_directory spills if memory_limit is approached
    Returns final row count.
    """
    os.makedirs(os.path.dirname(os.path.abspath(cfg.duckdb_path)), exist_ok=True)

    shards = sorted(
        os.path.join(local_dir, f)
        for f in os.listdir(local_dir)
        if f.endswith(".parquet")
    )
    if not shards:
        raise FileNotFoundError(f"No .parquet files found in {local_dir}")

    total      = len(shards)
    table_name = cfg.duckdb_table
    log.info(f"Loading {total} shard(s) into DuckDB table '{table_name}' …")

    conn = duckdb.connect(cfg.duckdb_path)
    try:
        _configure_duckdb(conn, cfg)

        # 1 — Bootstrap table from first shard (schema + data)
        first = shards[0].replace("\\", "/")
        conn.execute(f"DROP TABLE IF EXISTS {table_name}")
        conn.execute(
            f"CREATE TABLE {table_name} AS "
            f"SELECT * FROM read_parquet('{first}', hive_partitioning = false)"
        )
        log.info(f"  [1/{total}] {os.path.basename(first)} — table created")

        # 2 — Insert remaining shards one at a time
        for idx, shard in enumerate(shards[1:], start=2):
            shard_fwd = shard.replace("\\", "/")
            conn.execute(
                f"INSERT INTO {table_name} "
                f"SELECT * FROM read_parquet('{shard_fwd}', hive_partitioning = false)"
            )
            log.info(f"  [{idx}/{total}] {os.path.basename(shard)} — inserted")

        row_count = conn.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]
        log.info(f"Table '{table_name}' ready — {row_count:,} rows ✓")
        return row_count

    finally:
        conn.close()


# ─────────────────────────────────────────────────────────────────────────────
# Step 6 · Cleanup local tmp
# ─────────────────────────────────────────────────────────────────────────────

def _cleanup_local(local_dir: str) -> None:
    shutil.rmtree(local_dir, ignore_errors=True)
    log.info(f"Local tmp removed: {local_dir}")


# ─────────────────────────────────────────────────────────────────────────────
# Public utility — list all tables in a DuckDB file
# ─────────────────────────────────────────────────────────────────────────────

def list_duckdb_tables(duckdb_path: str) -> list:
    """
    Returns a list of dicts, one per table in the database:
      [{"table_name": str, "row_count": int, "column_count": int}, …]
    Sorted by table_name. Can be called independently at any time.
    """
    conn = duckdb.connect(duckdb_path, read_only=True)
    try:
        rows = conn.execute("""
            SELECT
                table_name,
                estimated_size  AS row_count,
                column_count
            FROM duckdb_tables()
            ORDER BY table_name
        """).fetchall()
    finally:
        conn.close()

    return [
        {"table_name": r[0], "row_count": r[1], "column_count": r[2]}
        for r in rows
    ]


def _print_table_summary(tables: list, duckdb_path: str) -> None:
    bar = "─" * 74
    log.info(bar)
    log.info(f"  All tables in: {duckdb_path}")
    log.info(bar)
    if not tables:
        log.info("  (database is empty)")
    else:
        log.info(f"  {'TABLE NAME':<50}  {'ROW COUNT':>12}  {'COLS':>5}")
        log.info("  " + "─" * 72)
        for t in tables:
            log.info(
                f"  {t['table_name']:<50}  {t['row_count']:>12,}  {t['column_count']:>5}"
            )
    log.info(bar)


# ─────────────────────────────────────────────────────────────────────────────
# Public entry-point
# ─────────────────────────────────────────────────────────────────────────────

def run_pipeline(
    bq_dataset:     str           = "worktable_data_analysis",
    bq_table_id:    str           = "bscore_model_full_features_model_dataset_snapshot_20260713",
    bq_location:    str           = "asia-southeast1",
    project:        str           = "prj-prod-dataplatform",
    bucket_name:    str           = "prod-asia-southeast1-tonik-aiml-workspace",
    gcs_folder:     str           = "DC/Parquet_files",
    duckdb_path:    str           = os.path.join(".", "duckdb", "my_database.db"),
    duckdb_table:   Optional[str] = None,
    memory_limit:   str           = "4GB",
    duckdb_threads: int           = 4,
    max_workers:    int           = 16,
) -> list:
    """
    Run the full BQ → GCS → DuckDB pipeline.

    Parameters
    ──────────
    bq_dataset      BigQuery dataset name
    bq_table_id     BigQuery table name (no dataset prefix)
    bq_location     Region for BQ export job; must match your GCS bucket region
    project         GCP project ID
    bucket_name     GCS bucket name (no gs:// prefix)
    gcs_folder      GCS key prefix for staging files, e.g. "DC/Parquet_files"
    duckdb_path     Path to the target .db file (created if absent)
    duckdb_table    DuckDB table name — defaults to bq_table_id if None
    memory_limit    DuckDB RAM cap, e.g. "4GB", "8GB", "16GB"
    duckdb_threads  DuckDB thread count (lower = less peak RAM per operation)
    max_workers     Thread-pool size for parallel GCS download / delete

    Returns
    ───────
    list[dict]  All tables now in duckdb_path, sorted by name.
                Each dict: {"table_name": str, "row_count": int, "column_count": int}

    Example
    ───────
    from bq_snapshot_to_duckdb import run_pipeline

    tables = run_pipeline(
        bq_dataset    = "worktable_data_analysis",
        bq_table_id   = "bscore_model_full_features_model_dataset_snapshot_20260713",
        duckdb_path   = "./duckdb/my_database.db",
        memory_limit  = "8GB",
    )
    for t in tables:
        print(t["table_name"], t["row_count"])
    """
    cfg = PipelineConfig(
        bq_dataset     = bq_dataset,
        bq_table_id    = bq_table_id,
        bq_location    = bq_location,
        project        = project,
        bucket_name    = bucket_name,
        gcs_folder     = gcs_folder,
        duckdb_path    = duckdb_path,
        duckdb_table   = duckdb_table,
        memory_limit   = memory_limit,
        duckdb_threads = duckdb_threads,
        max_workers    = max_workers,
    )

    run_id     = uuid.uuid4().hex[:8]
    gcs_prefix = f"{cfg.gcs_folder}/{cfg.bq_dataset}/{cfg.bq_table_id}/{run_id}"
    local_run  = os.path.join(cfg.local_tmp_root, run_id)

    log.info("=" * 60)
    log.info(f"Run ID      : {run_id}")
    log.info(f"BQ source   : {cfg.bq_dataset}.{cfg.bq_table_id}")
    log.info(f"GCS staging : gs://{cfg.bucket_name}/{gcs_prefix}/")
    log.info(f"DuckDB      : {cfg.duckdb_path}  →  table '{cfg.duckdb_table}'")
    log.info(f"Memory cap  : {cfg.memory_limit}  |  threads: {cfg.duckdb_threads}")
    log.info("=" * 60)

    bq_client  = bigquery.Client(project=cfg.project)
    gcs_client = storage.Client(project=cfg.project)
    bucket     = gcs_client.bucket(cfg.bucket_name)

    blobs = None
    try:
        # 0 · GCS access check (sentinel; no bucket.get IAM needed)
        _verify_gcs_access(bucket, gcs_prefix)

        # 1 · BQ Export → GCS  ($0 bytes billed)
        _export_bq_to_gcs(bq_client, cfg, gcs_prefix)

        # 2 · List shards
        blobs = _list_parquet_blobs(bucket, cfg, gcs_prefix)

        # 3 · Parallel download
        _download_parallel(blobs, local_run, cfg.max_workers)

        # 4 · Delete GCS immediately (cost control)
        _delete_parallel(blobs, cfg.max_workers)
        blobs = None

        # 5 · Load into DuckDB (shard-by-shard, memory-safe)
        _load_to_duckdb(local_run, cfg)

        # 6 · Remove local tmp
        _cleanup_local(local_run)

    except Exception:
        log.exception("Pipeline failed — attempting GCS cleanup …")
        if blobs:
            try:
                _delete_parallel(blobs, cfg.max_workers)
            except Exception:
                log.warning("GCS cleanup on error also failed — check manually.")
        raise

    # 7 · List all tables in the database and return them
    tables = list_duckdb_tables(cfg.duckdb_path)
    _print_table_summary(tables, cfg.duckdb_path)
    log.info("Pipeline complete ✓")
    return tables


# ─────────────────────────────────────────────────────────────────────────────
# CLI fallback   (python bq_snapshot_to_duckdb.py)
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    run_pipeline()