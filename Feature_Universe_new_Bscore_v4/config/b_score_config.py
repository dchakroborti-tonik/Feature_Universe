"""
Shared B Score configuration.

Run parameters live in b_score_config.yml (the only file you edit per run).
This module reads them and derives every schema / table name used by the notebooks.

Usage in a notebook:
    import sys
    sys.path.append(r"<folder containing this file>")
    import b_score_config as cfg
    from b_score_config import *      # optional: gives you the old variable names
    cfg.show_config()                 # optional: replaces the old print() block
"""

from datetime import datetime
from pathlib import Path

import yaml

_HERE = Path(__file__).resolve().parent
with open(_HERE / "b_score_config.yml", "r", encoding="utf-8") as _f:
    _cfg = yaml.safe_load(_f)

# ── Basics ────────────────────────────────────────────────────────────────────
CURRENT_DATE = datetime.now().strftime("%Y%m%d")

PROJECT_ID = _cfg["project_id"]
GS_BUCKET = _cfg["gs_bucket"]
GS_BUCKET_OLD = _cfg["gs_bucket_old"]
UTIL_PATH = _cfg["util_path"]

schema1 = _cfg["schemas"]["schema1"]  # risk_mart
schema2 = _cfg["schemas"]["schema2"]  # worktable_data_analysis
schema3 = _cfg["schemas"]["schema3"]  # dap_ds_poweruser_playground

tab = _cfg["tab"]
ver = _cfg["ver"]

OBDATE = _cfg["obdate"]
SDATE = _cfg["sdate"]
EDATE = OBDATE

formatted_date = datetime.strptime(SDATE, "%Y-%m-%d").strftime("%Y%m%d")
ob_formatted = datetime.strptime(OBDATE, "%Y-%m-%d").strftime("%Y%m%d")

# ── Source tables (risk_mart) ─────────────────────────────────────────────────
al = f"applied_loans_20230101_{ob_formatted}"
altrans = f"applied_loans_20210701_{ob_formatted}_trans"
nal = f"tsa_onboarded_but_never_applied_loan_20230101_{ob_formatted}"

# ── Step A tables ─────────────────────────────────────────────────────────────
stepa0 = f"{tab}_base_data_{ver}_{formatted_date}_{ob_formatted}"
stepa1 = f"{tab}_loan_application_details_{ver}"
stepa2 = f"{tab}_loan_disbursement_details_{ver}"
stepa3 = f"{tab}_loan_details_{ver}"
stepa4 = f"{tab}_delinquency_{ver}"
stepa5 = f"{tab}_first_applied_loan_data_{ver}"
stepa6 = f"{tab}_last_applied_loan_data_{ver}"
stepa7 = f"{tab}_first_disbursed_loan_data_{ver}"
stepa8 = f"{tab}_last_disbursed_loan_data_{ver}"
stepa9 = f"{tab}_applied_loan_data_{ver}"
stepa10 = f"{tab}_prev_applied_loan_data_{ver}"

# ── Intermediate staging tables ───────────────────────────────────────────────
bscorebasedata = stepa0
bscoresnapshotcustomerdata = f"{tab}_applied_loans_customer_information_data_{ver}"
bscoresnapshotcustomertransactiondata = (
    f"{tab}_applied_loans_customer_transaction_data_{ver}"
)
bscoresnapshotcustomerevent = f"{tab}_applied_loans_customer_event_data_{ver}"
bscoresnapshotcontactability = f"{tab}_applied_loans_contactability_{ver}"
bscoresnapshotcombineddata = f"{tab}_model_applied_loans_{ver}_{ob_formatted}"


def _s2(suffix: str) -> str:
    """schema2.<tab>_<suffix>_<ver>_<obdate>"""
    return f"{schema2}.{tab}_{suffix}_{ver}_{ob_formatted}"


step61 = _s2("vb_results")
step62 = _s2("chatbot")
step63 = _s2("chatbot_fb")
step64 = _s2("chatbot_users")
step65 = _s2("genesys_chat")
step66 = _s2("genesys_email")
step67 = _s2("inbound_voice")
step68 = _s2("airudder_softcollection_calls")
step682 = _s2("cs_vb_cnt_calls_total")
step69 = _s2("reach_enhanced")
step610 = _s2("ars_results")
step611 = _s2("inbound_additional_features")
step612 = _s2("outbound_voice_features")
step6 = _s2("contact_features_extended")
step7 = _s2("contact_genesysdata")
step8 = _s2("loan_level_swathi_table")
step9 = _s2("ptp_details")

