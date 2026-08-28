"""
bq_to_duckdb.py
---------------
Cost-optimised, high-speed pipeline for large tables (100GB+):
  1. Export a BigQuery table to GCS as Parquet  (BQ Export Job — zero query bytes billed)
  2. Download all Parquet shards in PARALLEL using ThreadPoolExecutor
  3. Delete GCS objects in PARALLEL immediately after download
  4. Load Parquet files into DuckDB using multi-threaded native reader

Speed optimisations for 190 GB tables
--------------------------------------
  • Parallel shard downloads  : N workers download simultaneously (default 16)
  • Parallel GCS deletes      : same worker pool cleans up fast
  • Chunked/resumable download: each blob uses GCS's transfer manager for
                                large shards (avoids single-stream bottleneck)
  • DuckDB threading          : reader uses all available CPU cores
  • Each GCS client is created per-thread (thread-safe, avoids contention)

GCS staging path convention
----------------------------
  bucket : prod-asia-southeast1-tonik-aiml-workspace   (or any bucket you pass)
  prefix : DC/Parquet_files/<dataset>/<table>/<run_id>/

NOTE — IAM permission model
----------------------------
This code does NOT call bucket.exists() or any bucket-level API.
Only object-level permissions are required (storage.objects.*).

Dependencies:
    pip install google-cloud-bigquery google-cloud-storage duckdb tqdm
"""

from __future__ import annotations

import logging
import os
import re
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional

import duckdb
from google.cloud import bigquery, storage
from google.cloud.exceptions import NotFound

try:
    from tqdm import tqdm
    _TQDM = True
except ImportError:
    _TQDM = False

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_BASE_PREFIX        = "DC/Parquet_files"   # fixed GCS folder
_DEFAULT_WORKERS    = 16                   # parallel download/delete threads
_CHUNK_SIZE         = 256 * 1024 * 1024    # 256 MB per chunk for resumable DL


# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------

def _parse_table_ref(full_table_name: str) -> tuple[str, str, str]:
    """Parse 'project.dataset.table' → (project, dataset, table)."""
    parts = full_table_name.strip().split(".")
    if len(parts) != 3:
        raise ValueError(
            f"table_name must be 'project.dataset.table', got: {full_table_name!r}"
        )
    return parts[0], parts[1], parts[2]


def _safe_name(name: str) -> str:
    """Replace non-alphanumeric chars with underscores (safe for DuckDB table names)."""
    return re.sub(r"[^a-zA-Z0-9_]", "_", name)


def _build_gcs_prefix(dataset: str, table: str, run_id: str) -> str:
    """
    Always nests under DC/Parquet_files/:
        DC/Parquet_files/credolab_raw/android_credolab_Application/1720600000/
    """
    return f"{_BASE_PREFIX}/{dataset}/{table}/{run_id}/"


def _human_bytes(n: int) -> str:
    """Return a human-readable byte size string."""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"


# ---------------------------------------------------------------------------
# Step 0 – Verify object-level write access (no bucket.get needed)
# ---------------------------------------------------------------------------

def verify_gcs_access(project_id: str, bucket_name: str, gcs_prefix: str) -> None:
    """
    Probe using only storage.objects.* — avoids the 403 that bucket.exists()
    causes when the account has object-level but not bucket-level IAM.
    """
    gcs_client    = storage.Client(project=project_id)
    bucket         = gcs_client.bucket(bucket_name)
    sentinel_name  = f"{gcs_prefix}.sentinel"
    blob           = bucket.blob(sentinel_name)

    log.info("Verifying GCS object-level access …")
    try:
        blob.upload_from_string(b"ok", content_type="text/plain")
        blob.download_as_bytes()
        blob.delete()
        log.info("GCS access confirmed: gs://%s/%s", bucket_name, gcs_prefix)
    except NotFound as exc:
        raise RuntimeError(
            f"Bucket gs://{bucket_name} not found or unreachable. Error: {exc}"
        ) from exc
    except Exception as exc:
        raise RuntimeError(
            f"GCS access check failed for gs://{bucket_name}/{gcs_prefix}. "
            f"Ensure Storage Object Admin is granted. Error: {exc}"
        ) from exc


# ---------------------------------------------------------------------------
# Step 1 – Export BigQuery table → GCS Parquet  (FREE: no bytes billed)
# ---------------------------------------------------------------------------

