"""
Help & support contact features for B-Score Events.
Version: v20260423

Support contact is a double-edged signal: contacting help could mean the
customer is proactive and engaged, OR that they're in financial distress.
The channel matters: chatbot (self-service) vs hotline (escalated issue).
"""
import numpy as np
from .config import HELP_EVENTS, BILLS_PAY_EVENTS


def compute_support_features(window_dfs):
    """Compute help and support contact features."""
    features = {}

    for w, d in window_dfs.items():
        # ---- General help ----
        help_cnt = int((d['event_name'] == 'help').sum())
        tsa_help_cnt = int((d['event_name'] == 'tsa_help').sum())
        total_help = help_cnt + tsa_help_cnt

        features[f'help_cnt_{w}'] = total_help
        features[f'help_flag_{w}'] = int(total_help > 0)

        # ---- Help channel breakdown ----
        features[f'help_chatbot_cnt_{w}'] = int(
            (d['event_name'] == 'tsa_help_chatbot').sum())
        features[f'help_faq_cnt_{w}'] = int(
            (d['event_name'] == 'tsa_help_faq').sum())
        features[f'help_hotline_cnt_{w}'] = int(
            (d['event_name'] == 'tsa_help_hotline').sum())

        # Hotline contact = highest escalation signal
        features[f'help_hotline_flag_{w}'] = int(
            (d['event_name'] == 'tsa_help_hotline').any())

        # ---- Back navigation (signal of friction / confusion) ----
        ql_back_cnt = int((d['event_name'] == 'ql_back').sum())
        features[f'ql_back_cnt_{w}'] = ql_back_cnt
        features[f'ql_back_flag_{w}'] = int(ql_back_cnt > 0)

        # ---- Total support events ----
        all_support = HELP_EVENTS + BILLS_PAY_EVENTS + ['ql_back']
        features[f'support_total_events_cnt_{w}'] = int(
            d['event_name'].isin(all_support).sum()
        )

        # ---- TSA Profile events (account management) ----
        features[f'tsa_profile_cnt_{w}'] = int(
            d['event_name'].isin(['tsa_profile_additional', 'tsa_profile_request']).sum()
        )

    return features
