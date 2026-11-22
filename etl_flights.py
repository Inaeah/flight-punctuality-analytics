"""
ETL: 2015 US flight data (CSV) -> PostgreSQL star schema.

Usage:
    python etl_flights.py                # default months: 1 2 3
    python etl_flights.py --months 2 3   # reload only Feb and Mar

Exit code is 1 if the ETL fails or reconciliation finds a mismatch.
"""
import argparse
import io
import logging
import os
import sys
from datetime import date
from pathlib import Path

import pandas as pd
import psycopg2
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
LOG_FILE = BASE_DIR / "etl.log"

DATE_DIM_START = date(2015, 1, 1)
DATE_DIM_END = date(2015, 12, 31)

DEFAULT_MONTHS = [1, 2, 3]
CHUNK_SIZE = 500_000

SOURCE_COLS = [
    "YEAR", "MONTH", "DAY", "AIRLINE", "FLIGHT_NUMBER",
    "ORIGIN_AIRPORT", "DESTINATION_AIRPORT", "SCHEDULED_DEPARTURE",
    "DEPARTURE_DELAY", "ARRIVAL_DELAY", "DISTANCE",
    "DIVERTED", "CANCELLED", "CANCELLATION_REASON",
]
FACT_COLS = [
    "date_key", "airline_key", "origin_airport_key", "dest_airport_key",
    "flight_number", "scheduled_departure",
    "departure_delay_min", "arrival_delay_min", "distance_miles",
    "is_cancelled", "is_diverted", "cancellation_reason", "is_delayed_15",
]
NATURAL_KEY = [
    "date_key", "airline_key", "flight_number",
    "origin_airport_key", "scheduled_departure",
]

log = logging.getLogger("etl_flights")


def setup_logging() -> None:
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(message)s")
    log.setLevel(logging.INFO)
    for handler in (logging.StreamHandler(sys.stdout),
                    logging.FileHandler(LOG_FILE, encoding="utf-8")):
        handler.setFormatter(fmt)
        log.addHandler(handler)


def get_connection():
    load_dotenv(BASE_DIR / ".env")
    db_url = os.getenv("DB_URL")
    if not db_url:
        raise RuntimeError("DB_URL is not set. Create a .env file (see README).")
    return psycopg2.connect(db_url)


def copy_csv(cur, csv_path: Path, table: str) -> None:
    # COPY is much faster than row-by-row INSERTs
    with open(csv_path, encoding="utf-8") as f:
        cur.copy_expert(f"COPY {table} FROM STDIN WITH (FORMAT csv, HEADER true)", f)


def load_dim_airline(cur) -> None:
    cur.execute("TRUNCATE staging.airlines")
    copy_csv(cur, DATA_DIR / "airlines.csv", "staging.airlines")
    cur.execute("""
        INSERT INTO dw.dim_airline (airline_code, airline_name)
        SELECT TRIM(iata_code), TRIM(airline)
        FROM staging.airlines
        ON CONFLICT (airline_code) DO NOTHING
    """)
    log.info("dim_airline: %d new rows", cur.rowcount)


def load_dim_airport(cur) -> None:
    cur.execute("TRUNCATE staging.airports")
    copy_csv(cur, DATA_DIR / "airports.csv", "staging.airports")
    cur.execute("""
        INSERT INTO dw.dim_airport
            (airport_code, airport_name, city, state, country, latitude, longitude)
        SELECT TRIM(iata_code), TRIM(airport), TRIM(city), TRIM(state),
               TRIM(country), latitude, longitude
        FROM staging.airports
        ON CONFLICT (airport_code) DO NOTHING
    """)
    log.info("dim_airport: %d new rows", cur.rowcount)

    cur.execute("SELECT COUNT(*) FROM dw.dim_airport WHERE latitude IS NULL")
    missing = cur.fetchone()[0]
    if missing:
        log.warning("dim_airport: %d airports have no coordinates", missing)