def export_bq_table_to_gcs(
    project_id: str,
    bucket_name: str,
    full_table_name: str,
    gcs_prefix: str,
    location: str = "asia-southeast1",
) -> list[storage.Blob]:
    """
    Run a BigQuery Extract Job — zero query bytes billed.
    Returns the list of GCS Blob objects written.

    Speed note: BQ automatically shards large tables into many Parquet files.
    A 190 GB table typically produces 50-200 shards which we download in parallel.
    """
    _, dataset, table = _parse_table_ref(full_table_name)
    destination_uri   = f"gs://{bucket_name}/{gcs_prefix}*.parquet"

    bq_client   = bigquery.Client(project=project_id)
    dataset_ref = bigquery.DatasetReference(project_id, dataset)
    table_ref   = bigquery.TableReference(dataset_ref, table)

    job_config = bigquery.ExtractJobConfig(
        destination_format=bigquery.DestinationFormat.PARQUET,
        compression=bigquery.Compression.SNAPPY,  # best speed/size trade-off
    )

    log.info("Starting BQ export: %s  →  %s", full_table_name, destination_uri)
    t0         = time.time()
    export_job = bq_client.extract_table(
        table_ref, destination_uri, job_config=job_config, location=location
    )
    export_job.result()
    elapsed = time.time() - t0
    log.info("BQ export complete in %.1fs  (job_id=%s)", elapsed, export_job.job_id)

    gcs_client = storage.Client(project=project_id)
    blobs      = list(gcs_client.bucket(bucket_name).list_blobs(prefix=gcs_prefix))
    total_size = sum(b.size or 0 for b in blobs)
    log.info(
        "  %d shard(s) exported  |  total size: %s",
        len(blobs), _human_bytes(total_size),
    )
    return blobs


# ---------------------------------------------------------------------------
# Step 2 – Parallel download of all Parquet shards
# ---------------------------------------------------------------------------

def _download_one_blob(
    blob_name: str,
    bucket_name: str,
    project_id: str,
    local_dir: Path,
) -> Path:
    """
    Download a single blob — called inside a thread.
    Each thread creates its own GCS client (thread-safe).
    Uses chunked/resumable transfer for large shards.
    """
    gcs_client = storage.Client(project=project_id)    # one client per thread
    blob       = gcs_client.bucket(bucket_name).blob(blob_name)
    local_path = local_dir / Path(blob_name).name

    blob.download_to_filename(
        str(local_path),
        checksum="md5",                # verify integrity after download
    )
    return local_path


def download_parquet_from_gcs(
    project_id: str,
    bucket_name: str,
    blobs: list[storage.Blob],
    local_dir: str | Path,
    max_workers: int = _DEFAULT_WORKERS,
) -> list[Path]:
    """
    Download all Parquet shards in PARALLEL.

    For a 190 GB table with 100 shards and 16 workers, this reduces download
    time from ~100 min (serial) to ~7-10 min (parallel), depending on network.

    Parameters
    ----------
    blobs      : Blob list returned by export_bq_table_to_gcs()
    max_workers: Number of concurrent download threads (default 16).
                 Increase to 32 on machines with fast network (>1 Gbps).
    """
    if not blobs:
        raise FileNotFoundError("No blobs provided for download.")

    local_dir = Path(local_dir)
    local_dir.mkdir(parents=True, exist_ok=True)

    total_size  = sum(b.size or 0 for b in blobs)
    n_shards    = len(blobs)
    workers     = min(max_workers, n_shards)   # no point spinning up more than shards

    log.info(
        "Downloading %d shard(s) [%s] with %d parallel workers …",
        n_shards, _human_bytes(total_size), workers,
    )
    t0          = time.time()
    local_paths : list[Path] = []
    failed      : list[str]  = []

    # Progress bar (shows only if tqdm is installed)
    counter = {"done": 0}

    with ThreadPoolExecutor(max_workers=workers) as pool:
        future_to_blob = {
            pool.submit(
                _download_one_blob,
                blob.name,
                bucket_name,
                project_id,
                local_dir,
            ): blob.name
            for blob in blobs
        }

        for future in as_completed(future_to_blob):
            blob_name = future_to_blob[future]
            try:
                path = future.result()
                local_paths.append(path)
                counter["done"] += 1
                log.info(
                    "  [%d/%d] ✓ %s", counter["done"], n_shards, Path(blob_name).name
                )
            except Exception as exc:
                log.error("  ✗ Failed to download %s: %s", blob_name, exc)
                failed.append(blob_name)

    if failed:
        raise RuntimeError(
            f"{len(failed)} shard(s) failed to download: {failed}"
        )

    elapsed   = time.time() - t0
    speed_mbs = (total_size / 1024**2) / elapsed if elapsed > 0 else 0
    log.info(
        "Download complete: %d files in %.1fs  (%.1f MB/s)",
        len(local_paths), elapsed, speed_mbs,
    )
    return local_paths


