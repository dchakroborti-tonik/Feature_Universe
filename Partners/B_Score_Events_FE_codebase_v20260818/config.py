"""
Configuration constants for B-Score Events Feature Engineering.
Version: v20260818

Changes from v20260817:
  - DEDUP_COLUMNS removes digitalLoanAccountId and uses the
    customer-observation grain.

Observation window: last 7 days before observation_datetime.
Event time column : event_time_manila (PH timezone, tz-naive after main.py conversion).
"""

# ============================================================
# TIME WINDOW
# ============================================================
WINDOWS = {'7d': 168}   # 168 hours = 7 days

SESSION_GAP_SEC = 300
DROPOFF_GAP_SEC = 300
# FIX v20260428: was 'customerId' — source table column is 'customer_id'
DEDUP_COLUMNS = [
    'customer_id',
    'moengage_user_id',
    'event_time_manila',
    'event_name',
    'observation_datetime',
]

# ============================================================
# QUICK LOAN (QL) RE-BORROWING JOURNEY
# Screens are ordered by funnel depth.  Seeing deeper screens = stronger signal.
# ============================================================
QL_EARLY_FUNNEL = [
    'loans_selection',
    'loans_input_amount',
    'loans_ql_calculator',
    'loans_ql_application_launch',
    'loans_ql_application_summary',
    'loans_ql_application_loanamount',
    'loans_ql_application_purpose',
    'loans_ql_application_civil',
    'loans_ql_application_civil_single',
    'loans_ql_application_dependents',
    'loans_ql_application_income',
    'loans_ql_application_company',
    'loans_ql_application_tin',
    'loans_ql_education',
    'loans_ql_contact_reference_1',
    'loans_ql_contact_reference_2',
    'loans_ql_application_backupmobile',
    'loans_ql_address',
    'loans_ql_occupation',
    'loans_ql_application_terms',
    'loans_ql_application_terms_apply',
    'loans_ql_bkyc',
    'loans_fl_skyc',
    'loans_ql_summary_no_vas',
]

QL_OFFER_EVENTS = [
    'loans_ql_offer',
    'loans_ql_approved_offer',
    'loans_ql_offer_paydays',
    'loans_ql_offer_signalldocs',
    'loans_ql_offer_signature',
    'loans_ql_offer_signatures',
    'loans_ql_offer_summary',
    'loans_ql_offer_success',
    'loans_ql_offer_summary_success',
    'loans_ql_offer_accepted',
    'loans_ql_payhinga_info',
]

QL_COMPLETION_EVENTS = [
    'loans_ql_application_completed',
    'loans_ql_application_income_success',
    'loans_ql_application_dependents_success',
    'loans_ql_application_civil_success',
    'loans_ql_application_company_success',
    'loans_ql_application_tin_success',
    'loans_ql_application_purpose_success',
    'loans_ql_launch_approved',
    'loans_ql_launch_inprogress',
    'loans_ql_disburse_success',
    'loans_launch_approved',
]

# QL Sales Screens (re-borrowing upsell entry before full QL journey)
QL_SALES_SCREEN_EVENTS = [
    'loans_ql_sales_screen_1',
    'loans_ql_sales_screen_2',
    'loans_ql_sales_screen_3',
]

# Loan dashboard & lifecycle
LOAN_DASHBOARD_EVENTS = [
    'loans_dashboard',
    'loans_dashboard_vas',
    'loans_vas_popup',
    'loans_vas_info',
    'loans_proof_of_cover',
    'loans_launch_payments_done',
    'loans_launch_payments_fullypaid',
    'loans_launch_approved',
]

# ============================================================
# FLEXUP (FU)
# ============================================================
FU_SALES_EVENTS = [
    'loans_fu_6andup',
    'loans_fu_sales_screen_1',
    'loans_fu_sales_screen_2',
    'loans_fu_sales_screen_3',
    'loans_fu_sales_screen_accepted',
    'loans_fu_accepted_sales_screen_1',
    'loans_fu_launch',
    'loans_fu_calculator',
    'loans_fu_offer_screen',
]

FU_APPLICATION_EVENTS = [
    'loans_fu_application_summary',
    'loans_fu_address',
    'loans_fu_current_address_1',
    'loans_fu_application_purpose',
    'loans_fu_application_purpose_success',
    'loans_fu_application_terms',
    'loans_fu_application_terms_accepted',
    'loans_fu_application_completed',
]

