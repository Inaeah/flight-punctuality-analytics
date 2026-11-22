# Flight Punctuality Analytics

Data pipeline and analysis of US domestic flight punctuality in Q1 2015 (1.4M flights, 14 airlines, 322 airports).

**On-Time Performance (OTP): 79.66%**, the share of completed flights arriving at most 15 minutes late.

## Key findings

- **February was worst** (OTP 77.5%, cancellations 4.8%), with 75% of cancellations caused by weather.
- **Delays build up through the day**: 90.8% on time at 05:00, ~73% by 18:00–19:00.
- **Northeast hubs rank lowest**: LaGuardia (68.9%), O'Hare (70.5%), JFK and Boston (~72%).
- **Airlines range** from Alaska (86.5%) to Frontier (65.9%).

## How it works

```
CSV (US DOT) → Python ETL → PostgreSQL star schema → reporting views → Looker Studio
```

- **Star schema**: `fact_flights` (one row per flight) with `dim_date`, `dim_airline`, and `dim_airport` (used for both origin and destination).
- **ETL** ([`etl_flights.py`](etl_flights.py)): chunked extract, surrogate key lookup, and an idempotent monthly delete-insert run in a single transaction.
- **Reconciliation**: row counts and OTP are compared between the source and the warehouse after every run. A mismatch makes the job exit with code 1.
- **Data quality** rules are enforced with database constraints. Profiling showed that October uses numeric airport IDs, so scope is limited to Q1.

SQL: [`schema.sql`](sql/schema.sql) · [`reporting.sql`](sql/reporting.sql) · [`analysis.sql`](sql/analysis.sql)

## Run

1. Download the [dataset](https://www.kaggle.com/datasets/usdot/flight-delays) into `data/`.
2. Create `.env` containing `DB_URL=postgresql://user:password@host:5432/dbname`.
3. Run:

```bash
pip install -r requirements.txt
psql "$DB_URL" -f sql/schema.sql
python etl_flights.py            # optional: --months 2 3
psql "$DB_URL" -f sql/reporting.sql
```

## Stack

Python (pandas, psycopg2) · PostgreSQL / Neon · Looker Studio

Data: U.S. DOT Bureau of Transportation Statistics via Kaggle (CC0).