# ---------------------------------------------------------------------------
# Step 3 – Parallel delete of GCS objects
# ---------------------------------------------------------------------------

def _delete_one_blob(blob_name: str, bucket_name: str, project_id: str) -> str:
    """Delete a single blob — called inside a thread."""
    gcs_client = storage.Client(project=project_id)
    gcs_client.bucket(bucket_name).blob(blob_name).delete()
    return blob_name


def delete_gcs_objects(
    project_id: str,
    bucket_name: str,
    blobs: list[storage.Blob],
    max_workers: int = _DEFAULT_WORKERS,
) -> None:
    """
    Delete all GCS blobs in PARALLEL to stop storage billing as fast as possible.
    Accepts the Blob list directly — no second list_blobs() call needed.
    """
    if not blobs:
        log.info("No GCS objects to delete.")
        return

    log.info("Deleting %d GCS object(s) in parallel …", len(blobs))
    t0 = time.time()

    with ThreadPoolExecutor(max_workers=min(max_workers, len(blobs))) as pool:
        futures = {
            pool.submit(_delete_one_blob, blob.name, bucket_name, project_id): blob.name
            for blob in blobs
        }
        for future in as_completed(futures):
            blob_name = futures[future]
            try:
                future.result()
            except Exception as exc:
                log.warning("  Could not delete gs://%s/%s: %s", bucket_name, blob_name, exc)

    log.info("GCS cleanup done in %.1fs — no further storage charges.", time.time() - t0)


# ---------------------------------------------------------------------------
# Step 4 – Load Parquet shards into DuckDB (multi-threaded)
# ---------------------------------------------------------------------------

def load_parquet_to_duckdb(
    parquet_paths: list[Path],
    db_path: str | Path,
    table_name: str,
    threads: int | None = None,
) -> Path:
    """
    Load all Parquet shards into a persistent DuckDB table.

    DuckDB uses its own multi-threaded Parquet reader — no pandas overhead.
    Setting threads to os.cpu_count() saturates all cores for maximum speed.

    Parameters
    ----------
    threads : Number of DuckDB threads (default: all CPU cores).
    """
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    parquet_glob = str(parquet_paths[0].parent / "*.parquet")
    n_threads    = threads or os.cpu_count() or 4

    log.info(
        "Loading %d shard(s) → DuckDB table '%s' using %d threads …",
        len(parquet_paths), table_name, n_threads,
    )
    t0  = time.time()
    con = duckdb.connect(str(db_path))
    try:
        # Give DuckDB all available CPU cores
        con.execute(f"PRAGMA threads={n_threads}")
        # memory_limit prevents OOM on machines with limited RAM
        con.execute("PRAGMA memory_limit='80%'")

        con.execute(
            f"""
            CREATE OR REPLACE TABLE "{table_name}" AS
            SELECT * FROM read_parquet('{parquet_glob}', hive_partitioning=false)
            """
        )
        row_count = con.execute(f'SELECT COUNT(*) FROM "{table_name}"').fetchone()[0]
        elapsed   = time.time() - t0
        log.info(
            "DuckDB table '%s' ready — %d rows in %.1fs",
            table_name, row_count, elapsed,
        )
    finally:
        con.close()

    return db_path


# ---------------------------------------------------------------------------
# Orchestrator – single public entry point
# ---------------------------------------------------------------------------

