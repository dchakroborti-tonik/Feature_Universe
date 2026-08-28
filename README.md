# B-Score Feature Universe Training Config

End-to-end feature engineering pipeline for Tonik Bank's **B-Score** (credit risk) model. This repository manages configuration, BigQuery data extraction, feature computation across multiple data domains, and local DuckDB storage for large-scale datasets.

---

## Repository Structure

```
Feature_Universe_Training_Config/
├── config.txt                          # Central run configuration (GCP, dates, table names)
├── apply_config.py                     # Propagates config.txt into all notebooks
├── requirements.txt                    # Python dependencies
│
├── Part1_Applied_Trans_Table_configured.ipynb   # Step 1: Applied loans transactions table
├── Part2_DC_Steps_configured.ipynb              # Step 2: Core DC feature engineering steps
├── Part3_Partners_Steps_configured.ipynb        # Step 3: Partner feature orchestration
├── Part4_Final_Steps_configured.ipynb           # Step 4: Final join, dedup, and output table
├── B_Score_Feature_Universe_Training_Template.ipynb  # Master template notebook
│
├── Events_Features/                    # MoEngage app-event behavioral features
│   ├── README.md
│   ├── main.py                         # Production batch runner
│   ├── bscore_event_features_v20260818.ipynb
│   └── B_Score_Events_FE_codebase_v20260818/   # Feature computation package
│
├── Partners/                           # Partner data source features
│   ├── cash_demo_feature_creation_configured.ipynb
│   ├── cic_features_20260706_configured.ipynb
│   ├── device_score_android_feature_creation_configured.ipynb
│   ├── ios_device_score_features_configured.ipynb
│   ├── model_app_features_configured.ipynb
│   └── main.py
│
├── Support_Data/                       # Reference/lookup files
│   ├── PH_City_Province_Event_Mapping.xlsx
│   ├── mobile_device_with_gsm.csv
│   ├── rename_columns.xlsx
│   └── remove_duplicate_feature.xlsx
│
└── Utils/                              # BigQuery-to-DuckDB extraction scripts
    ├── bq_to_duckdb.py
    ├── bq_snapshot_to_duckdb.py
    └── bq_fast_download_updated_auto_chunked.py
```

> **Gitignored (large files):** `data/`, `duckdb/`, `parquet_chunks/`, `.venv/`, output CSVs.

---

## Pipeline Overview

The pipeline runs in four sequential parts, preceded by configuration injection:

```
config.txt
    │
    ▼ apply_config.py
    │
    ├── Part 1: Applied Loans Transactions Table (BigQuery)
    ├── Part 2: DC Feature Engineering Steps (step6x → step1019)
    ├── Part 3: Partner Features (CIC, Device Score, App Package, Cash Demo)
    ├── Part 4: Final Join, Dedup, Rename → Model-Ready BQ Table
    │
    └── Events_Features/main.py  ──► b_score_events_output_v*.csv  (runs independently)
```

Each Part notebook reads from and writes intermediate staging tables back to the BigQuery `worktable_data_analysis` schema.

---

## Configuration

All run parameters live in **`config.txt`** (written in Python syntax). Edit this file before each scoring run, then propagate changes:

```bash
python apply_config.py
```

Key parameters:

| Variable | Description | Example |
|---|---|---|
| `ver` | Model version tag | `'v26'` |
| `OBDATE` | Observation date | `'2026-08-20'` |
| `SDATE` | Training window start | `'2023-01-01'` |
| `EDATE` | Training window end | `'2026-08-16'` |
| `project_id` | GCP project | `'tonik-...'` |
| `step6x … step24` | Intermediate BQ staging table names | auto-named per `ver` |

`apply_config.py` injects the contents of `config.txt` into the first config cell (sentinel: `# B Score model configuration`) of every `_configured.ipynb` notebook across root and Partners.

---

## Setup

### Prerequisites

- Python 3.13+
- GCP credentials configured (`gcloud auth application-default login`)
- Access to Tonik BigQuery project and GCS bucket

### Install dependencies

```bash
python -m venv .venv
.venv\Scripts\activate       # Windows
pip install -r requirements.txt
```

### Key dependencies

| Package | Purpose |
|---|---|
| `google-cloud-bigquery` | BigQuery read/write |
| `google-cloud-storage` | GCS transfer for large table exports |
| `duckdb` | Local columnar store (avoids repeated BQ billing) |
| `pyarrow` | Parquet I/O |
| `pandas`, `numpy`, `scipy` | Data manipulation and statistics |
| `catboost` | Model training (downstream) |
| `openpyxl`, `fuzzywuzzy` | Support data parsing |

