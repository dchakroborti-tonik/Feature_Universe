"""
Main orchestrator for B-Score Events feature engineering.
Version: v20260818

Changes from v20260428:
  - create_all_features: removed tz_localize block on event_time_manila.
    event_time_manila is already tz-naive (UTC->Manila done in main.py).
    The old block checked `if df[col].dt.tz is None: tz_localize(...)` which
    would actually EXECUTE (since col IS tz-naive) and crash with TypeError
    or produce a tz-aware series mismatched against the tz-naive anchor.
  - Feature grain is (customer_id, observation_datetime).
  - run_feature_engineering (legacy helper) filters by customer_id
    and observation_datetime when those columns are present.

Feature modules (in order):
  1.  Base aggregate
  2.  Loan application (QL full funnel + SIL + disbursement)
  3.  FlexUp complete journey
  4.  SILRel (store relending)
  5.  RL (Relending product)
  6.  FL / UIL
  7.  Payment behaviour
  8.  Communication engagement
  9.  Financial activity
  10. Help & support
  11. Session patterns
"""
import pandas as pd
import numpy as np
import warnings

from .helpers import (
    clean_event_names, deduplicate_events, get_anchor_time,
    get_window_dfs, add_time_columns,
)
from .features_base import compute_base_features
from .features_loan_app import compute_loan_app_features
from .features_flexup import compute_flexup_features
from .features_silrel import compute_silrel_features
from .features_rl import compute_rl_features
from .features_fl import compute_fl_features
from .features_payment import compute_payment_features
from .features_comms import compute_comms_features
from .features_financial import compute_financial_features
from .features_support import compute_support_features
from .features_session import compute_session_features


def create_all_features(df):
    """
    Compute all features for a single customer-observation event window.

    Expects df with columns:
        customer_id, event_time_manila (tz-naive), event_name,
        observation_datetime (tz-naive, Manila local = date + 23:59:00)

    event_time_manila is already:
      - Converted from UTC to Asia/Manila  (done in main.py)
      - tz-naive / stripped of tzinfo       (done in main.py)
      - Sorted low -> high                  (done in main.py)
      - 7-day window filtered               (done in main.py)

    Inside this function we still sort + failsafe-dedup so the module
    remains safe when called standalone / in tests.
    """
    df = df.copy()
    if len(df) == 0:
        return {}

    # Failsafe: normalise event names (lowercase, strip)
    df = clean_event_names(df)

    # Failsafe dedup (harmless no-op when table has no dupes)
    df = deduplicate_events(df)

    # Anchor = observation_datetime (tz-naive Manila datetime, set in main.py)
    anchor = get_anchor_time(df)
    if pd.isna(anchor):
        return {}

    # Resolve time column — always event_time_manila from new pipeline
    col = 'event_time_manila' if 'event_time_manila' in df.columns else 'event_time'
    df[col] = pd.to_datetime(df[col], errors='coerce')

    # FIX v20260428: removed tz_localize block.
    # event_time_manila is already tz-naive after main.py conversion.
    # The old code checked `if df[col].dt.tz is None: tz_localize(...)` which
    # would execute (col IS tz-naive), localise the series to tz-aware,
    # then crash on `anchor_time - df[col]` in get_window_dfs because
    # anchor (from get_anchor_time) is tz-naive while col became tz-aware.

    # Sort (failsafe — main.py already sorts, but be safe for standalone use)
    df = df.sort_values(col).reset_index(drop=True)
    df = add_time_columns(df)

    # Build 7d window dict and add time columns to each window slice
    window_dfs = get_window_dfs(df, anchor)
    for wk in window_dfs:
        window_dfs[wk] = add_time_columns(window_dfs[wk])

    # Compute features from all modules
    features = {}
    features.update(compute_base_features(window_dfs))
    features.update(compute_loan_app_features(window_dfs))
    try:
        features.update(compute_flexup_features(window_dfs))
    except Exception:
        pass
    try:
        features.update(compute_silrel_features(window_dfs))
    except Exception:
        pass
    try:
        features.update(compute_rl_features(window_dfs))
    except Exception:
        pass
    try:
        features.update(compute_fl_features(window_dfs))
    except Exception:
        pass
    features.update(compute_payment_features(window_dfs))
    try:
        features.update(compute_comms_features(window_dfs))
    except Exception:
        pass
    features.update(compute_financial_features(window_dfs))
    features.update(compute_support_features(window_dfs))
    features.update(compute_session_features(window_dfs))

    return features


def run_feature_engineering(df_events, df_observations):
    """
    Legacy batch helper (not used by main.py — kept for standalone/notebook use).

    v20260818: when observation_datetime is present, filter events at the
    same customer-observation grain as the production runner.
    """
    warnings.filterwarnings('ignore')
    result_list, no_data = [], []
    for i, (_, obs_row) in enumerate(df_observations.iterrows()):
        if i % 100 == 0:
            print(f"Processing {i}/{len(df_observations)}")
        cid = obs_row['customer_id']
        obs_dt = pd.to_datetime(obs_row['observation_datetime'])
        col = 'event_time_manila'
        cust_evts = df_events[df_events['customer_id'] == cid].copy()
        if 'observation_datetime' in cust_evts.columns:
            cust_obs = pd.to_datetime(cust_evts['observation_datetime'], errors='coerce')
            cust_evts = cust_evts[cust_obs == obs_dt].copy()
        window_start = obs_dt - pd.Timedelta(hours=168)
        win = cust_evts[
            (cust_evts[col] >= window_start) & (cust_evts[col] <= obs_dt)
        ].copy()
        win['observation_datetime'] = obs_dt
        win = win.sort_values(col).reset_index(drop=True)
        if len(win) == 0:
            no_data.append((cid, obs_dt))
            continue
        try:
            feats = create_all_features(win)
        except Exception as e:
            print(f"Error cust={cid} obs={obs_dt}: {e}")
            feats = {}
        feats.update(obs_row.to_dict())
        result_list.append(feats)
    df_out = pd.DataFrame(result_list)
    print(f"Output: {df_out.shape}, no_data: {len(no_data)}")
    return df_out