def load_dim_date(cur) -> None:
    cur.execute("""
        INSERT INTO dw.dim_date
            (date_key, full_date, year, quarter, month, month_name,
             day_of_month, day_of_week, day_name)
        SELECT TO_CHAR(d, 'YYYYMMDD')::INT,
               d::DATE,
               EXTRACT(YEAR    FROM d),
               EXTRACT(QUARTER FROM d),
               EXTRACT(MONTH   FROM d),
               TO_CHAR(d, 'FMMonth'),
               EXTRACT(DAY     FROM d),
               EXTRACT(ISODOW  FROM d),
               TO_CHAR(d, 'FMDay')
        FROM generate_series(%s::DATE, %s::DATE, INTERVAL '1 day') AS d
        ON CONFLICT (date_key) DO NOTHING
    """, (DATE_DIM_START, DATE_DIM_END))
    log.info("dim_date: %d new rows", cur.rowcount)


def load_dimensions(conn) -> None:
    # single transaction: all dimensions load, or none do
    with conn, conn.cursor() as cur:
        load_dim_airline(cur)
        load_dim_airport(cur)
        load_dim_date(cur)


def get_key_maps(conn) -> dict:
    # natural key -> surrogate key, used to translate codes in the fact rows
    with conn.cursor() as cur:
        cur.execute("SELECT airline_code, airline_key FROM dw.dim_airline")
        airlines = dict(cur.fetchall())
        cur.execute("SELECT airport_code, airport_key FROM dw.dim_airport")
        airports = dict(cur.fetchall())
    return {"airline": airlines, "airport": airports}


def extract_flights(months: list[int]):
    # read in chunks so the 565 MB file never sits in memory at once
    reader = pd.read_csv(
        DATA_DIR / "flights.csv",
        usecols=SOURCE_COLS,
        dtype={"ORIGIN_AIRPORT": str, "DESTINATION_AIRPORT": str,
               "SCHEDULED_DEPARTURE": str, "CANCELLATION_REASON": str},
        chunksize=CHUNK_SIZE,
    )
    for chunk in reader:
        chunk = chunk[chunk["MONTH"].isin(months)]
        if not chunk.empty:
            yield chunk


def transform_flights(src: pd.DataFrame, key_maps: dict) -> pd.DataFrame:
    out = pd.DataFrame(index=src.index)
    out["month"] = src["MONTH"]
    out["date_key"] = src["YEAR"] * 10000 + src["MONTH"] * 100 + src["DAY"]
    out["airline_key"] = src["AIRLINE"].map(key_maps["airline"])
    out["origin_airport_key"] = src["ORIGIN_AIRPORT"].map(key_maps["airport"])
    out["dest_airport_key"] = src["DESTINATION_AIRPORT"].map(key_maps["airport"])
    out["flight_number"] = src["FLIGHT_NUMBER"]
    hhmm = src["SCHEDULED_DEPARTURE"]
    out["scheduled_departure"] = hhmm.str[:2] + ":" + hhmm.str[2:]

    # nullable Int16 keeps NULL delays as NULL instead of turning them into floats
    out["departure_delay_min"] = src["DEPARTURE_DELAY"].astype("Int16")
    out["arrival_delay_min"] = src["ARRIVAL_DELAY"].astype("Int16")
    out["distance_miles"] = src["DISTANCE"]

    out["is_cancelled"] = src["CANCELLED"] == 1
    out["is_diverted"] = src["DIVERTED"] == 1
    out["cancellation_reason"] = src["CANCELLATION_REASON"]

    completed = ~(out["is_cancelled"] | out["is_diverted"])
    out["is_delayed_15"] = (out["arrival_delay_min"] > 15).astype("boolean")
    out.loc[~completed, "is_delayed_15"] = pd.NA
    return out


def drop_orphans(df: pd.DataFrame) -> pd.DataFrame:
    keys = ["airline_key", "origin_airport_key", "dest_airport_key"]
    orphan = df[keys].isna().any(axis=1)
    if orphan.any():
        log.warning("dropped %d rows with codes missing from dimensions", orphan.sum())
    df = df[~orphan].copy()
    df[keys] = df[keys].astype("int16")
    return df