FU_OFFER_EVENTS = [
    'loans_fu_offer_duedate',
    'loans_fu_offer_duedate_success',
    'loans_fu_offer_installment',
    'loans_fu_offer_installment_success',
    'loans_fu_offer_signalldocs',
    'loans_fu_offer_signature',
    'loans_fu_offer_signatures',
    'loans_fu_offer_signatures_amort',
    'loans_fu_offer_signatures_disclosure',
    'loans_fu_offer_signatures_promissory',
    'loans_fu_offer_amort_signed',
    'loans_fu_offer_disclosure_signed',
    'loans_fu_offer_promissory_signed',
    'loans_fu_offer_success',
    'loans_fu_offer_summary',
    'loans_fu_summary_no_vas',
    'loans_fu_disburse_success',
    'offer_created',
    'offer_used',
    'offer_delete',
    'upsell_free_card_promo',
]

# ============================================================
# SILREL
# ============================================================
SILREL_EVENTS = [
    'loans_silrel',
    'loans_silrel_qr_scan',
    'loans_silrel_address',
    'loans_silrel_occupation',
    'loans_silrel_application_summary',
    'loans_silrel_application_terms',
    'loans_silrel_offer',
    'loans_silrel_offer_paydays',
    'loans_silrel_offer_signalldocs',
    'loans_silrel_offer_signature',
    'loans_silrel_offer_summary',
    'loans_silrel_approved_offer',
    'loans_silrel_confirmation',
    'loans_silrel_confirmation_code',
    'loans_silrel_purchase_success',
    'loans_silrel_disburse_fail',
    'loans_silrel_launch_approved',
    'loans_silrel_offer_dashboard',
]

# SIL full application events
SIL_APPLICATION_EVENTS = [
    'loans_sil_application_launch',
    'loans_sil_application_summary',
    'loans_sil_application_civil',
    'loans_sil_application_dependents',
    'loans_sil_education',
    'loans_sil_contact_reference_1',
    'loans_sil_contact_reference_2',
    'loans_sil_current_address_1',
    'loans_sil_application_income',
    'loans_sil_application_company',
    'loans_sil_application_tin',
    'loans_sil_application_backupmobile',
    'loans_sil_application_terms',
    'loans_sil_application_income_success',
    'loans_sil_application_completed',
    'loans_sil_offer',
    'loans_sil_offer_success',
    'loans_sil_directsettle_summary',
    'loans_sil_directsettle_success',
    'loans_sil_back',
    'sil_back',
]

SIL_QR_EVENTS = [
    'loans_sil_qr_scan_screen',
    'loans_sil_qr_scan',
    'loans_sil_qr_hunt',
    'loans_sil_qr_scan_no_tonik_agent',
]

# ============================================================
# RL — RELENDING
# ============================================================
RL_EVENTS = [
    'loans_rl_sales_screen',
    'loans_rl_sales_screens',
    'loans_rl_sales_screen_accept',
    'loans_rl_application_launch',
    'loans_rl_application_summary',
    'loans_rl_application_purpose',
    'loans_rl_application_purpose_others',
    'loans_rl_application_purpose_success',
    'loans_rl_current_address_1',
    'loans_rl_application_terms',
    'loans_rl_application_terms_accepted',
    'loans_rl_application_completed',
    'loans_rl_offer_summary',
    'loans_rl_offer_summary_success',
    'loans_rl_offer_signatures',
    'loans_rl_offer_signatures_amort',
    'loans_rl_offer_signatures_disclosure',
    'loans_rl_offer_signatures_promissory',
    'loans_rl_offer_amort_signed',
    'loans_rl_offer_success',
    'loans_rl_disburse_success',
    'loans_rl_pr_calculator_vas',
    'loans_rl_summary_no_vas',
    'loans_rl_summary_vas',
    'loans_rl_payhinga_info',
]

# ============================================================
# FL / FLXL / UIL
# ============================================================
FL_EVENTS = [
    'loans_fl_income',
    'loans_fl_calculator',
    'loans_fl_selection',
    'loans_fl_sales_screen_1',
    'loans_fl_sales_screen_2',
    'loans_fl_sales_screen_3',
    'loans_fl_preapproved_offer',
    'loans_fl_skyc',
    'loans_flxl_calculator',
    'loans_flxl_maritalstatus',
    'loans_flxl_disburse_success',
    'loans_acl_counter_cal',
]

UIL_EVENTS = [
    'loans_uil_main',
    'loans_uil_employment_status',
    'loans_uil_occupation',
    'loans_uil_industry',
    'loans_uil_source_of_income',
]

# ============================================================
# PAYMENT EVENTS
# ============================================================
PAYMENT_EVENTS = [
    'loan_payment',
    'loan_payment_confirm',
    'loan_payment_gcash',
    'loan_payment_in_progress',
    'loan_payment_status',
    'loan_payment_success',
    'loan_payment_transaction_details',
    'loan_monthly_repayment_success',
    'loan_disbursement',
]

PAYMENT_REMINDER_EVENTS = [
    'payment_comingup',
    'monthly_due_reminder',
    'due_date',
    'event_loan_payment_coming_up',
    'payment_done',
]

