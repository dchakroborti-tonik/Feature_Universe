"""
Financial activity features for B-Score Events.
Version: v20260818

Updated: richer topup variants (debit card, OTC, online), QR payment events,
payment sending (P2P, interbank InstaPay/PesoNet), GCash success events,
and comprehensive TSA account management signals.
"""
import numpy as np
from .config import TOPUP_EVENTS, CARD_EVENTS, GCASH_EVENTS, STASH_EVENTS, PAYMENT_SEND_EVENTS, TSA_EVENTS


def compute_financial_features(window_dfs):
    features = {}
    for w, d in window_dfs.items():
        # Top-up (broken out by channel)
        topup_main = int((d['event_name'] == 'payments_topup_main').sum())
        topup_interbank = int((d['event_name'] == 'payments_topup_interbank').sum())
        topup_debit = int((d['event_name'] == 'payments_topup_debit_card').sum())
        topup_online = int(d['event_name'].isin(['payments_topup_online',
                                                  'payments_topup_online_gcash_success']).sum())
        topup_otc = int(d['event_name'].isin(['payments_topup_otc',
                                               'payments_topup_otc_mlhuillier']).sum())
        topup_other = int(d['event_name'].isin(['top_up', 'top_up_peso_insta']).sum())
        topup_total = topup_main + topup_interbank + topup_debit + topup_online + topup_otc + topup_other

        features[f'topup_total_cnt_{w}'] = topup_total
        features[f'topup_flag_{w}'] = int(topup_total > 0)
        features[f'topup_main_cnt_{w}'] = topup_main
        features[f'topup_interbank_cnt_{w}'] = topup_interbank
        features[f'topup_debit_card_cnt_{w}'] = topup_debit
        features[f'topup_online_cnt_{w}'] = topup_online
        features[f'topup_otc_cnt_{w}'] = topup_otc
        features[f'topup_unique_channels_{w}'] = int(sum(c > 0 for c in [
            topup_main, topup_interbank, topup_debit, topup_online, topup_otc]))

        # Card usage
        card_cnt = int(d['event_name'].isin(CARD_EVENTS).sum())
        features[f'card_events_cnt_{w}'] = card_cnt
        features[f'card_flag_{w}'] = int(card_cnt > 0)
        features[f'card_physical_cnt_{w}'] = int(d['event_name'].isin(
            ['payments_cards_physical', 'payments_cards_phyisical_free']).sum())
        features[f'card_virtual_cnt_{w}'] = int(d['event_name'].isin(
            ['payments_cards_virtual', 'payments_cards_virtual_lock',
             'payments_cards_virtual_unlock']).sum())

        # GCash linking
        gcash_link_cnt = int(d['event_name'].isin(GCASH_EVENTS).sum())
        features[f'gcash_linking_cnt_{w}'] = gcash_link_cnt
        features[f'gcash_linking_flag_{w}'] = int(gcash_link_cnt > 0)
        features[f'gcash_linking_success_flag_{w}'] = int(
            d['event_name'].isin(['gcash_linking_processing_loaded',
                                   'gcash_linking_success_loaded']).any())

        # Payment sending (P2P / bank transfers)
        send_total = int(d['event_name'].isin(PAYMENT_SEND_EVENTS).sum())
        features[f'payment_send_total_cnt_{w}'] = send_total
        features[f'payment_send_flag_{w}'] = int(send_total > 0)
        features[f'payment_send_tonik_cnt_{w}'] = int(d['event_name'].isin(
            ['payments_send_tonik', 'payments_send_tonik_mobile']).sum())
        features[f'payment_send_interbank_cnt_{w}'] = int(d['event_name'].isin(
            ['payments_send_interbank', 'payments_send_interbank_instapay',
             'payments_send_interbank_instapay_success',
             'payments_send_interbank_pesonet_success']).sum())
        features[f'payment_send_success_cnt_{w}'] = int(d['event_name'].isin(
            ['payments_send_interbank_instapay_success',
             'payments_send_interbank_pesonet_success']).sum())

        # QR payments
        qr_pay_cnt = int(d['event_name'].isin(['qr_scanning', 'qr_code_generated',
                                                'qr_summary_p2m', 'qr_summary_p2p',
                                                'qr_with_amount', 'qr_without_amount']).sum())
        features[f'qr_payment_cnt_{w}'] = qr_pay_cnt
        features[f'qr_payment_flag_{w}'] = int(qr_pay_cnt > 0)
        features[f'qr_p2m_cnt_{w}'] = int((d['event_name'] == 'qr_summary_p2m').sum())
        features[f'qr_p2p_cnt_{w}'] = int((d['event_name'] == 'qr_summary_p2p').sum())

        # Stash (savings)
        stash_cnt = int(d['event_name'].isin(STASH_EVENTS).sum())
        features[f'stash_events_cnt_{w}'] = stash_cnt
        features[f'stash_flag_{w}'] = int(stash_cnt > 0)
        features[f'stash_add_cnt_{w}'] = int(d['event_name'].isin(
            ['stash_add', 'stash_add_success']).sum())
        features[f'stash_created_flag_{w}'] = int(d['event_name'].isin(
            ['stash_setup_success_solo', 'stash_setup_initial_success']).any())

        # TSA account management
        tsa_mgmt_cnt = int(d['event_name'].isin(TSA_EVENTS).sum())
        features[f'tsa_events_cnt_{w}'] = tsa_mgmt_cnt
        features[f'tsa_history_flag_{w}'] = int(d['event_name'].isin(
            ['tsa_account_history', 'tsa_history_manage', 'tsa_history_topup']).any())
        features[f'tsa_manage_flag_{w}'] = int(d['event_name'].isin(
            ['tsa_manage', 'tsa_manage_fees', 'tsa_manage_limits']).any())
        features[f'tsa_profile_update_cnt_{w}'] = int(d['event_name'].isin(
            ['tsa_profile_additional', 'tsa_profile_additional_update',
             'tsa_profile_contact', 'tsa_profile_personal', 'profile_updateinfo']).sum())
        features[f'dashboard_tile_cnt_{w}'] = int((d['event_name'] == 'dashboard_tile').sum())

        # Bills
        features[f'bills_pay_cnt_{w}'] = int(
            d['event_name'].isin(['pay_bills_splash', 'pay_bills_back']).sum())

        # Total financial activity
        all_fin = (TOPUP_EVENTS + CARD_EVENTS + GCASH_EVENTS + STASH_EVENTS
                   + PAYMENT_SEND_EVENTS + TSA_EVENTS)
        features[f'financial_total_events_cnt_{w}'] = int(d['event_name'].isin(all_fin).sum())
        features[f'financial_any_flag_{w}'] = int(
            (topup_total + card_cnt + gcash_link_cnt + stash_cnt + send_total + qr_pay_cnt) > 0)

    return features
