"""
Communication engagement features for B-Score Events.
Version: v20260424

Updated: Added notification_clicked (click-through signal),
mobile in-app clicked / auto-dismissed variants.
"""
import numpy as np
from .config import EMAIL_EVENTS, SMS_EVENTS, PUSH_EVENTS, IN_APP_EVENTS


def compute_comms_features(window_dfs):
    features = {}
    for w, d in window_dfs.items():
        # Email
        email_delivered = int((d['event_name'] == 'email delivered').sum())
        email_opened = int((d['event_name'] == 'email opened').sum())
        email_sent = int((d['event_name'] == 'email sent').sum())
        email_dropped = int((d['event_name'] == 'email dropped').sum())
        features[f'email_delivered_cnt_{w}'] = email_delivered
        features[f'email_opened_cnt_{w}'] = email_opened
        features[f'email_sent_cnt_{w}'] = email_sent
        features[f'email_dropped_cnt_{w}'] = email_dropped
        features[f'email_open_flag_{w}'] = int(email_opened > 0)
        features[f'email_open_rate_{w}'] = (
            round(email_opened / email_delivered, 4) if email_delivered > 0 else np.nan)
        total_email = email_delivered + email_dropped
        features[f'email_drop_rate_{w}'] = (
            round(email_dropped / total_email, 4) if total_email > 0 else np.nan)
        features[f'email_total_cnt_{w}'] = int(d['event_name'].isin(EMAIL_EVENTS).sum())

        # SMS
        sms_cnt = int(d['event_name'].isin(SMS_EVENTS).sum())
        features[f'sms_cnt_{w}'] = sms_cnt
        features[f'sms_flag_{w}'] = int(sms_cnt > 0)

        # Push
        push_sent_ios = int((d['event_name'] == 'notification sent ios').sum())
        push_recv_android = int((d['event_name'] == 'notification received android').sum())
        push_clicked = int((d['event_name'] == 'notification clicked android').sum())
        push_total = push_sent_ios + push_recv_android
        features[f'push_sent_cnt_{w}'] = push_total
        features[f'push_flag_{w}'] = int(push_total > 0)
        features[f'push_clicked_cnt_{w}'] = push_clicked                   # NEW: click-through
        features[f'push_clicked_flag_{w}'] = int(push_clicked > 0)
        features[f'push_click_rate_{w}'] = (
            round(push_clicked / max(push_total, 1), 4) if push_total > 0 else np.nan)
        features[f'push_permission_flag_{w}'] = int(
            (d['event_name'] == 'moe_push_permission_state_allowed').any())
        features[f'push_permission_blocked_flag_{w}'] = int(
            (d['event_name'] == 'moe_push_permission_state_blocked').any())

        # In-app
        inapp_shown = int((d['event_name'] == 'mobile in-app shown').sum())
        inapp_closed = int((d['event_name'] == 'mobile in-app closed').sum())
        inapp_clicked = int((d['event_name'] == 'mobile in-app clicked').sum())       # NEW
        inapp_auto_dismissed = int((d['event_name'] == 'mobile in-app auto dismissed').sum())  # NEW
        inapp_attempted = int((d['event_name'] == 'moe_in_app_attempted').sum())
        features[f'inapp_shown_cnt_{w}'] = inapp_shown
        features[f'inapp_closed_cnt_{w}'] = inapp_closed
        features[f'inapp_clicked_cnt_{w}'] = inapp_clicked
        features[f'inapp_auto_dismissed_cnt_{w}'] = inapp_auto_dismissed
        features[f'inapp_attempted_cnt_{w}'] = inapp_attempted
        features[f'inapp_flag_{w}'] = int(inapp_shown > 0)
        features[f'inapp_click_flag_{w}'] = int(inapp_clicked > 0)
        features[f'inapp_click_rate_{w}'] = (
            round(inapp_clicked / inapp_shown, 4) if inapp_shown > 0 else np.nan)
        features[f'inapp_dismiss_rate_{w}'] = (
            round((inapp_closed + inapp_auto_dismissed) / inapp_shown, 4)
            if inapp_shown > 0 else np.nan)

        # Overall
        total_comms = email_delivered + sms_cnt + push_total + inapp_shown
        total_engaged = email_opened + push_clicked + inapp_clicked
        features[f'comms_total_cnt_{w}'] = total_comms
        features[f'comms_any_engagement_flag_{w}'] = int(total_engaged > 0)
        features[f'comms_engagement_cnt_{w}'] = total_engaged

    return features
