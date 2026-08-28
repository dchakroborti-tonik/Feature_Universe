"""
Shared helper functions for B-Score Events feature engineering.
Version: v20260428

Changes from v20260423:
  - get_anchor_time: removed tz_localize('Asia/Manila') on observation_datetime.
    observation_datetime is already tz-naive (set in main.py as Manila date + 23:59:00).
    The old localize call would crash on tz-naive datetimes from the new pipeline.
  - get_window_dfs: anchor_time is now always tz-naive; arithmetic with tz-naive
    event_time_manila is consistent — no tz mismatch crash.
  - All other logic unchanged.
"""
import pandas as pd
import numpy as np
import logging
from .config import (
    WINDOWS, DEDUP_COLUMNS, DROPOFF_GAP_SEC, REENTRY_EVENTS, MOE_SYSTEM_EVENTS,
)

logger = logging.getLogger(__name__)


def clean_event_names(df, col='event_name'):
    """Lowercase, strip, remove zero-width characters from event_name."""
    df = df.copy()
    df[col] = (
        df[col]
        .astype(str)
        .str.strip()
        .str.lower()
        .str.replace(r'[\u200b\u200c\u200d\ufeff]', '', regex=True)
    )
    return df


def deduplicate_events(df):
    """
    Failsafe dedup: remove duplicate event rows (same customer_id, time, event_name).
    DEDUP_COLUMNS = ['customer_id', 'event_time_manila', 'event_name'].
    Silently skips any column not present in df (e.g. if customer_id is absent).
    """
    before = len(df)
    cols = [c for c in DEDUP_COLUMNS if c in df.columns]
    if not cols:
        return df
    df = df.drop_duplicates(subset=cols, keep='first').reset_index(drop=True)
    removed = before - len(df)
    if removed > 0:
        logger.debug(f"Dedup removed {removed}/{before} rows")
    return df


def get_anchor_time(df):
    """
    Get the observation datetime anchor (tz-naive, Asia/Manila).

    Reads observation_datetime column which is set in main.py as:
        Manila date + 23:59:00  (tz-naive)
    Falls back to max event_time_manila if observation_datetime is absent/null.

    FIX v20260428: removed tz_localize('Asia/Manila') — observation_datetime
    is already tz-naive from main.py. The old localize call would raise
    TypeError on a tz-naive datetime.
    """
    if 'observation_datetime' in df.columns:
        anchor = pd.to_datetime(df['observation_datetime'].iloc[0], errors='coerce')
        if pd.notna(anchor):
            # anchor is tz-naive (Manila local time) — return as-is
            return anchor
    # Fallback: use the latest event time in the window
    col = 'event_time_manila' if 'event_time_manila' in df.columns else 'event_time'
    return df[col].max()


def ensure_tz(dt, tz='Asia/Manila'):
    """
    Utility: ensure a datetime is timezone-aware in Asia/Manila.
    Not used in the main pipeline (all datetimes are tz-naive), kept for
    standalone / testing use.
    """
    dt = pd.to_datetime(dt, errors='coerce')
    if pd.isna(dt):
        return dt
    if dt.tzinfo is None:
        return dt.tz_localize(tz)
    return dt.tz_convert(tz)


def get_window_dfs(df, anchor_time):
    """
    Build windowed DataFrames (7d = 168 hours before anchor_time).
    Returns dict: {'7d': df_7d}

    Both anchor_time and event_time_manila are tz-naive — arithmetic is safe.
    FIX v20260428: anchor_time is no longer tz-localised in get_anchor_time,
    so the subtraction here is consistently tz-naive - tz-naive.
    """
    col = 'event_time_manila' if 'event_time_manila' in df.columns else 'event_time'
    df = df.copy()
    df['_hours_before'] = (anchor_time - df[col]).dt.total_seconds() / 3600
    result = {}
    for w, hours in WINDOWS.items():
        wd = df[(df['_hours_before'] >= 0) & (df['_hours_before'] <= hours)].copy()
        wd = wd.sort_values(col).reset_index(drop=True)
        result[w] = wd
    return result


def add_time_columns(df):
    """Add hour, dayofweek, event_date, time_gap_sec, next/prev event columns."""
    col = 'event_time_manila' if 'event_time_manila' in df.columns else 'event_time'
    df = df.sort_values(col).reset_index(drop=True)
    df['hour'] = df[col].dt.hour
    df['dayofweek'] = df[col].dt.dayofweek
    df['event_date'] = df[col].dt.date
    df['next_event_time'] = df[col].shift(-1)
    df['next_event_name'] = df['event_name'].shift(-1)
    df['prev_event_name'] = df['event_name'].shift(1)
    df['time_gap_sec'] = (df['next_event_time'] - df[col]).dt.total_seconds()
    return df


def assign_session_ids(df, gap_threshold=DROPOFF_GAP_SEC):
    """Assign session IDs based on time gaps between events."""
    col = 'event_time_manila' if 'event_time_manila' in df.columns else 'event_time'
    df = df.sort_values(col).reset_index(drop=True)
    gaps = df[col].diff().dt.total_seconds()
    df['new_session'] = ((gaps > gap_threshold) | df['event_name'].isin(REENTRY_EVENTS)).astype(int)
    df.loc[0, 'new_session'] = 1
    df['session_id'] = df['new_session'].cumsum()
    return df


def remove_moe_system_events(df):
    """Remove MoEngage internal system events that don't reflect user behaviour."""
    mask = df['event_name'].isin(MOE_SYSTEM_EVENTS)
    return df[~mask].reset_index(drop=True)