# ============================================================
# COMMUNICATION ENGAGEMENT EVENTS
# ============================================================
EMAIL_EVENTS = [
    'email delivered',
    'email opened',
    'email sent',
    'email dropped',
]

SMS_EVENTS = ['sms sent', 'sms_message_parts']

PUSH_EVENTS = [
    'notification sent ios',
    'notification received android',
    'notification clicked android',
    'moe_push_permission_state_allowed',
    'moe_push_permission_state_blocked',
]

IN_APP_EVENTS = [
    'mobile in-app shown',
    'mobile in-app closed',
    'mobile in-app clicked',
    'mobile in-app auto dismissed',
    'moe_in_app_attempted',
    'moe_flow_trip_conversion',
]

# ============================================================
# FINANCIAL ACTIVITY EVENTS
# ============================================================
TOPUP_EVENTS = [
    'payments_topup_main',
    'payments_topup_interbank',
    'payments_topup_debit_card',
    'payments_topup_online',
    'payments_topup_online_gcash_success',
    'payments_topup_otc',
    'payments_topup_otc_mlhuillier',
    'top_up',
    'top_up_peso_insta',
]

CARD_EVENTS = [
    'payments_cards_main',
    'payments_cards_physical',
    'payments_cards_virtual',
    'payments_cards_virtual_lock',
    'payments_cards_virtual_unlock',
    'payments_cards_phyisical_free',
]

PAYMENT_SEND_EVENTS = [
    'payments_send_main',
    'payments_send_tonik',
    'payments_send_tonik_mobile',
    'payments_send_interbank',
    'payments_send_interbank_instapay',
    'payments_send_interbank_instapay_success',
    'payments_send_interbank_pesonet_success',
    'payment_send',
    'qr_scanning',
    'qr_code_generated',
    'qr_otp',
    'qr_purpose',
    'qr_summary_p2m',
    'qr_summary_p2p',
    'qr_with_amount',
    'qr_without_amount',
]

GCASH_EVENTS = [
    'gcash_linking',
    'gcash_linking_processing_back_to_dashboard',
    'gcash_linking_processing_loaded',
    'gcash_linking_success_back_to_dashboard',
    'gcash_linking_success_loaded',
    'gcash_popup',
]

STASH_EVENTS = [
    'stash_main', 'stash_add', 'stash_add_success',
    'stash_opening', 'stash_opening_select',
    'stash_opening_select_individual', 'stash_opening_start',
    'stash_setup', 'stash_setup_create', 'stash_setup_initial',
    'stash_setup_initial_success', 'stash_setup_review',
    'stash_setup_success_solo', 'stash_setup_terms_checked',
]

# ============================================================
# TSA / ACCOUNT MANAGEMENT EVENTS
# ============================================================
TSA_EVENTS = [
    'tsa_help', 'tsa_help_chatbot', 'tsa_help_faq', 'tsa_help_hotline',
    'tsa_account_history',
    'tsa_history_manage', 'tsa_history_topup',
    'tsa_manage', 'tsa_manage_fees', 'tsa_manage_limits',
    'tsa_profile_additional', 'tsa_profile_request',
    'tsa_profile_account_number', 'tsa_profile_request_success',
    'tsa_profile_additional_update', 'tsa_profile_contact',
    'tsa_profile_personal',
    'dashboard_tile',
    'profile_updateinfo',
    'user_profile',
]

# ============================================================
# HELP & SUPPORT EVENTS
# ============================================================
HELP_EVENTS = ['help', 'tsa_help', 'tsa_help_chatbot', 'tsa_help_faq', 'tsa_help_hotline']
BILLS_PAY_EVENTS = ['pay_bills_splash', 'pay_bills_back']

# ============================================================
# APP OPEN / RE-ENTRY
# ============================================================
APP_OPEN_EVENTS = ['app/site opened', 'app_launch', 'app_login', 'user entered flow']
REENTRY_EVENTS = {'app_launch', 'app_login', 'app/site opened', 'user entered flow'}

# ============================================================
# MOENGAGE SYSTEM EVENTS (exclude from behavioural counts)
# ============================================================
MOE_SYSTEM_EVENTS = [
    'moe_user_merge_event',
    'moe_user_merge_event_new_user',
    'moe_push_permission_state_allowed',
    'moe_push_permission_state_blocked',
]

# ============================================================
# ALL LOAN DISBURSEMENT SIGNALS
# ============================================================
ANY_DISBURSE_EVENTS = [
    'loans_ql_disburse_success',
    'loans_fu_disburse_success',
    'loans_rl_disburse_success',
    'loans_flxl_disburse_success',
    'loans_silrel_purchase_success',
    'loan_disbursement',
]
