"""
Production batch runner for B-Score Events Feature Engineering.
Version: v20260818

Machine target : e2-standard-4  (4 vCPUs, 16 GB RAM)
Source table   : risk_mart.moenagage_events_all_disb_20240901_20260422
                 ~18 M rows / 1.85 GB - fits comfortably in RAM after load.

Source table columns:
    customer_id          STRING    - customer identifier
    moengage_user_id     STRING    - MoEngage user identifier
    event_time           TIMESTAMP - UTC, converted to Manila tz-naive here
    event_name           STRING
    Observation_date     DATE      - Manila calendar date, no time component

Pipeline
--------
1. Pull entire source table in one BQ read.
2. Convert event_time (UTC) -> event_time_manila (Asia/Manila, tz-naive).
3. Convert Observation_date -> observation_datetime = date + 23:59:00.
4. Build one metadata row per (customer_id, observation_datetime).
5. Pre-group events by (customer_id, observation_datetime).
6. Per customer-observation pair:
     a. Fetch that pair's events from grouped index.
     b. Filter to 7-day window: [obs_dt - 168h, obs_dt].
     c. Sort events by event_time_manila ascending.
     d. Attach observation_datetime column.
     e. Call create_all_features(window_df).
7. Write output in BATCH_SIZE chunks with checkpoint on
   customer_id|observation_datetime.

Output columns (always first three, then all feature columns):
    customer_id | moengage_user_id | observation_datetime
    ... + all feature columns from create_all_features()

Usage:
    python main.py
"""

import os
import sys
import warnings

import pandas as pd
from tqdm import tqdm

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
print(f"Base Directory: {BASE_DIR}")
sys.path.insert(0, BASE_DIR)

from B_Score_Events_FE_codebase_v20260818 import create_all_features

# import sys
# import os

# # Gets the directory of the current file (B_Score_Events_FE_codebase_v20260818)
# CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))

# # Gets the parent directory (Partners)
# PARENT_DIR = os.path.dirname(CURRENT_DIR)

# # Insert the parent directory so Python can find the module by its folder name
# sys.path.insert(0, PARENT_DIR)

# print(f"Parent Directory added to path: {PARENT_DIR}")

# from B_Score_Events_FE_codebase_v20260818 import create_all_features


warnings.filterwarnings('ignore')

# CONFIG
PROJECT_ID = "prj-prod-dataplatform"
SOURCE_TABLE = "risk_mart.bscore_moenagage_events_all_20230101_20260816"

OUTPUT_FILE = os.path.join(BASE_DIR, "b_score_events_output_v20260818.csv")
CHECKPOINT_FILE = os.path.join(BASE_DIR, "b_score_events_checkpoint_v20260818.txt")
BATCH_SIZE = 500

USE_TEST_CUSTOMERS = False
TEST_CUSTOMER_IDS = []


def load_events_table() -> pd.DataFrame:
    """
    Single BQ read of the full source table.

    Returns raw DataFrame with columns:
        customer_id, moengage_user_id, event_time, event_name,
        Observation_date
    """
    from google.cloud import bigquery

    client = bigquery.Client(project=PROJECT_ID)
    query = f"""
        SELECT
            CAST(customer_id AS STRING) AS customer_id,
            moengage_user_id,
            event_time,
            event_name,
            Observation_date
        FROM `{SOURCE_TABLE}`
    """
    print("Querying BigQuery ...")
    df = client.query(query).to_dataframe(progress_bar_type='tqdm')
    print(f"  Loaded {len(df):,} rows")
    return df


def preprocess(df: pd.DataFrame) -> pd.DataFrame:
    """
    Create tz-naive Manila event timestamps and observation anchors.
    """
    df['event_time'] = pd.to_datetime(df['event_time'], utc=True, errors='coerce')
    df['event_time_manila'] = (
        df['event_time']
        .dt.tz_convert('Asia/Manila')
        .dt.tz_localize(None)
    )
    df.drop(columns=['event_time'], inplace=True)

    df['Observation_date'] = pd.to_datetime(df['Observation_date'], errors='coerce')
    df['observation_datetime'] = (
        df['Observation_date'] + pd.Timedelta(hours=23, minutes=59, seconds=0)
    )
    df.drop(columns=['Observation_date'], inplace=True)

    df['customer_id'] = df['customer_id'].astype(str)
    return df


def make_pair_key(customer_id, obs_dt) -> str:
    """Stable checkpoint key for one (customer_id, observation_datetime)."""
    obs_key = pd.to_datetime(obs_dt).strftime('%Y-%m-%d %H:%M:%S')
    return f"{customer_id}|{obs_key}"


