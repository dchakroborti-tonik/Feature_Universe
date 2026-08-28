"""
Base aggregate features for B-Score Events.
Version: v20260424

Updated: Added app_rating (satisfaction signal), user exited flow count.
"""
import numpy as np
from scipy.stats import entropy as shannon_entropy
from .config import SESSION_GAP_SEC, MOE_SYSTEM_EVENTS, APP_OPEN_EVENTS


def compute_base_features(window_dfs):
    features = {}
    for w, d in window_dfs.items():
        if len(d) == 0:
            for k in ['total_events_cnt', 'behavioural_events_cnt', 'unique_event_types_cnt',
                      'login_cnt', 'app_open_cnt', 'active_days_cnt', 'event_entropy',
                      'session_cnt', 'event_gap_avg_sec', 'behavioural_event_ratio',
                      'events_per_active_day', 'app_rating_flag', 'user_exited_flow_cnt']:
                features[f'{k}_{w}'] = 0
            continue

        n = len(d)
        col = 'event_time_manila' if 'event_time_manila' in d.columns else 'event_time'
        behav = d[~d['event_name'].isin(MOE_SYSTEM_EVENTS)]
        n_behav = len(behav)

        features[f'total_events_cnt_{w}'] = n
        features[f'behavioural_events_cnt_{w}'] = n_behav
        features[f'unique_event_types_cnt_{w}'] = d['event_name'].nunique()
        features[f'login_cnt_{w}'] = int((d['event_name'] == 'app_login').sum())
        features[f'app_open_cnt_{w}'] = int(d['event_name'].isin(APP_OPEN_EVENTS).sum())
        features[f'active_days_cnt_{w}'] = d['event_date'].nunique() if 'event_date' in d.columns else 0
        features[f'event_entropy_{w}'] = (
            float(shannon_entropy(behav['event_name'].value_counts())) if n_behav > 0 else 0.0)

        gaps = d[col].diff().dt.total_seconds()
        features[f'session_cnt_{w}'] = int((gaps > SESSION_GAP_SEC).sum()) + 1
        features[f'event_gap_avg_sec_{w}'] = float(gaps.dropna().mean()) if len(gaps.dropna()) > 0 else np.nan
        features[f'behavioural_event_ratio_{w}'] = round(n_behav / max(n, 1), 4)
        active_days = features[f'active_days_cnt_{w}']
        features[f'events_per_active_day_{w}'] = (
            round(n_behav / active_days, 2) if active_days > 0 else np.nan)

        # App rating (satisfaction/NPS proxy)
        features[f'app_rating_flag_{w}'] = int(
            d['event_name'].isin(['app_rating']).any())

        # User exited flow (drop-off signal)
        features[f'user_exited_flow_cnt_{w}'] = int(
            (d['event_name'] == 'user exited flow').sum())

    return features
