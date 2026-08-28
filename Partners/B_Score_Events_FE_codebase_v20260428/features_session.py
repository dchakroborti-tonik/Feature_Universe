"""
Session pattern and time-of-day features for B-Score Events.
Version: v20260423

Session features capture the rhythm and intensity of app usage:
- Frequent short sessions → distracted/checking
- Long sessions → deep engagement
- Night activity → possibly stress-related browsing
- Weekend/weekday patterns → behavioural consistency

These complement the event-level features by capturing HOW the customer
is using the app, not just WHAT they're doing.
"""
import numpy as np
import pandas as pd
from .config import SESSION_GAP_SEC


def compute_session_features(window_dfs):
    """Compute session and time-of-day pattern features."""
    features = {}

    for w, d in window_dfs.items():
        if len(d) == 0:
            for k in ['session_cnt', 'avg_session_duration_mins', 'med_session_duration_mins',
                      'max_session_duration_mins', 'avg_events_per_session',
                      'night_session_flag', 'weekend_ratio', 'tod_med_hr',
                      'tod_variance', 'days_with_activity_cnt', 'max_daily_sessions']:
                features[f'{k}_{w}'] = np.nan
            continue

        col = 'event_time_manila' if 'event_time_manila' in d.columns else 'event_time'

        # ---- Session identification ----
        d2 = d.copy().sort_values(col).reset_index(drop=True)
        gaps = d2[col].diff().dt.total_seconds()
        d2['new_session'] = (gaps > SESSION_GAP_SEC).astype(int)
        d2.loc[0, 'new_session'] = 1
        d2['session_id'] = d2['new_session'].cumsum()

        n_sessions = int(d2['session_id'].nunique())
        features[f'session_cnt_{w}'] = n_sessions

        # ---- Session durations ----
        sess_durations = []
        for _, grp in d2.groupby('session_id'):
            if len(grp) > 1:
                dur = (grp[col].max() - grp[col].min()).total_seconds() / 60
                if dur < 60:  # cap at 60 min to avoid between-session noise
                    sess_durations.append(dur)

        if sess_durations:
            features[f'avg_session_duration_mins_{w}'] = round(float(np.mean(sess_durations)), 2)
            features[f'med_session_duration_mins_{w}'] = round(float(np.median(sess_durations)), 2)
            features[f'max_session_duration_mins_{w}'] = round(float(np.max(sess_durations)), 2)
        else:
            for k in ['avg_session_duration_mins', 'med_session_duration_mins', 'max_session_duration_mins']:
                features[f'{k}_{w}'] = np.nan

        # ---- Events per session ----
        events_per_session = d2.groupby('session_id').size()
        features[f'avg_events_per_session_{w}'] = round(float(events_per_session.mean()), 2)
        features[f'max_events_per_session_{w}'] = int(events_per_session.max())

        # ---- Time of day patterns ----
        features[f'tod_med_hr_{w}'] = round(float(d2['hour'].median()), 1)
        features[f'tod_variance_{w}'] = round(float(d2['hour'].var()), 2) if len(d2) > 1 else np.nan

        # Night activity: any events between 22:00 and 06:00
        night = d2[(d2['hour'] >= 22) | (d2['hour'] < 6)]
        features[f'night_session_flag_{w}'] = int(len(night) > 0)
        features[f'night_events_cnt_{w}'] = len(night)

        # Early morning activity (05:00-07:00 typical commute/wake-up check)
        early = d2[(d2['hour'] >= 5) & (d2['hour'] < 8)]
        features[f'early_morning_flag_{w}'] = int(len(early) > 0)

        # ---- Day-of-week patterns ----
        weekend = d2[d2['dayofweek'].isin([5, 6])]
        weekday = d2[~d2['dayofweek'].isin([5, 6])]
        features[f'weekend_ratio_{w}'] = round(
            len(weekend) / max(len(weekday), 1), 4)
        features[f'weekend_flag_{w}'] = int(len(weekend) > 0)

        # ---- Activity distribution across days ----
        daily_counts = d2.groupby('event_date').size()
        features[f'days_with_activity_cnt_{w}'] = len(daily_counts)
        features[f'max_events_per_day_{w}'] = int(daily_counts.max())
        features[f'avg_events_per_day_{w}'] = round(float(daily_counts.mean()), 2)

        # Max sessions in any single day
        daily_sessions = d2.groupby('event_date')['session_id'].nunique()
        features[f'max_daily_sessions_{w}'] = int(daily_sessions.max())
        features[f'avg_daily_sessions_{w}'] = round(float(daily_sessions.mean()), 2)

        # ---- Event gap patterns ----
        event_gaps = d2[col].diff().dt.total_seconds().dropna()
        features[f'event_gap_med_sec_{w}'] = round(float(event_gaps.median()), 2) if len(event_gaps) > 0 else np.nan
        features[f'event_gap_max_hrs_{w}'] = round(float(event_gaps.max() / 3600), 2) if len(event_gaps) > 0 else np.nan

        # Longest gap > 24h (multi-day absence signal)
        features[f'gap_over_24h_flag_{w}'] = int((event_gaps > 86400).any())

    return features
