"""
FlexUp (FU) complete journey features for B-Score Events.
Version: v20260424

FU journey now covers: sales screens → launch → calculator → full application
→ offer journey → signatures → disbursement.
A fu_disburse_success within the 7-day window = new top-up loan added.
"""
import numpy as np
from .config import FU_SALES_EVENTS, FU_APPLICATION_EVENTS, FU_OFFER_EVENTS, ANY_DISBURSE_EVENTS

FU_FUNNEL_ORDERED = [
    'loans_fu_6andup', 'loans_fu_sales_screen_1', 'loans_fu_sales_screen_2',
    'loans_fu_sales_screen_3', 'loans_fu_launch', 'loans_fu_calculator',
    'loans_fu_offer_screen', 'loans_fu_application_summary',
    'loans_fu_application_terms', 'loans_fu_application_completed',
    'loans_fu_offer_summary', 'loans_fu_offer_signalldocs',
    'loans_fu_offer_signature', 'loans_fu_offer_success', 'loans_fu_disburse_success',
]
FU_IDX = {e: i for i, e in enumerate(FU_FUNNEL_ORDERED)}

ALL_FU_EVENTS = FU_SALES_EVENTS + FU_APPLICATION_EVENTS + FU_OFFER_EVENTS


def compute_flexup_features(window_dfs):
    features = {}
    for w, d in window_dfs.items():
        col = 'event_time_manila' if 'event_time_manila' in d.columns else 'event_time'

        # Sales screens
        features[f'fu_entry_cnt_{w}'] = int((d['event_name'] == 'loans_fu_6andup').sum())
        features[f'fu_entry_flag_{w}'] = int((d['event_name'] == 'loans_fu_6andup').any())
        for i in [1, 2, 3]:
            cnt = int((d['event_name'] == f'loans_fu_sales_screen_{i}').sum())
            features[f'fu_screen{i}_cnt_{w}'] = cnt
            features[f'fu_screen{i}_flag_{w}'] = int(cnt > 0)
        features[f'fu_sales_accepted_flag_{w}'] = int(
            d['event_name'].isin(['loans_fu_sales_screen_accepted',
                                   'loans_fu_accepted_sales_screen_1']).any())
        features[f'fu_launch_flag_{w}'] = int((d['event_name'] == 'loans_fu_launch').any())
        features[f'fu_calculator_flag_{w}'] = int((d['event_name'] == 'loans_fu_calculator').any())
        features[f'fu_offer_screen_flag_{w}'] = int((d['event_name'] == 'loans_fu_offer_screen').any())

        # Application
        features[f'fu_application_started_flag_{w}'] = int(
            d['event_name'].isin(FU_APPLICATION_EVENTS).any())
        features[f'fu_application_completed_flag_{w}'] = int(
            (d['event_name'] == 'loans_fu_application_completed').any())

        # Offer journey
        features[f'fu_offer_cnt_{w}'] = int((d['event_name'] == 'loans_fu_offer_summary').sum())
        features[f'fu_offer_created_cnt_{w}'] = int((d['event_name'] == 'offer_created').sum())
        features[f'fu_offer_created_flag_{w}'] = int((d['event_name'] == 'offer_created').any())
        features[f'fu_offer_used_flag_{w}'] = int((d['event_name'] == 'offer_used').any())
        features[f'fu_offer_deleted_flag_{w}'] = int((d['event_name'] == 'offer_delete').any())
        features[f'fu_offer_total_events_cnt_{w}'] = int(d['event_name'].isin(FU_OFFER_EVENTS).sum())

        # Disbursement (CRITICAL)
        fu_disb = int((d['event_name'] == 'loans_fu_disburse_success').sum())
        features[f'fu_disburse_success_cnt_{w}'] = fu_disb
        features[f'fu_disburse_success_flag_{w}'] = int(fu_disb > 0)

        # Funnel depth
        reached = [e for e in FU_FUNNEL_ORDERED if (d['event_name'] == e).any()]
        max_idx = max((FU_IDX[e] for e in reached), default=-1)
        features[f'fu_funnel_depth_{w}'] = max_idx + 1
        features[f'fu_funnel_started_flag_{w}'] = int(max_idx >= 0)
        features[f'fu_reached_application_flag_{w}'] = int(max_idx >= 7)
        features[f'fu_completed_funnel_flag_{w}'] = int(fu_disb > 0)
        features[f'fu_total_events_cnt_{w}'] = int(d['event_name'].isin(ALL_FU_EVENTS).sum())

        # Upsell promo
        features[f'upsell_promo_cnt_{w}'] = int(
            (d['event_name'] == 'upsell_free_card_promo').sum())

        # Timing: entry to offer
        entry_times = d.loc[d['event_name'] == 'loans_fu_6andup', col]
        offer_times = d.loc[d['event_name'] == 'loans_fu_disburse_success', col]
        if not entry_times.empty and not offer_times.empty:
            first_entry = entry_times.min()
            future = offer_times[offer_times >= first_entry]
            features[f'fu_entry_to_disburse_sec_{w}'] = (
                (future.min() - first_entry).total_seconds() if not future.empty else np.nan)
        else:
            features[f'fu_entry_to_disburse_sec_{w}'] = np.nan

    return features
