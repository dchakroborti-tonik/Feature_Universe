"""
Relending (RL) product features for B-Score Events.
Version: v20260424

RL = Relending: a revolving/refinancing loan product. The RL journey includes
sales screens, a short application, offer with amortization signatures, and
disbursement. rl_disburse_success = new RL loan added.
"""
import numpy as np
from .config import RL_EVENTS

RL_FUNNEL_ORDERED = [
    'loans_rl_sales_screen', 'loans_rl_sales_screen_accept',
    'loans_rl_application_launch', 'loans_rl_application_summary',
    'loans_rl_application_purpose', 'loans_rl_application_terms',
    'loans_rl_application_completed', 'loans_rl_offer_summary',
    'loans_rl_offer_signatures', 'loans_rl_offer_success',
    'loans_rl_disburse_success',
]
RL_IDX = {e: i for i, e in enumerate(RL_FUNNEL_ORDERED)}


def compute_rl_features(window_dfs):
    features = {}
    for w, d in window_dfs.items():
        # Sales entry
        features[f'rl_sales_screen_cnt_{w}'] = int(
            d['event_name'].isin(['loans_rl_sales_screen', 'loans_rl_sales_screens']).sum())
        features[f'rl_sales_screen_flag_{w}'] = int(
            d['event_name'].isin(['loans_rl_sales_screen', 'loans_rl_sales_screens']).any())
        features[f'rl_sales_accepted_flag_{w}'] = int(
            (d['event_name'] == 'loans_rl_sales_screen_accept').any())

        # Application
        features[f'rl_application_started_flag_{w}'] = int(
            (d['event_name'] == 'loans_rl_application_launch').any())
        features[f'rl_application_completed_flag_{w}'] = int(
            (d['event_name'] == 'loans_rl_application_completed').any())

        # Offer
        features[f'rl_offer_flag_{w}'] = int(
            d['event_name'].isin(['loans_rl_offer_summary', 'loans_rl_offer_success']).any())
        features[f'rl_offer_signed_flag_{w}'] = int(
            d['event_name'].isin(['loans_rl_offer_signatures', 'loans_rl_offer_amort_signed']).any())

        # Disbursement (new RL loan)
        rl_disb = int((d['event_name'] == 'loans_rl_disburse_success').sum())
        features[f'rl_disburse_success_cnt_{w}'] = rl_disb
        features[f'rl_disburse_success_flag_{w}'] = int(rl_disb > 0)

        # Funnel depth
        reached = [e for e in RL_FUNNEL_ORDERED if (d['event_name'] == e).any()]
        max_idx = max((RL_IDX[e] for e in reached), default=-1)
        features[f'rl_funnel_depth_{w}'] = max_idx + 1
        features[f'rl_funnel_started_flag_{w}'] = int(max_idx >= 0)

        # Summary features
        features[f'rl_summary_no_vas_flag_{w}'] = int(
            (d['event_name'] == 'loans_rl_summary_no_vas').any())
        features[f'rl_payhinga_info_flag_{w}'] = int(
            (d['event_name'] == 'loans_rl_payhinga_info').any())
        features[f'rl_total_events_cnt_{w}'] = int(
            d['event_name'].isin(RL_EVENTS).sum())

    return features
