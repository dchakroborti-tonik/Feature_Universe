"""
Compare two BigQuery tables column-by-column on an inner join of
the key columns defined in KEYS (one or more) and export the differences to Excel.

Output workbook:
  - Summary : row counts + per-column mismatch statistics
  - Details : one row per (customer, obs date, column) where values differ

Requirements:  pip install google-cloud-bigquery pandas numpy openpyxl db-dtypes pyarrow
"""

from datetime import date, datetime
from decimal import Decimal

import gc

import numpy as np
import pandas as pd
from google.cloud import bigquery
from pandas.api.types import (
    is_bool_dtype,
    is_datetime64_any_dtype,
    is_float_dtype,
    is_numeric_dtype,
)

# --------------------------------------------------------------------------
# CONFIG
# --------------------------------------------------------------------------
PROJECT_ID = "prj-prod-dataplatform"
TABLE_1 = "prj-prod-dataplatform.dataset_a.table_one"   # <-- change
TABLE_2 = "prj-prod-dataplatform.dataset_b.table_two"   # <-- change
KEYS = ["id_customerid", "dt_obs_date"]   # one or more columns, e.g. ["digitalloanAccountId"]
DECIMALS = 2
# Timestamps are floored to this precision before comparing, so 10:00:00.123 and
# 10:00:00.456 are treated as the same. Use "s", "ms", "us", or None to keep full precision.
DATETIME_PRECISION = "s"
DAYFIRST = False   # only used when a text column must be parsed as dates: True -> "01/04/2026" = 1 Apr
DATE_FORMAT = "%Y-%m-%d"
DATETIME_FORMAT = "%Y-%m-%d %H:%M:%S"
OUTPUT_FILE = "table_comparison.xlsx"
BATCH_SIZE = 10        # non-key columns loaded & compared per pass (lower it if you still run out of memory)
EXCEL_MAX_ROWS = 1_000_000  # Excel limit is 1,048,576; leave headroom


# --------------------------------------------------------------------------
# HELPERS
# --------------------------------------------------------------------------
def load_table(client: bigquery.Client, table: str, columns=None) -> pd.DataFrame:
    cols = ", ".join(f"`{c}`" for c in columns) if columns else "*"
    return client.query(f"SELECT {cols} FROM `{table}`").to_dataframe()


def table_columns(client: bigquery.Client, table: str) -> list:
    """Column names from the table schema (no data is read)."""
    return [f.name for f in client.get_table(table).schema]


def validate_keys(columns: list, name: str) -> None:
    """Fail early if a key column is missing from a table."""
    missing = [k for k in KEYS if k not in columns]
    if missing:
        raise KeyError(
            f"Key column(s) {missing} not found in {name}. "
            f"Available columns: {columns}"
        )


def _is_date_like(s: pd.Series) -> bool:
    if is_datetime64_any_dtype(s) or str(s.dtype).startswith("dbdate"):
        return True
    if s.dtype == object:
        first = s.dropna()
        return len(first) > 0 and isinstance(first.iloc[0], (date, datetime))
    return False


def normalize_datetime(s: pd.Series) -> pd.Series:
    """Convert DATE / DATETIME / TIMESTAMP values to one common representation:
    timezone-naive datetime64 (tz-aware values are converted to UTC first),
    floored to DATETIME_PRECISION."""
    s = pd.to_datetime(s)
    if getattr(s.dt, "tz", None) is not None:
        s = s.dt.tz_convert("UTC").dt.tz_localize(None)
    if DATETIME_PRECISION:
        s = s.dt.floor(DATETIME_PRECISION)
    return s


def is_date_only(*series: pd.Series) -> bool:
    """True if every non-null value in all the given datetime series is at midnight."""
    for s in series:
        nn = s.dropna()
        if len(nn) and not (nn == nn.dt.normalize()).all():
            return False
    return True


def format_datetimes(s: pd.Series, date_only: bool) -> pd.Series:
    """Datetime series -> consistently formatted strings (NaT -> None)."""
    fmt = DATE_FORMAT if date_only else DATETIME_FORMAT
    return s.dt.strftime(fmt).astype(object).where(s.notna(), None)


def harmonize_datetime_columns(df1: pd.DataFrame, df2: pd.DataFrame, cols) -> None:
    """If a column is date-like in one table but text in the other (e.g. DATE vs
    STRING '2026-01-31' or '31/01/2026'), parse the text side so both compare as dates."""
    for col in cols:
        for a, b in ((df1, df2), (df2, df1)):
            if is_datetime64_any_dtype(a[col]) and not is_datetime64_any_dtype(b[col]):
                try:
                    parsed = pd.to_datetime(b[col], errors="coerce", format="mixed",
                                            dayfirst=DAYFIRST)
                    if parsed.notna().sum() == b[col].notna().sum():
                        b[col] = normalize_datetime(parsed)
                    else:
                        print(f"WARNING: column '{col}' is a date in one table but some "
                              "values in the other could not be parsed as dates; "
                              "comparing as text.")
                except Exception:
                    print(f"WARNING: could not parse '{col}' as a date in the other table.")


