# B-Score Events Feature Engineering v20260818

This version computes features at this grain:

```text
(customer_id, observation_datetime)
```

`digitalLoanAccountId` is intentionally not read from the source table, not used for grouping, and not written to the output.

## Folder Contents

- `main.py` - production batch runner for v20260818.
- `B_Score_Events_FE_codebase_v20260818/` - copied feature package for this version.
- `b_score_events_output_v20260818.csv` - output file created by the runner.
- `b_score_events_checkpoint_v20260818.txt` - checkpoint file created by the runner.

## Flow

1. Load the full BigQuery source table without `digitalLoanAccountId`.
2. Convert `event_time` from UTC to tz-naive Manila time as `event_time_manila`.
3. Convert `Observation_date` to `observation_datetime = Observation_date + 23:59:00`.
4. Build one metadata row per `(customer_id, observation_datetime)`.
5. Group events by `(customer_id, observation_datetime)`.
6. For each customer-observation pair:
   - fetch that pair's events,
   - filter to `[observation_datetime - 168 hours, observation_datetime]`,
   - sort by `event_time_manila`,
   - attach the pair's `observation_datetime`,
   - call `create_all_features(window_df)`.
7. Write one output row per customer-observation pair.

## Checkpoint Grain

The checkpoint key is:

```text
customer_id|YYYY-MM-DD HH:MM:SS
```

This avoids skipping later observation dates for the same customer.

## Dedup Grain

In `B_Score_Events_FE_codebase_v20260818/config.py`, `DEDUP_COLUMNS` is:

```python
[
    'customer_id',
    'moengage_user_id',
    'event_time_manila',
    'event_name',
    'observation_datetime',
]
```

## Run

From this folder:

```powershell
python main.py
```
