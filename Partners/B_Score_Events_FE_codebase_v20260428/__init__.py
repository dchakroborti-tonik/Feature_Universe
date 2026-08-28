"""
B-Score Events Feature Engineering Package
Version: v20260428

Changes from v20260424:
  - Source changed from Parquet + separate BQ query to single BQ table:
      risk_mart.moenagage_events_all_disb_20240901_20260422
  - customer_id (snake_case) replaces customerId throughout all modules
  - event_time_manila is always tz-naive (UTC->Manila conversion done in main.py)
  - observation_datetime is always tz-naive (Manila date + 23:59:00, set in main.py)
  - engine.create_all_features: removed tz_localize block that would crash on
    already-tz-naive event_time_manila
  - helpers.get_anchor_time: removed tz_localize on already-tz-naive observation_datetime
  - helpers.get_window_dfs: tz-naive arithmetic consistent throughout
  - config.DEDUP_COLUMNS: 'customerId' -> 'customer_id'
  - engine.run_feature_engineering: 'customerId' -> 'customer_id' (legacy helper)
  - Features computed at digitalLoanAccountId level (one row per loan in output)

Modules:
    config              - Event lists, windows, thresholds (347 unique event types)
    helpers             - Cleaning, windowing, sessions
    features_base       - Base aggregate (logins, entropy, rating, exited flow)
    features_loan_app   - Full QL funnel + SIL + disbursement composite
    features_flexup     - FlexUp sales -> application -> disburse
    features_silrel     - SILRel in-store relending journey
    features_rl         - Relending (RL) product journey
    features_fl         - FlexLoan / FlexXL / UIL income screening
    features_payment    - Payment behaviour, reminders, success rate
    features_comms      - Email, SMS, push (clicked), in-app (clicked/dismissed)
    features_financial  - Topup, send, QR, GCash, stash, TSA management
    features_support    - Help chatbot, FAQ, hotline, QL back
    features_session    - Session patterns, time-of-day, gaps
    engine              - Orchestrator
    generate_feature_universe - Feature universe Excel
    main                - Production batch runner
"""

from .engine import create_all_features, run_feature_engineering
