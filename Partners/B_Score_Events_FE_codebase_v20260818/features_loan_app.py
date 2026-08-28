"""
Loan application activity features for B-Score Events.
Version: v20260818

Covers the full QL (Quick Loan) re-borrowing journey through disbursement,
plus QL Sales Screens, loan dashboard, SIL in-window activity,
and the ANY_NEW_LOAN_DISBURSED composite flag.
"""
import numpy as np
import pandas as pd
from .config import (
    QL_EARLY_FUNNEL, QL_OFFER_EVENTS, QL_COMPLETION_EVENTS,
    QL_SALES_SCREEN_EVENTS, LOAN_DASHBOARD_EVENTS,
    SIL_APPLICATION_EVENTS, SIL_QR_EVENTS, ANY_DISBURSE_EVENTS,
)

QL_FUNNEL_ORDERED = [
    'loans_selection', 'loans_input_amount', 'loans_ql_calculator',
    'loans_ql_application_launch', 'loans_ql_application_purpose',
    'loans_ql_application_summary', 'loans_ql_application_loanamount',
    'loans_ql_application_civil', 'loans_ql_application_dependents',
    'loans_ql_application_income', 'loans_ql_application_company',
    'loans_ql_application_tin', 'loans_ql_education',
    'loans_ql_application_backupmobile', 'loans_ql_application_terms',
    'loans_ql_summary_no_vas', 'loans_ql_offer',
    'loans_ql_offer_signalldocs', 'loans_ql_application_completed',
    'loans_ql_disburse_success',
]
QL_IDX = {e: i for i, e in enumerate(QL_FUNNEL_ORDERED)}

QL_SHORT = {
    'loans_selection': 'ql_selection',
    'loans_input_amount': 'ql_input_amt',
    'loans_ql_calculator': 'ql_calculator',
    'loans_ql_application_launch': 'ql_app_launch',
    'loans_ql_application_summary': 'ql_app_summary',
    'loans_ql_application_loanamount': 'ql_loan_amt',
    'loans_ql_application_purpose': 'ql_purpose',
    'loans_ql_application_civil': 'ql_civil',
    'loans_ql_application_dependents': 'ql_dependents',
    'loans_ql_application_income': 'ql_income',
    'loans_ql_application_company': 'ql_company',
    'loans_ql_application_tin': 'ql_tin',
    'loans_ql_education': 'ql_education',
    'loans_ql_contact_reference_1': 'ql_ref1',
    'loans_ql_contact_reference_2': 'ql_ref2',
    'loans_ql_address': 'ql_address',
    'loans_ql_occupation': 'ql_occupation',
    'loans_ql_application_backupmobile': 'ql_backupmobile',
    'loans_ql_application_terms': 'ql_terms',
    'loans_ql_bkyc': 'ql_bkyc',
    'loans_fl_skyc': 'ql_fl_skyc',
    'loans_ql_summary_no_vas': 'ql_summary_no_vas',
}
ALL_QL_EVENTS = QL_EARLY_FUNNEL + QL_OFFER_EVENTS + QL_COMPLETION_EVENTS


