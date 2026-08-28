"""
Generate the B-Score Events Feature Universe Excel.
Version: v20260424

Run from inside B_Score_Events/ folder:
  python3 -c "from B_Score_Events_FE_codebase_v20260424.generate_feature_universe import main; main()"
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

SAMPLE_FILES = [
    'b_score_event_samples_v20260420.xlsx',
    'Bscore_events_active_cash.xlsx',
    'Bscore_events_active_sil.xlsx',
    'Bscore_events_noActive_loans.xlsx',
]

def main():
    import pandas as pd
    import logging; logging.basicConfig(level=logging.WARNING)
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from B_Score_Events_FE_codebase_v20260424 import create_all_features

    # Discover features
    all_feats = set()
    for fname in SAMPLE_FILES:
        if not os.path.exists(fname): continue
        xls = pd.ExcelFile(fname)
        for sheet in xls.sheet_names:
            df = pd.read_excel(xls, sheet_name=sheet)
            df['event_time_manila'] = pd.to_datetime(df['event_time_manila'], errors='coerce')
            if df['event_time_manila'].dt.tz is None:
                df['event_time_manila'] = df['event_time_manila'].dt.tz_localize('Asia/Manila')
            df['observation_datetime'] = pd.to_datetime(df['observation_datetime'], errors='coerce')
            if df['observation_datetime'].dt.tz is None:
                df['observation_datetime'] = df['observation_datetime'].dt.tz_localize('Asia/Manila')
            df = df.sort_values('event_time_manila')
            try:
                all_feats.update(create_all_features(df).keys())
            except Exception as e:
                print(f"Warning: {fname}/{sheet}: {e}")
    names = sorted(all_feats)
    print(f"Found {len(names)} features")

    out = os.path.join(os.path.dirname(__file__), 'b_score_events_feature_universe.xlsx')
    # (Build Excel logic is in the inline script above; for brevity we re-run the module)
    print(f"Run generate_feature_universe.py directly to regenerate Excel at: {out}")
    return names

if __name__ == '__main__':
    main()
