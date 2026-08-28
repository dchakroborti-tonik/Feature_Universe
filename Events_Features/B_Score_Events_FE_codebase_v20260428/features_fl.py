"""
FlexLoan (FL/FlXL) and UIL product features for B-Score Events.
Version: v20260424

FL = FlexLoan (pre-approved revolving facility for established customers)
FlXL = FlexLoan XL (larger variant)
UIL = Universal Income Loan (income-based screens)

loans_fl_income is the key entry: seeing this means the customer was
being evaluated for a FlexLoan based on their income.
loans_flxl_disburse_success = FlexXL loan disbursed.
"""
import numpy as np
from .config import FL_EVENTS, UIL_EVENTS


def compute_fl_features(window_dfs):
    features = {}
    for w, d in window_dfs.items():
        # FL income screen (eligibility check)
        features[f'fl_income_cnt_{w}'] = int((d['event_name'] == 'loans_fl_income').sum())
        features[f'fl_income_flag_{w}'] = int((d['event_name'] == 'loans_fl_income').any())

        # FL calculator and selection
        features[f'fl_calculator_flag_{w}'] = int(
            d['event_name'].isin(['loans_fl_calculator', 'loans_flxl_calculator']).any())
        features[f'fl_selection_flag_{w}'] = int(
            (d['event_name'] == 'loans_fl_selection').any())

        # FL sales screens (pre-approval pitch)
        fl_sales_cnt = int(d['event_name'].isin([
            'loans_fl_sales_screen_1', 'loans_fl_sales_screen_2',
            'loans_fl_sales_screen_3']).sum())
        features[f'fl_sales_cnt_{w}'] = fl_sales_cnt
        features[f'fl_sales_flag_{w}'] = int(fl_sales_cnt > 0)
        features[f'fl_preapproved_offer_flag_{w}'] = int(
            (d['event_name'] == 'loans_fl_preapproved_offer').any())

        # FlXL marital status (additional form screen unique to FlXL)
        features[f'flxl_maritalstatus_flag_{w}'] = int(
            (d['event_name'] == 'loans_flxl_maritalstatus').any())

        # FlXL disbursement
        flxl_disb = int((d['event_name'] == 'loans_flxl_disburse_success').sum())
        features[f'flxl_disburse_success_cnt_{w}'] = flxl_disb
        features[f'flxl_disburse_success_flag_{w}'] = int(flxl_disb > 0)

        # ACL Counter Calculator
        features[f'acl_counter_cal_flag_{w}'] = int(
            (d['event_name'] == 'loans_acl_counter_cal').any())

        # Total FL events
        features[f'fl_total_events_cnt_{w}'] = int(
            d['event_name'].isin(FL_EVENTS).sum())

        # UIL screens
        features[f'uil_main_flag_{w}'] = int((d['event_name'] == 'loans_uil_main').any())
        features[f'uil_employment_flag_{w}'] = int(
            (d['event_name'] == 'loans_uil_employment_status').any())
        features[f'uil_income_source_flag_{w}'] = int(
            (d['event_name'] == 'loans_uil_source_of_income').any())
        features[f'uil_total_events_cnt_{w}'] = int(
            d['event_name'].isin(UIL_EVENTS).sum())
        features[f'uil_started_flag_{w}'] = int(
            d['event_name'].isin(UIL_EVENTS).any())

        # Any FL/UIL activity (eligibility screening signal)
        features[f'fl_uil_any_flag_{w}'] = int(
            d['event_name'].isin(FL_EVENTS + UIL_EVENTS).any())

    return features