def load_month(conn, month: int, df: pd.DataFrame) -> None:
    start_key = 2015 * 10000 + month * 100
    buf = io.StringIO()
    df[FACT_COLS].to_csv(buf, index=False, header=False)
    buf.seek(0)

    # delete-insert in one transaction: re-running a month replaces it, never duplicates it
    with conn, conn.cursor() as cur:
        cur.execute(
            "DELETE FROM dw.fact_flights WHERE date_key BETWEEN %s AND %s",
            (start_key + 1, start_key + 31),
        )
        deleted = cur.rowcount
        cur.copy_expert(
            f"COPY dw.fact_flights ({', '.join(FACT_COLS)}) FROM STDIN WITH (FORMAT csv)",
            buf,
        )
        log.info("fact_flights month %02d: deleted %d, inserted %d",
                 month, deleted, cur.rowcount)


def source_stats(src: pd.DataFrame) -> pd.DataFrame:
    # computed on the raw CSV rows, independently of the transform logic
    completed = (src["CANCELLED"] == 0) & (src["DIVERTED"] == 0)
    on_time = completed & (src["ARRIVAL_DELAY"] <= 15)
    return pd.DataFrame({
        "month": src["MONTH"],
        "rows": 1,
        "completed": completed.astype(int),
        "on_time": on_time.astype(int),
    }).groupby("month").sum()


def load_facts(conn, months: list[int]) -> pd.DataFrame:
    key_maps = get_key_maps(conn)
    parts, stats = [], []
    for chunk in extract_flights(months):
        stats.append(source_stats(chunk))
        parts.append(transform_flights(chunk, key_maps))
    flights = drop_orphans(pd.concat(parts))
    log.info("extracted %d flight rows for months %s", len(flights), months)

    for month, df in flights.groupby("month"):
        # dedup per month, since duplicates can sit in different chunks
        before = len(df)
        df = df.drop_duplicates(NATURAL_KEY, keep="last")
        if len(df) < before:
            log.warning("month %02d: dropped %d duplicate rows", month, before - len(df))
        load_month(conn, month, df)

    # a chunk can hold the end of one month and the start of the next
    return pd.concat(stats).groupby(level=0).sum()


def reconcile(conn, source: pd.DataFrame, months: list[int]) -> bool:
    with conn.cursor() as cur:
        cur.execute("""
            SELECT d.month,
                   COUNT(*),
                   COUNT(f.is_delayed_15),
                   COUNT(*) FILTER (WHERE NOT f.is_delayed_15)
            FROM dw.fact_flights f
            JOIN dw.dim_date d USING (date_key)
            WHERE d.month = ANY(%s)
            GROUP BY d.month
        """, (months,))
        warehouse = pd.DataFrame(
            cur.fetchall(), columns=["month", "rows", "completed", "on_time"]
        ).set_index("month")

    ok = True
    for month in months:
        src = source.loc[month] if month in source.index else pd.Series(0, index=warehouse.columns)
        dw = warehouse.loc[month] if month in warehouse.index else pd.Series(0, index=warehouse.columns)
        src_otp = 100 * src["on_time"] / src["completed"] if src["completed"] else 0
        dw_otp = 100 * dw["on_time"] / dw["completed"] if dw["completed"] else 0
        matched = (src == dw).all()
        ok &= matched
        log.log(
            logging.INFO if matched else logging.ERROR,
            "reconcile month %02d: rows %d vs %d, OTP %.2f%% vs %.2f%% (source vs warehouse) %s",
            month, src["rows"], dw["rows"], src_otp, dw_otp, "OK" if matched else "MISMATCH",
        )
    return ok


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument(
        "--months", type=int, nargs="+", default=DEFAULT_MONTHS,
        choices=range(1, 13), metavar="M", help="months of 2015 to load (1-12)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    months = sorted(set(args.months))
    setup_logging()
    log.info("ETL started, months %s", months)
    conn = get_connection()
    try:
        load_dimensions(conn)
        source = load_facts(conn, months)
        ok = reconcile(conn, source, months)
    except Exception:
        log.exception("ETL failed")
        raise
    finally:
        conn.close()

    if not ok:
        log.error("ETL finished with reconciliation errors")
        sys.exit(1)
    log.info("ETL finished")


if __name__ == "__main__":
    main()
