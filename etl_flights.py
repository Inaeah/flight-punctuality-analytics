"""
ETL: 2015 US flight data (CSV) -> PostgreSQL star schema.

Usage:
    python etl_flights.py
"""
import logging
import os
import sys
from datetime import date
from pathlib import Path

import psycopg2
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
LOG_FILE = BASE_DIR / "etl.log"

DATE_DIM_START = date(2015, 1, 1)
DATE_DIM_END = date(2015, 12, 31)

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

def main() -> None:
    setup_logging()
    log.info("ETL started")
    conn = get_connection()
    try:
        load_dimensions(conn)
    except Exception:
        log.exception("ETL failed")
        raise
    finally:
        conn.close()
    log.info("ETL finished")


if __name__ == "__main__":
    main()
