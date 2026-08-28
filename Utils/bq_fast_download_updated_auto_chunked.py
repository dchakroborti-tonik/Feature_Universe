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

Fix notes (type errors when combining shards)
----------------------------------------------
Two root causes cause DuckDB to choke when reading multiple BigQuery
Parquet shards via a glob:

  a) Cross-shard schema drift. If a column is entirely NULL in one shard,
     BigQuery's Parquet writer can encode its physical type slightly
     differently than in shards where the column has real values. By
     default `read_parquet()` requires every file in the glob to share
     an identical schema, so this throws a schema/type-mismatch error.

  b) NUMERIC / BIGNUMERIC precision. BigQuery's BIGNUMERIC can hold up
     to 76.76 digits, but DuckDB's DECIMAL type caps out at 38 digits
     of precision -- reading/casting such a column directly can fail.

Fix: after the query finishes, fetch the *authoritative* BigQuery schema
for the anonymous destination table and use it to explicitly (and
safely, via TRY_CAST) coerce every column to a matching DuckDB type,
while reading the glob with `union_by_name=True` to reconcile any
column-set differences across shards. This removes DuckDB's per-file
type-guessing, which is what breaks on (a) and (b) above.

Duplicate column names (the reason this uses an anonymous destination
table in the first place) are auto-detected: if the BigQuery schema
contains duplicate names, strict per-column casting is skipped (falls
back to a plain `SELECT *`, still with `union_by_name=True`) since an
explicit CAST-by-name would be ambiguous. This is logged, not silent.

Usage
-----
from util.bq_fast_download import bq_to_df

