"""
Payment behaviour features for B-Score Events.
Version: v20260818

Updated: Added loan_payment_success, loan_disbursement, offer_used/delete,
and loan_payment_transaction_details. Disbursement events now tracked here too.
"""
import numpy as np
import pandas as pd
from .config import PAYMENT_EVENTS, PAYMENT_REMINDER_EVENTS


def compute_payment_features(window_dfs):
    features = {}
    for w, d in window_dfs.items():
        col = 'event_time_manila' if 'event_time_manila' in d.columns else 'event_time'

        # Attempts
        pay_cnt = int((d['event_name'] == 'loan_payment').sum())
        features[f'payment_attempt_cnt_{w}'] = pay_cnt
        features[f'payment_attempt_flag_{w}'] = int(pay_cnt > 0)
        features[f'payment_confirm_cnt_{w}'] = int((d['event_name'] == 'loan_payment_confirm').sum())
        features[f'payment_inprogress_cnt_{w}'] = int((d['event_name'] == 'loan_payment_in_progress').sum())
        features[f'payment_status_cnt_{w}'] = int((d['event_name'] == 'loan_payment_status').sum())
        features[f'payment_txn_details_cnt_{w}'] = int((d['event_name'] == 'loan_payment_transaction_details').sum())

        # GCash payment
        gcash_pay = int((d['event_name'] == 'loan_payment_gcash').sum())
        features[f'payment_gcash_cnt_{w}'] = gcash_pay
        features[f'payment_gcash_flag_{w}'] = int(gcash_pay > 0)

        # Success events (two variants)
        repay_success = int(d['event_name'].isin([
            'loan_monthly_repayment_success', 'loan_payment_success']).sum())
        features[f'repayment_success_cnt_{w}'] = repay_success
        features[f'repayment_success_flag_{w}'] = int(repay_success > 0)
        features[f'payment_done_cnt_{w}'] = int((d['event_name'] == 'payment_done').sum())

        # Success rate
        total_attempts = pay_cnt + gcash_pay
        features[f'repayment_success_rate_{w}'] = (
            round(repay_success / total_attempts, 4) if total_attempts > 0 else np.nan)
        features[f'gcash_payment_share_{w}'] = (
            round(gcash_pay / total_attempts, 4) if total_attempts > 0 else np.nan)

        # Loan disbursement received (any product)
        features[f'loan_disbursement_received_flag_{w}'] = int(
            (d['event_name'] == 'loan_disbursement').any())

        # Total payment events
        features[f'payment_total_events_cnt_{w}'] = int(d['event_name'].isin(PAYMENT_EVENTS).sum())

        # Reminders
        reminder_cnt = int(d['event_name'].isin(PAYMENT_REMINDER_EVENTS).sum())
        features[f'payment_reminder_cnt_{w}'] = reminder_cnt
        features[f'payment_reminder_flag_{w}'] = int(reminder_cnt > 0)
        features[f'monthly_due_reminder_cnt_{w}'] = int((d['event_name'] == 'monthly_due_reminder').sum())
        features[f'payment_coming_up_cnt_{w}'] = int(
            d['event_name'].isin(['payment_comingup', 'event_loan_payment_coming_up']).sum())
        features[f'due_date_cnt_{w}'] = int((d['event_name'] == 'due_date').sum())

        # Reminder → payment response
        reminder_times = d.loc[d['event_name'].isin(PAYMENT_REMINDER_EVENTS), col].sort_values()
        payment_times = d.loc[d['event_name'].isin([
            'loan_payment', 'loan_payment_gcash', 'loan_monthly_repayment_success',
            'loan_payment_success']), col].sort_values()

        responded_cnt, response_gaps = 0, []
        for rt in reminder_times:
            future = payment_times[payment_times >= rt]
            if not future.empty:
                gap_hrs = (future.iloc[0] - rt).total_seconds() / 3600
                if gap_hrs <= 24:
                    responded_cnt += 1
                    response_gaps.append(gap_hrs)

        features[f'reminder_response_cnt_{w}'] = responded_cnt
        features[f'reminder_response_rate_{w}'] = (
            round(responded_cnt / max(len(reminder_times), 1), 4)
            if len(reminder_times) > 0 else np.nan)
        features[f'reminder_response_avg_hrs_{w}'] = (
            float(np.mean(response_gaps)) if response_gaps else np.nan)

        # Payment time-of-day
        pay_df = d[d['event_name'].isin(['loan_payment', 'loan_payment_gcash',
                                          'loan_monthly_repayment_success', 'loan_payment_success'])]
        features[f'payment_tod_med_{w}'] = (
            float(pay_df['hour'].median()) if len(pay_df) > 0 else np.nan)

        # Recency of last payment
        all_pay_times = d.loc[d['event_name'].isin(PAYMENT_EVENTS), col]
        if not all_pay_times.empty:
            features[f'last_payment_recency_hrs_{w}'] = round(
                (d[col].max() - all_pay_times.max()).total_seconds() / 3600, 2)
        else:
            features[f'last_payment_recency_hrs_{w}'] = np.nan

    return features