---

## Running the Pipeline

### 1. Update configuration

Edit `config.txt` (update `ver`, `OBDATE`, `SDATE`, `EDATE`, table names), then:

```bash
python apply_config.py
```

### 2. Execute notebooks in order

Run Parts 1–4 sequentially in Jupyter or VS Code:

```
Part1_Applied_Trans_Table_configured.ipynb
Part2_DC_Steps_configured.ipynb
Part3_Partners_Steps_configured.ipynb
Part4_Final_Steps_configured.ipynb
```

### 3. Run event features (independent)

```bash
cd Events_Features
python main.py
```

This reads from BigQuery (`bscore_moenagage_events_all_*`), converts UTC to Manila time, computes 7-day rolling behavioral features per `(customer_id, observation_datetime)` pair, and writes output to CSV in batches of 500 with checkpoint/resume support.

---

## Feature Domains

| Domain | Source | Notebook / Script |
|---|---|---|
| Applied Loans Transactions | BigQuery `risk_mart` | Part 1 |
| DC Core Features (step6x–step1019) | BigQuery staging tables | Part 2 |
| CIC Credit Bureau | BigQuery / CIC source | `Partners/cic_features_*.ipynb` |
| Cash Demo | BigQuery | `Partners/cash_demo_*.ipynb` |
| Device Score (Android) | BigQuery | `Partners/device_score_android_*.ipynb` |
| Device Score (iOS) | BigQuery | `Partners/ios_device_score_*.ipynb` |
| App Package / Loan App | BigQuery | `Partners/model_app_features_*.ipynb` |
| MoEngage App Events | BigQuery `bscore_moenagage_events_*` | `Events_Features/main.py` |

### Event Feature Sub-domains (`Events_Features/B_Score_Events_FE_codebase_v20260818/`)

| Module | Features |
|---|---|
| `features_base.py` | Event counts, recency |
| `features_session.py` | App session and engagement |
| `features_financial.py` | Financial transactions |
| `features_payment.py` | Payment events |
| `features_loan_app.py` | Loan application journey |
| `features_fl.py` | Flexi Loan events |
| `features_rl.py` | Revolving Loan events |
| `features_flexup.py` | FlexUp product events |
| `features_silrel.py` | SIL/REL product events |
| `features_comms.py` | Communication / notification events |
| `features_support.py` | Customer support interactions |

---

## BigQuery Data Extraction Utilities (`Utils/`)

For local development, large BQ tables can be pulled into a local DuckDB to avoid repeated billing:

| Script | Use Case |
|---|---|
| `bq_to_duckdb.py` | Export BQ table → GCS Parquet → parallel download → DuckDB (optimized for 100 GB+) |
| `bq_snapshot_to_duckdb.py` | Same flow, works from BQ snapshots |
| `bq_fast_download_updated_auto_chunked.py` | Auto-chunks large BQ queries by key, parallelizes downloads |

Local DuckDB is stored at `duckdb/my_database.db` (gitignored).

---

## Support Data (`Support_Data/`)

| File | Purpose |
|---|---|
| `PH_City_Province_Event_Mapping.xlsx` | Philippines city-to-province mapping for geographic features |
| `mobile_device_with_gsm.csv` | Device lookup table with GSM flags |
| `rename_columns.xlsx` / `rename_columns_2.xlsx` | Column rename mappings applied at final step |
| `Prakatheesh_rename_columns.xlsx` | Additional rename mapping |
| `remove_duplicate_feature.xlsx` / `Additional_remove_duplicates.xlsx` | Feature columns to drop before model training |

---

## Versioning Convention

- **Model version** is controlled by `ver` in `config.txt` (e.g., `v26`).
- All intermediate BigQuery staging table names embed the version tag automatically.
- Event feature codebase versions are tracked by date suffix (e.g., `v20260818`). Older snapshots (e.g., `v20260428`) are retained in subdirectories for rollback.
- Notebooks suffixed `_configured` are generated outputs — do not edit them directly; edit the source template and re-run `apply_config.py`.

---

## Author

**Dwaipayan Chakroborti** — dchakroborti@tonikbank.com  
Tonik Bank Data Science / Risk Modelling Team