def compute_loan_app_features(window_dfs):
    features = {}
    for w, d in window_dfs.items():
        col = 'event_time_manila' if 'event_time_manila' in d.columns else 'event_time'

        # Per-screen early funnel
        for event in QL_EARLY_FUNNEL:
            short = QL_SHORT.get(event, 'ql_' + event.replace('loans_ql_application_', '').replace('loans_ql_', '').replace('loans_', ''))
            cnt = int((d['event_name'] == event).sum())
            features[f'{short}_cnt_{w}'] = cnt
            features[f'{short}_flag_{w}'] = int(cnt > 0)
            features[f'{short}_repeat_cnt_{w}'] = max(cnt - 1, 0)

        # Funnel depth
        reached = [e for e in QL_FUNNEL_ORDERED if (d['event_name'] == e).any()]
        max_idx = max((QL_IDX[e] for e in reached), default=-1)
        features[f'ql_funnel_max_depth_{w}'] = max_idx + 1
        features[f'ql_funnel_started_flag_{w}'] = int(max_idx >= 0)
        features[f'ql_funnel_reached_form_flag_{w}'] = int(max_idx >= 7)
        features[f'ql_funnel_reached_offer_flag_{w}'] = int(max_idx >= 16)
        features[f'ql_funnel_reached_completed_flag_{w}'] = int(
            (d['event_name'] == 'loans_ql_application_completed').any())
        features[f'ql_funnel_screens_visited_cnt_{w}'] = len(reached)

        # QL Sales Screens
        for i, evt in enumerate(['loans_ql_sales_screen_1','loans_ql_sales_screen_2','loans_ql_sales_screen_3'], 1):
            cnt = int((d['event_name'] == evt).sum())
            features[f'ql_sales_screen{i}_cnt_{w}'] = cnt
            features[f'ql_sales_screen{i}_flag_{w}'] = int(cnt > 0)
        features[f'ql_sales_total_cnt_{w}'] = int(d['event_name'].isin(QL_SALES_SCREEN_EVENTS).sum())
        features[f'ql_sales_started_flag_{w}'] = int(d['event_name'].isin(QL_SALES_SCREEN_EVENTS).any())

        # QL offer journey
        features[f'ql_offer_cnt_{w}'] = int((d['event_name'] == 'loans_ql_offer').sum())
        features[f'ql_offer_flag_{w}'] = int((d['event_name'] == 'loans_ql_offer').any())
        features[f'ql_offer_success_flag_{w}'] = int(d['event_name'].str.startswith('loans_ql_offer_success').any())
        features[f'ql_offer_total_events_cnt_{w}'] = int(d['event_name'].isin(QL_OFFER_EVENTS).sum())

        # QL completion & disbursement (CRITICAL)
        features[f'ql_completed_flag_{w}'] = int((d['event_name'] == 'loans_ql_application_completed').any())
        features[f'ql_launch_approved_flag_{w}'] = int(d['event_name'].isin(['loans_ql_launch_approved','loans_launch_approved']).any())
        ql_disb = int((d['event_name'] == 'loans_ql_disburse_success').sum())
        features[f'ql_disburse_success_cnt_{w}'] = ql_disb
        features[f'ql_disburse_success_flag_{w}'] = int(ql_disb > 0)

        # Drop-off
        features[f'ql_inprogress_cnt_{w}'] = int((d['event_name'] == 'loans_launch_inprogress').sum())
        features[f'ql_inprogress_flag_{w}'] = int((d['event_name'] == 'loans_launch_inprogress').any())
        features[f'ql_dntstopmenow_cnt_{w}'] = int((d['event_name'] == 'loans_ql_dntstopmenow').sum())

        # Total QL
        features[f'ql_total_events_cnt_{w}'] = int(d['event_name'].isin(ALL_QL_EVENTS).sum())

        # Loan dashboard
        features[f'loans_dashboard_cnt_{w}'] = int((d['event_name'] == 'loans_dashboard').sum())
        features[f'loans_dashboard_flag_{w}'] = int((d['event_name'] == 'loans_dashboard').any())
        features[f'loans_dashboard_vas_cnt_{w}'] = int((d['event_name'] == 'loans_dashboard_vas').sum())
        features[f'loans_vas_popup_cnt_{w}'] = int((d['event_name'] == 'loans_vas_popup').sum())
        features[f'loans_proof_of_cover_cnt_{w}'] = int((d['event_name'] == 'loans_proof_of_cover').sum())
        features[f'loans_launch_fully_paid_flag_{w}'] = int((d['event_name'] == 'loans_launch_payments_fullypaid').any())
        features[f'loans_launch_payments_done_flag_{w}'] = int((d['event_name'] == 'loans_launch_payments_done').any())
        features[f'loans_launch_approved_flag_{w}'] = int((d['event_name'] == 'loans_launch_approved').any())

        # SIL in-window
        features[f'sil_application_flag_{w}'] = int(d['event_name'].isin(SIL_APPLICATION_EVENTS).any())
        features[f'sil_application_events_cnt_{w}'] = int(d['event_name'].isin(SIL_APPLICATION_EVENTS).sum())
        features[f'sil_qr_events_cnt_{w}'] = int(d['event_name'].isin(SIL_QR_EVENTS).sum())
        features[f'sil_qr_scan_flag_{w}'] = int((d['event_name'] == 'loans_sil_qr_scan').any())
        features[f'sil_completed_flag_{w}'] = int((d['event_name'] == 'loans_sil_application_completed').any())

        # ANY new loan disbursement (composite)
        any_disb = d['event_name'].isin(ANY_DISBURSE_EVENTS)
        features[f'any_new_loan_disbursed_flag_{w}'] = int(any_disb.any())
        features[f'any_new_loan_disbursed_cnt_{w}'] = int(any_disb.sum())
        disb_times = d.loc[any_disb, col]
        if not disb_times.empty:
            features[f'last_disbursement_recency_hrs_{w}'] = round(
                (d[col].max() - disb_times.max()).total_seconds() / 3600, 2)
        else:
            features[f'last_disbursement_recency_hrs_{w}'] = np.nan

    return features