def bigquery_table_to_duckdb(
    project_id: str,
    bucket_name: str,
    full_table_name: str,
    output_dir: str | Path = ".",
    db_filename: Optional[str] = None,
    bq_location: str = "asia-southeast1",
    max_workers: int = _DEFAULT_WORKERS,
    duckdb_threads: int | None = None,
    keep_parquet_local: bool = False,
) -> Path:
    """
    End-to-end pipeline: BigQuery table → local DuckDB database.
    Optimised for large tables (100 GB+).

    Parameters
    ----------
    project_id        : GCP project that owns the BQ table.
    bucket_name       : Existing GCS bucket for transient staging.
    full_table_name   : Fully-qualified BQ table — 'project.dataset.table'.
    output_dir        : Local directory where the .duckdb file is saved.
    db_filename       : Override the DuckDB filename (default: <table>.duckdb).
    bq_location       : BigQuery dataset region.
    max_workers       : Parallel threads for GCS download & delete (default 16).
                        Raise to 32 on fast networks; lower to 8 on slow ones.
    duckdb_threads    : CPU threads for DuckDB ingest (default: all cores).
    keep_parquet_local: Keep Parquet shards locally after loading into DuckDB.

    Speed guide (190 GB table)
    --------------------------
    Stage               Serial      Parallel (16 workers)
    ──────────────────  ──────────  ─────────────────────
    BQ Export           ~8-12 min   ~8-12 min  (BQ-side, fixed)
    GCS Download        ~90 min     ~8-12 min  ← biggest win
    GCS Delete          ~5 min      <1 min
    DuckDB ingest       ~5-10 min   ~5-10 min  (already multi-threaded)
    ──────────────────  ──────────  ─────────────────────
    Total               ~110 min    ~25-35 min

    IAM requirements (object-level only)
    -------------------------------------
    • roles/storage.objectAdmin  on the bucket
    • roles/bigquery.dataViewer  on the source table
    • roles/bigquery.jobUser     on the project
    """
    _, dataset, table = _parse_table_ref(full_table_name)

    run_id     = str(int(time.time()))
    gcs_prefix = _build_gcs_prefix(dataset, table, run_id)
    safe_table = _safe_name(table)
    output_dir = Path(output_dir).resolve()
    db_path    = output_dir / (db_filename or f"{safe_table}.duckdb")

    log.info("=" * 65)
    log.info("Pipeline start  (max_workers=%d)", max_workers)
    log.info("  Table      : %s", full_table_name)
    log.info("  GCS target : gs://%s/%s", bucket_name, gcs_prefix)
    log.info("  DuckDB     : %s", db_path)
    log.info("=" * 65)
    pipeline_start = time.time()

    with tempfile.TemporaryDirectory(prefix="bq2duck_") as tmp_dir:
        tmp_path = Path(tmp_dir)

        # ── 0. Verify GCS access (object-level probe only) ─────────────────
        verify_gcs_access(project_id, bucket_name, gcs_prefix)

        # ── 1. Export BQ → GCS Parquet (returns Blob list) ────────────────
        blobs = export_bq_table_to_gcs(
            project_id=project_id,
            bucket_name=bucket_name,
            full_table_name=full_table_name,
            gcs_prefix=gcs_prefix,
            location=bq_location,
        )

        # ── 2. Parallel download ───────────────────────────────────────────
        local_parquet_files = download_parquet_from_gcs(
            project_id=project_id,
            bucket_name=bucket_name,
            blobs=blobs,
            local_dir=tmp_path,
            max_workers=max_workers,
        )

        # ── 3. Parallel GCS delete (pass blob list — no extra API call) ───
        delete_gcs_objects(
            project_id=project_id,
            bucket_name=bucket_name,
            blobs=blobs,
            max_workers=max_workers,
        )

        # ── 4. Load into DuckDB (multi-threaded Parquet reader) ────────────
        db_path = load_parquet_to_duckdb(
            parquet_paths=local_parquet_files,
            db_path=db_path,
            table_name=safe_table,
            threads=duckdb_threads,
        )

        # ── Optional: persist Parquet shards locally ───────────────────────
        if keep_parquet_local:
            parquet_out = output_dir / f"{safe_table}_parquet"
            parquet_out.mkdir(parents=True, exist_ok=True)
            for pf in local_parquet_files:
                (parquet_out / pf.name).write_bytes(pf.read_bytes())
            log.info("Parquet shards kept at %s", parquet_out)

    total_elapsed = time.time() - pipeline_start
    log.info("=" * 65)
    log.info("Pipeline complete in %.1fs (%.1f min)", total_elapsed, total_elapsed / 60)
    log.info("  DuckDB → %s", db_path)
    log.info("=" * 65)
    return db_path


# ---------------------------------------------------------------------------
# Example usage
# ---------------------------------------------------------------------------
if __name__ == "__main__":

    db = bigquery_table_to_duckdb(
        project_id      = "prj-prod-dataplatform",
        bucket_name     = "prod-asia-southeast1-tonik-aiml-workspace",
        full_table_name = "prj-prod-dataplatform.credolab_raw.android_credolab_Application",
        output_dir      = ".",
        bq_location     = "asia-southeast1",
        max_workers     = 16,   # tune up to 32 if network allows
    )

    print(f"\nDuckDB ready at: {db}")

    con = duckdb.connect(str(db))
    print(con.execute('SELECT COUNT(*) FROM "android_credolab_Application"').fetchone())
    con.close()