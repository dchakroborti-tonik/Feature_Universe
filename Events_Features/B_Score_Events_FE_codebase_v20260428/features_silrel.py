"""
SILRel (SIL Relending) features for B-Score Events.
Version: v20260424

SILRel = In-store relending: the customer visits a merchant and scans a new QR
to get a new SIL-type loan while possibly already holding an existing loan.
silrel_purchase_success = new purchase completed at store = new debt added.
"""
import numpy as np
from .config import SILREL_EVENTS

SILREL_FUNNEL_ORDERED = [
    'loans_silrel', 'loans_silrel_qr_scan', 'loans_silrel_occupation',
    'loans_silrel_address', 'loans_silrel_application_summary',
    'loans_silrel_application_terms', 'loans_silrel_offer',
    'loans_silrel_offer_paydays', 'loans_silrel_offer_summary',
    'loans_silrel_approved_offer', 'loans_silrel_confirmation',
    'loans_silrel_purchase_success',
]
SILREL_IDX = {e: i for i, e in enumerate(SILREL_FUNNEL_ORDERED)}


def compute_silrel_features(window_dfs):
    features = {}
    for w, d in window_dfs.items():
        col = 'event_time_manila' if 'event_time_manila' in d.columns else 'event_time'

        # Entry
        features[f'silrel_entry_cnt_{w}'] = int((d['event_name'] == 'loans_silrel').sum())
        features[f'silrel_entry_flag_{w}'] = int((d['event_name'] == 'loans_silrel').any())
        features[f'silrel_qr_scan_flag_{w}'] = int((d['event_name'] == 'loans_silrel_qr_scan').any())

        # Application form
        features[f'silrel_application_started_flag_{w}'] = int(
            d['event_name'].isin(['loans_silrel_occupation', 'loans_silrel_address',
                                   'loans_silrel_application_summary']).any())

        # Offer
        features[f'silrel_offer_flag_{w}'] = int((d['event_name'] == 'loans_silrel_offer').any())
        features[f'silrel_approved_offer_flag_{w}'] = int(
            (d['event_name'] == 'loans_silrel_approved_offer').any())
        features[f'silrel_offer_dashboard_flag_{w}'] = int(
            (d['event_name'] == 'loans_silrel_offer_dashboard').any())

        # Completion (new purchase at store)
        silrel_purchase = int((d['event_name'] == 'loans_silrel_purchase_success').sum())
        features[f'silrel_purchase_success_cnt_{w}'] = silrel_purchase
        features[f'silrel_purchase_success_flag_{w}'] = int(silrel_purchase > 0)
        features[f'silrel_disburse_fail_flag_{w}'] = int(
            (d['event_name'] == 'loans_silrel_disburse_fail').any())

        # Funnel depth
        reached = [e for e in SILREL_FUNNEL_ORDERED if (d['event_name'] == e).any()]
        max_idx = max((SILREL_IDX[e] for e in reached), default=-1)
        features[f'silrel_funnel_depth_{w}'] = max_idx + 1
        features[f'silrel_funnel_started_flag_{w}'] = int(max_idx >= 0)

        # Total SILRel events
        features[f'silrel_total_events_cnt_{w}'] = int(
            d['event_name'].isin(SILREL_EVENTS).sum())

    return features