df = bq_to_df('''
    SELECT *
    FROM `prj-prod-dataplatform.some_dataset.some_table`
    WHERE date >= "2026-01-01"
''')
"""

import logging
import os
import shutil
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd
from google.cloud import bigquery, storage

import duckdb

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# ---- Defaults (override via function args if needed) ----
DEFAULT_PROJECT = "prj-prod-dataplatform"
DEFAULT_BUCKET = "prod-asia-southeast1-tonik-aiml-workspace"
DEFAULT_GCS_FOLDER = "DC/Parquet_files"
DEFAULT_LOCATION = "asia-southeast1"
DEFAULT_MAX_WORKERS = 16

# BigQuery -> DuckDB scalar type mapping. RECORD/STRUCT and REPEATED
# (array) fields are intentionally NOT in here -- they're handled
# separately in _bq_field_to_duckdb_type() since a scalar CAST on them
# would fail.
_BQ_TO_DUCKDB_SCALAR = {
    "STRING": "VARCHAR",
    "BYTES": "BLOB",
    "INTEGER": "BIGINT",
    "INT64": "BIGINT",
    "FLOAT": "DOUBLE",
    "FLOAT64": "DOUBLE",
    "BOOLEAN": "BOOLEAN",
    "BOOL": "BOOLEAN",
    # Kept as naive TIMESTAMP (not TIMESTAMPTZ) for consistent, tz-naive
    # UTC handling downstream in pandas.
    "TIMESTAMP": "TIMESTAMP",
    "DATETIME": "TIMESTAMP",
    "DATE": "DATE",
    "TIME": "TIME",
    "GEOGRAPHY": "VARCHAR",  # exported as WKT string
    "JSON": "VARCHAR",
}


def _quote_ident(name: str) -> str:
    """Safely quote a DuckDB/SQL identifier, escaping embedded quotes."""
    return '"' + name.replace('"', '""') + '"'


def _bq_field_to_duckdb_type(field) -> str:
    """
    Map a BigQuery SchemaField to an explicit DuckDB CAST target type.

    Returns None when the column should NOT be explicitly cast (arrays /
    structs / records) -- these are left as DuckDB infers them, since a
    scalar CAST on nested or repeated data would fail.
    """
    if field.mode == "REPEATED":
        return None

    bq_type = field.field_type.upper()

    if bq_type in ("RECORD", "STRUCT"):
        return None

    if bq_type in ("NUMERIC", "BIGNUMERIC"):
        precision = field.precision or (38 if bq_type == "NUMERIC" else 76)
        scale = field.scale or (9 if bq_type == "NUMERIC" else 38)
        # DuckDB's DECIMAL tops out at 38 digits of precision. BIGNUMERIC
        # (up to 76.76 digits) won't fit -- fall back to VARCHAR so the
        # exact value is preserved as text instead of erroring out or
        # silently losing precision.
        if precision > 38:
            return "VARCHAR"
        return f"DECIMAL({precision},{scale})"

    return _BQ_TO_DUCKDB_SCALAR.get(bq_type, "VARCHAR")


def _empty_df_from_schema(schema) -> pd.DataFrame:
    """Build an empty (0-row) DataFrame with the right column names."""
    if not schema:
        return pd.DataFrame()
    return pd.DataFrame({field.name: pd.Series(dtype="object") for field in schema})


def bq_to_df(
    query: str,
    project: str = DEFAULT_PROJECT,
    bucket_name: str = DEFAULT_BUCKET,
    gcs_folder: str = DEFAULT_GCS_FOLDER,
    max_workers: int = DEFAULT_MAX_WORKERS,
    keep_gcs_files: bool = False,
    local_tmp_dir: str = None,
    dataset_location: str = DEFAULT_LOCATION,
    enforce_schema: bool = True,
    safe_cast: bool = True,
    chunk_by_customer_id: int = None,
):
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
    enforce_schema : bool
        If True (default), fetch the BigQuery result schema and explicitly
        cast every column to a matching DuckDB type when combining shards.
        This is what fixes cross-shard type-mismatch errors. Automatically
        disabled (with a warning) if the schema contains duplicate column
        names, since a name-based CAST would be ambiguous in that case.
    safe_cast : bool
        If True (default), casts use TRY_CAST (bad/unconvertible values
        become NULL instead of raising). Set False to use a strict CAST
        that raises on the first unconvertible value -- useful for
        surfacing real data issues while debugging.
    chunk_by_customer_id : int or None
        When set, splits the result by unique ``customerId`` values into
        chunks of at most this many customers each, and returns a
        ``list[pd.DataFrame]`` instead of a single DataFrame.  Rows for
        each customer are kept together in the same chunk.  The caller can
        then process each chunk independently and write results
        incrementally (e.g. WRITE_TRUNCATE for the first chunk, then
        WRITE_APPEND for the rest).  When None (default), a single
        DataFrame is returned as before.

    Returns
    -------
    pd.DataFrame
        When ``chunk_by_customer_id`` is None (default).
    list[pd.DataFrame]
        When ``chunk_by_customer_id`` is set.
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
        result_iterator = query_job.result()  # wait for completion
        total_rows = result_iterator.total_rows

        anon_table = query_job.destination
        logger.info(
            "Query finished (%s rows). Anonymous result table: %s.%s.%s",
            total_rows, anon_table.project, anon_table.dataset_id, anon_table.table_id,
        )

        # ---- Fetch the authoritative schema for explicit type casting ----
        table_schema = None
        if enforce_schema:
            try:
                table_schema = bq_client.get_table(anon_table).schema
            except Exception as e:
                logger.warning(
                    "Could not fetch schema for enforced casting (%s); "
                    "falling back to DuckDB's own type inference", e,
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
            if total_rows == 0:
                logger.info("Query returned 0 rows; returning an empty DataFrame")
                return _empty_df_from_schema(table_schema)
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

        # Decide whether we can safely do a strict, schema-enforced cast.
        enforce = enforce_schema and table_schema is not None
        if enforce:
            names = [f.name for f in table_schema]
            if len(names) != len(set(names)):
                dupes = sorted({n for n in names if names.count(n) > 1})
                logger.warning(
                    "Query result contains duplicate column names %s; "
                    "skipping strict per-column schema enforcement to avoid "
                    "ambiguous casts. Falling back to DuckDB's own type "
                    "inference (still using union_by_name to reconcile "
                    "shard schemas).",
                    dupes,
                )
                enforce = False

        if enforce:
            cast_fn = "TRY_CAST" if safe_cast else "CAST"
            select_parts = []
            for field in table_schema:
                duckdb_type = _bq_field_to_duckdb_type(field)
                col = _quote_ident(field.name)
                if duckdb_type is None:
                    select_parts.append(col)
                else:
                    select_parts.append(f"{cast_fn}({col} AS {duckdb_type}) AS {col}")
            select_clause = ", ".join(select_parts)
        else:
            select_clause = "*"

        # union_by_name=True reconciles shards whose column sets differ
        # (e.g. one shard missing a column entirely). Combined with the
        # explicit per-column CAST above, this also resolves the more
        # common case of a shared column having a subtly different
        # inferred physical type across shards.
        query_sql = (
            f"SELECT {select_clause} "
            f"FROM read_parquet('{glob_path}', union_by_name=True)"
        )
        logger.info("Reading parquet shards into DataFrame (enforce_schema=%s)", enforce)

        try:
            # Use an explicit connection so we can configure memory + spill.
            # Spill-to-disk (temp_directory) means DuckDB never OOMs on large
            # result sets -- it just spills intermediate data to local_dir,
            # which is already a temp path that gets cleaned up at the end.
            _duck = duckdb.connect()
            try:
                # Auto-size memory limit to 75% of currently available RAM,
                # capped at 20 GB, so other processes aren't starved.
                try:
                    import psutil as _ps
                    _avail_gb = _ps.virtual_memory().available / 1024 ** 3
                    _limit_gb = min(int(_avail_gb * 0.75), 20)
                except ImportError:
                    _limit_gb = 8  # conservative fallback if psutil not installed
                _duck.execute(f"SET memory_limit='{_limit_gb}GB'")
                # Allow spill-to-disk -- eliminates OOM for large datasets.
                _duck.execute(f"SET temp_directory='{local_dir}'")
                # Multi-threaded parquet reads.
                _duck.execute(f"SET threads={max_workers}")
                logger.info(
                    "DuckDB: memory_limit=%dGB, threads=%d, spill_dir=%s",
                    _limit_gb, max_workers, local_dir,
                )
                df = _duck.execute(query_sql).df()
            finally:
                _duck.close()
        except Exception as e:
            logger.error(
                "DuckDB failed to read/combine parquet shards (enforce_schema=%s): %s. "
                "If this mentions a duplicate/ambiguous column, or a NUMERIC/"
                "BIGNUMERIC precision error, try re-running with "
                "enforce_schema=False or safe_cast=True/False to narrow it down.",
                enforce, e,
            )
            raise

        logger.info("Loaded DataFrame with shape %s", df.shape)

        # ---- Optional: split into customer-ID chunks ----
        if chunk_by_customer_id:
            _all_cids = sorted(df["customerId"].dropna().unique().tolist())
            _n_cids   = len(_all_cids)
            # build groups of exactly chunk_by_customer_id customers each
            _id_groups = [
                _all_cids[_i : _i + chunk_by_customer_id]
                for _i in range(0, _n_cids, chunk_by_customer_id)
            ]
            _chunks = [
                df[df["customerId"].isin(set(_grp))].reset_index(drop=True)
                for _grp in _id_groups
            ]
            logger.info(
                "Chunked %d unique customerIds into %d DataFrames "
                "(%d customers per chunk, last chunk: %d)",
                _n_cids, len(_chunks),
                chunk_by_customer_id, len(_id_groups[-1]),
            )
            return _chunks

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