def normalize_key(s: pd.Series) -> pd.Series:
    """Make a key column comparable across both tables, whatever its type."""
    if _is_date_like(s):
        return normalize_datetime(s)
    if is_numeric_dtype(s) and not is_bool_dtype(s):
        # Avoid 123 vs 123.0 mismatches when integers were upcast to float
        nn = s.dropna()
        if len(nn) and (nn % 1 == 0).all():
            s = s.astype("Int64")
    return s.astype("string").str.strip()


def normalize(df: pd.DataFrame) -> pd.DataFrame:
    """Standardise key types, put date/datetime columns in one format, and round
    decimal columns to DECIMALS places."""
    df = df.copy()

    # Keys: make types comparable across both tables
    for k in KEYS:
        df[k] = normalize_key(df[k])

    for col in df.columns:
        if col in KEYS:
            continue
        s = df[col]
        if _is_date_like(s):
            df[col] = normalize_datetime(s)
        elif is_float_dtype(s):
            df[col] = s.round(DECIMALS)
        elif s.dtype == object:
            first = s.dropna()
            # BigQuery NUMERIC / BIGNUMERIC arrive as Decimal objects
            if len(first) and isinstance(first.iloc[0], Decimal):
                df[col] = pd.to_numeric(s.astype(float)).round(DECIMALS)
    return df


def is_numeric(s1: pd.Series, s2: pd.Series) -> bool:
    return (
        is_numeric_dtype(s1) and is_numeric_dtype(s2)
        and not is_bool_dtype(s1) and not is_bool_dtype(s2)
    )


def compare_column(a: pd.Series, b: pd.Series):
    """Return (mismatch_mask, difference_series_or_None)."""
    both_null = a.isna() & b.isna()

    if is_numeric(a, b):
        diff = (a.astype(float) - b.astype(float)).round(DECIMALS)
        mismatch = ~both_null & (a.isna() | b.isna() | (diff != 0))
        return mismatch, diff

    if is_datetime64_any_dtype(a) and is_datetime64_any_dtype(b):
        eq = (a == b).fillna(False).astype(bool)
        return ~(eq | both_null), None

    eq = (a.astype("string") == b.astype("string")).fillna(False).astype(bool)
    mismatch = ~(eq | both_null)
    return mismatch, None