step101 = _s2("account_product_portfolio_composition")
step102 = _s2("activity_recency_dormancy")
step103 = _s2("tx_balance_liquidity")
step104 = _s2("bureau_external_scoring")
step105 = _s2("completion_settlement_metrics")
step106 = _s2("conversion_campaign_engagement_events")
step107 = _s2("customer_acquisition_retention")
step108 = _s2("customer_lifecycle_engagement")
step109 = _s2("demographic_verification_enhanced")
step1010 = _s2("deposit_savings_products")
step1011 = _s2("derived_ratio_metrics")
step1012 = _s2("fraud_compliance_indicators")
step1013 = _s2("loan_product_specific_metrics")
step1014 = _s2("loan_staging_milestones")
step10151 = _s2("payment_behaviour_advanced")
step10152 = _s2("payment_behaviour_advanced_2")
step1016 = _s2("revenue_fee_decomposition")
step1017 = _s2("risk_segmentation_categorization")
step1018 = _s2("time_window_cohort_features")
step1019 = _s2("transaction_volume_type_breakdown")
step111 = _s2("collection_call_features")
step112 = _s2("payhinga_features")

step12c = f"{schema2}.PH_City_Province_Event_Mapping_{ver}_{ob_formatted}"  # note: no {tab} prefix
step12d = _s2("ph_shock_feature")
step14 = _s2("prevloan_less_6dpd_details")
step17 = _s2("customer_level_5dpd_details")
step20 = f"{schema3}.{tab}_yuvashri_features_{ver}_{ob_formatted}"  # lives in schema3
step22 = _s2("finscore")
step23 = _s2("trustingsocialscore")
step24 = _s2("bureauinc_score")

# ── Final / feature tables ────────────────────────────────────────────────────
trench3_b_score_model_applied_loans = (
    f"{tab}_model_applied_loans_app_package_{ver}_{ob_formatted}"
)
APP_PACKAGE = f"{tab}_applied_all_dis_loan_app_package_{ver}_{ob_formatted}"
App_Feature_Table = f"{tab}_model_app_features_{ver}_{ob_formatted}"
cic_feature_table = f"{tab}_cic_features_{ver}_{ob_formatted}"
android_devise_score_features = (
    f"{tab}_android_device_score_feature_list_{ver}_{ob_formatted}"
)
ios_device_score_features = f"{tab}_ios_device_score_features_{ver}_{ob_formatted}"
nitin_event_features = _s2("events_feats")
demo_features = f"{schema3}.{tab}_demo_features_{ver}"
stepfinaltab = f"{schema2}.{tab}_model_full_features_v7_{ver}_{ob_formatted}"
finaltab = f"{schema2}.{tab}_model_full_features_model_dataset_{ver}_{ob_formatted}"

# Convenience dict of all step tables (replaces the long hand-written print loop)
STEP_TABLES = {
    k: v for k, v in globals().items() if k.startswith("step") and isinstance(v, str)
}


def show_config():
    """Print the key settings and table names (replaces the print() block in each notebook)."""
    print(f"OBDATE: {OBDATE} | SDATE: {SDATE} | tab: {tab} | ver: {ver}")
    print(f"Project: {PROJECT_ID}")
    print(f"Output table: {schema2}.{bscoresnapshotcombineddata}")
    print(f"Applied Table: {schema1}.{al}")
    print(f"Applied Trans Table: {schema1}.{altrans}")
    print(f"tsa_onboarded_but_never_applied_loan Table: {schema1}.{nal}")
    print(f"App Package Table: {schema2}.{APP_PACKAGE}")
    print(f"App Feature Table: {schema2}.{App_Feature_Table}")
    print(f"CIC Feature Table: {schema2}.{cic_feature_table}")
    print(
        f"Android Device Score Feature Table: {schema2}.{android_devise_score_features}"
    )
    print(f"iOS Device Score Feature Table: {schema2}.{ios_device_score_features}")
    print(f"Events Feature Table: {nitin_event_features}")
    print(f"Demo Feature Table: {demo_features}")
    print(f"Final Feature Table: {stepfinaltab}")
    print(f"Final Table: {finaltab}")
    for name in sorted(STEP_TABLES):
        print(f"{name}: {STEP_TABLES[name]}")