def build_customer_obs_meta(df: pd.DataFrame) -> pd.DataFrame:
    """
    One row per unique (customer_id, observation_datetime).

    moengage_user_id is taken from the first row within each
    customer-observation pair.
    """
    meta = (
        df.groupby(['customer_id', 'observation_datetime'], sort=False)
        .agg(
            moengage_user_id=('moengage_user_id', 'first'),
        )
        .reset_index()
    )
    return meta


if __name__ == '__main__':

    # Resume / checkpoint
    processed_pairs: set = set()
    if os.path.exists(CHECKPOINT_FILE):
        with open(CHECKPOINT_FILE) as f:
            processed_pairs = {line.strip() for line in f if line.strip()}
        print(f"Resuming: {len(processed_pairs):,} customer-observation pairs already processed.")

    header_written = os.path.exists(OUTPUT_FILE)
    output_columns = None
    if header_written:
        try:
            output_columns = pd.read_csv(OUTPUT_FILE, nrows=0).columns.tolist()
        except Exception:
            pass

    # Load & preprocess
    raw_df = load_events_table()

    if USE_TEST_CUSTOMERS:
        test_ids = [str(c) for c in TEST_CUSTOMER_IDS]
        raw_df = raw_df[raw_df['customer_id'].isin(test_ids)].copy()
        print(f"  Test mode: {len(raw_df):,} rows for {len(test_ids)} customers")

    events_df = preprocess(raw_df)
    del raw_df

    # Build pair-level metadata and grouped index.
    customer_obs_meta = build_customer_obs_meta(events_df)
    total_pairs = len(customer_obs_meta)

    print(f"\nTotal customer-observation pairs to process : {total_pairs:,}")
    print(f"Unique customers                           : {events_df['customer_id'].nunique():,}")
    print(f"Already in checkpoint                      : {len(processed_pairs):,}")
    print(f"Remaining this run                         : {total_pairs - len(processed_pairs):,}\n")

    # Pre-group once by pair for O(1) per customer-observation event lookup.
    grouped = events_df.groupby(['customer_id', 'observation_datetime'], sort=False)

    batch_results: list = []
    batch_keys: list = []

    with tqdm(
        total=total_pairs,
        desc="Processing customer-observation pairs",
        unit="pair",
        dynamic_ncols=True,
    ) as pbar:

        for customer_obs_row in customer_obs_meta.itertuples(index=False):
            cust_id = customer_obs_row.customer_id
            obs_dt = customer_obs_row.observation_datetime
            moe_uid = customer_obs_row.moengage_user_id
            pair_key = make_pair_key(cust_id, obs_dt)

            pbar.update(1)

            # Skip already-processed customer-observation pairs.
            if pair_key in processed_pairs:
                continue

            # Fetch this customer-observation pair's events.
            try:
                pair_events = grouped.get_group((cust_id, obs_dt))
            except KeyError:
                pair_events = pd.DataFrame(columns=events_df.columns)

            # Failsafe 7-day window filter: [obs_dt - 168h, obs_dt].
            window_start = obs_dt - pd.Timedelta(hours=168)
            window_df = pair_events[
                (pair_events['event_time_manila'] >= window_start) &
                (pair_events['event_time_manila'] <= obs_dt)
            ].copy()

            window_df.sort_values('event_time_manila', inplace=True)

            # Attach the pair anchor so the engine reads the correct anchor.
            window_df['observation_datetime'] = obs_dt

            try:
                feats = create_all_features(window_df) if len(window_df) > 0 else {}
            except Exception as e:
                print(f"\n  ERROR  cust={cust_id}  obs={obs_dt}: {e}")
                feats = {}

            row = {
                'customer_id': cust_id,
                'moengage_user_id': moe_uid,
                'observation_datetime': obs_dt,
            }
            row.update(feats)
            batch_results.append(row)
            batch_keys.append(pair_key)

            if len(batch_results) >= BATCH_SIZE:
                bdf = pd.DataFrame(batch_results)
                if output_columns is None:
                    output_columns = bdf.columns.tolist()
                else:
                    bdf = bdf.reindex(columns=output_columns)

                bdf.to_csv(OUTPUT_FILE, mode='a', header=not header_written, index=False)
                header_written = True

                with open(CHECKPOINT_FILE, 'a') as ckpt:
                    ckpt.writelines(k + '\n' for k in batch_keys)
                processed_pairs.update(batch_keys)
                batch_results, batch_keys = [], []

    # Final flush (tail batch < BATCH_SIZE).
    if batch_results:
        bdf = pd.DataFrame(batch_results)
        if output_columns is None:
            output_columns = bdf.columns.tolist()
        else:
            bdf = bdf.reindex(columns=output_columns)
        bdf.to_csv(OUTPUT_FILE, mode='a', header=not header_written, index=False)
        with open(CHECKPOINT_FILE, 'a') as ckpt:
            ckpt.writelines(k + '\n' for k in batch_keys)

    print(f"\nDone. Output saved to: {OUTPUT_FILE}")