# --------------------------------------------------------------------------
# MAIN
# --------------------------------------------------------------------------
def main():
    client = bigquery.Client(project=PROJECT_ID)

    # ---- schemas (no data read yet) ----
    names1, names2 = table_columns(client, TABLE_1), table_columns(client, TABLE_2)
    validate_keys(names1, TABLE_1)
    validate_keys(names2, TABLE_2)
    cols1, cols2 = set(names1) - set(KEYS), set(names2) - set(KEYS)
    common_cols = sorted(cols1 & cols2)
    only_in_1 = sorted(cols1 - cols2)
    only_in_2 = sorted(cols2 - cols1)

    # ---- pass 1: keys only (cheap) -> row counts, null/duplicate keys, matched rows ----
    print("Loading keys...")
    k1 = normalize(load_table(client, TABLE_1, KEYS))
    k2 = normalize(load_table(client, TABLE_2, KEYS))

    for name, df in (("table 1", k1), ("table 2", k2)):
        n_null = int(df[KEYS].isna().any(axis=1).sum())
        if n_null:
            print(f"WARNING: {n_null} row(s) in {name} have a null key and will not match.")

    dup1, dup2 = int(k1.duplicated(KEYS).sum()), int(k2.duplicated(KEYS).sum())
    if dup1 or dup2:
        print(f"WARNING: duplicate keys found (table1={dup1}, table2={dup2}). "
              "Inner join will produce multiple rows for those keys.")

    n_rows1, n_rows2 = len(k1), len(k2)
    n_matched = len(k1.merge(k2, on=KEYS, how="inner"))
    only1 = len(k1.merge(k2.drop_duplicates(KEYS), on=KEYS, how="left", indicator=True)
                  .query("_merge == 'left_only'"))
    only2 = len(k2.merge(k1.drop_duplicates(KEYS), on=KEYS, how="left", indicator=True)
                  .query("_merge == 'left_only'"))
    del k1, k2
    gc.collect()

    # ---- pass 2: compare the other columns in batches to keep memory low ----
    detail_frames, summary_rows = [], []
    n_batches = -(-len(common_cols) // BATCH_SIZE)
    for bi, i in enumerate(range(0, len(common_cols), BATCH_SIZE), 1):
        batch = common_cols[i:i + BATCH_SIZE]
        print(f"Batch {bi}/{n_batches}: {len(batch)} column(s)...")
        d1 = normalize(load_table(client, TABLE_1, KEYS + batch))
        d2 = normalize(load_table(client, TABLE_2, KEYS + batch))
        harmonize_datetime_columns(d1, d2, batch)
        merged = d1.merge(d2, on=KEYS, how="inner", suffixes=("_t1", "_t2"))
        del d1, d2

        for col in batch:
            a, b = merged[f"{col}_t1"], merged[f"{col}_t2"]
            mismatch, diff = compare_column(a, b)
            n_mis = int(mismatch.sum())

            is_dt = is_datetime64_any_dtype(a) and is_datetime64_any_dtype(b)
            date_only = is_dt and is_date_only(a, b)
            dtype_label = (
                "numeric" if diff is not None
                else ("date" if date_only else "datetime") if is_dt
                else "non-numeric"
            )

            row = {
                "column": col,
                "data_type": dtype_label,
                "rows_compared": n_matched,
                "mismatches": n_mis,
                "pct_mismatch": round(100 * n_mis / n_matched, 2) if n_matched else 0.0,
                "null_vs_value_mismatches": int((mismatch & (a.isna() ^ b.isna())).sum()),
                "max_abs_diff": np.nan,
                "mean_abs_diff": np.nan,
                "sum_diff": np.nan,
            }
            if diff is not None and n_mis:
                d = diff[mismatch].dropna()
                if len(d):
                    row["max_abs_diff"] = round(d.abs().max(), DECIMALS)
                    row["mean_abs_diff"] = round(d.abs().mean(), DECIMALS)
                    row["sum_diff"] = round(d.sum(), DECIMALS)
            summary_rows.append(row)

            if n_mis:
                det = merged.loc[mismatch, KEYS].copy()
                det["column"] = col
                va, vb = a[mismatch], b[mismatch]
                if is_dt:  # show dates / datetimes in one consistent text format
                    va, vb = format_datetimes(va, date_only), format_datetimes(vb, date_only)
                det["table1_value"] = va.values
                det["table2_value"] = vb.values
                det["difference"] = diff[mismatch].values if diff is not None else np.nan
                detail_frames.append(det)

        del merged
        gc.collect()

    summary = pd.DataFrame(summary_rows).sort_values(
        "mismatches", ascending=False
    ).reset_index(drop=True)

    details = (
        pd.concat(detail_frames, ignore_index=True)
        if detail_frames
        else pd.DataFrame(columns=KEYS + ["column", "table1_value", "table2_value", "difference"])
    )
    # Keep value columns as object so numeric and text mismatches can coexist
    details["table1_value"] = details["table1_value"].astype(object)
    details["table2_value"] = details["table2_value"].astype(object)
    # Show date-type keys as plain dates in Excel
    for k in KEYS:
        if is_datetime64_any_dtype(details[k]):
            details[k] = details[k].dt.date
    details = details.sort_values(KEYS + ["column"]).reset_index(drop=True)

    overview = pd.DataFrame(
        {
            "metric": [
                "Table 1", "Table 2",
                "Rows in table 1", "Rows in table 2",
                "Rows matched (inner join on keys)",
                "Rows only in table 1 (not compared)",
                "Rows only in table 2 (not compared)",
                "Columns compared",
                "Columns only in table 1", "Columns only in table 2",
                "Columns with >=1 mismatch",
                "Total cell mismatches",
            ],
            "value": [
                TABLE_1, TABLE_2,
                n_rows1, n_rows2,
                n_matched,
                only1,
                only2,
                len(common_cols),
                ", ".join(only_in_1) or "-", ", ".join(only_in_2) or "-",
                int((summary["mismatches"] > 0).sum()),
                int(summary["mismatches"].sum()),
            ],
        }
    )

    # ---- write Excel ----
    print(f"Writing {OUTPUT_FILE} ...")
    with pd.ExcelWriter(OUTPUT_FILE, engine="openpyxl") as writer:
        overview.to_excel(writer, sheet_name="Summary", index=False, startrow=0)
        summary.to_excel(
            writer, sheet_name="Summary", index=False, startrow=len(overview) + 3
        )

        # Details (split across sheets if it exceeds Excel's row limit)
        if len(details) <= EXCEL_MAX_ROWS:
            details.to_excel(writer, sheet_name="Details", index=False)
        else:
            for i, start in enumerate(range(0, len(details), EXCEL_MAX_ROWS), 1):
                details.iloc[start:start + EXCEL_MAX_ROWS].to_excel(
                    writer, sheet_name=f"Details_{i}", index=False
                )

        # Formatting
        num_fmt = "0." + "0" * DECIMALS
        for ws in writer.book.worksheets:
            ws.freeze_panes = "A2" if ws.title != "Summary" else None
            for col_cells in ws.columns:
                width = max(len(str(c.value)) if c.value is not None else 0
                            for c in col_cells[:200])
                ws.column_dimensions[col_cells[0].column_letter].width = min(width + 2, 60)
            for row in ws.iter_rows():
                for c in row:
                    if isinstance(c.value, float):
                        c.number_format = num_fmt

    print(f"Done. {n_matched:,} matched rows, "
          f"{int(summary['mismatches'].sum()):,} cell mismatches across "
          f"{int((summary['mismatches'] > 0).sum())} columns.")


if __name__ == "__main__":
    main()
