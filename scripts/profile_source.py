"""
Profile the raw source CSVs before building the pipeline.

Checks volume, nulls, duplicates, referential integrity against the
airline/airport master files, and computes a baseline on-time performance
(OTP) figure that the loaded warehouse must reproduce exactly.

Usage:
    python scripts/profile_source.py
"""
from pathlib import Path

import pandas as pd

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
MONTHS_IN_SCOPE = [1, 2, 3]  # Jan-Mar 2015

FLIGHT_COLS = [
    "YEAR", "MONTH", "DAY", "AIRLINE", "FLIGHT_NUMBER",
    "ORIGIN_AIRPORT", "DESTINATION_AIRPORT", "SCHEDULED_DEPARTURE",
    "DEPARTURE_DELAY", "ARRIVAL_DELAY", "DISTANCE",
    "DIVERTED", "CANCELLED", "CANCELLATION_REASON",
]
# Natural key: identifies one scheduled flight
NATURAL_KEY = [
    "YEAR", "MONTH", "DAY", "AIRLINE", "FLIGHT_NUMBER",
    "ORIGIN_AIRPORT", "SCHEDULED_DEPARTURE",
]


def section(title: str) -> None:
    print(f"\n=== {title} ===")


def load_sources():
    # Airport codes and HHMM times must stay strings:
    # numeric parsing would drop leading zeros ("0005" -> 5).
    flights = pd.read_csv(
        DATA_DIR / "flights.csv",
        usecols=FLIGHT_COLS,
        dtype={
            "ORIGIN_AIRPORT": str,
            "DESTINATION_AIRPORT": str,
            "SCHEDULED_DEPARTURE": str,
        },
    )
    airlines = pd.read_csv(DATA_DIR / "airlines.csv")
    airports = pd.read_csv(DATA_DIR / "airports.csv")
    return flights, airlines, airports


def profile_full_year(flights: pd.DataFrame) -> None:
    section("Full year")
    print(f"Total rows: {len(flights):,}")
    print("Rows per month:")
    print(flights.groupby("MONTH").size().to_string())

    # Known issue: some months use numeric airport IDs instead of IATA codes
    numeric = flights["ORIGIN_AIRPORT"].str.isdigit()
    print("Rows with numeric airport codes per month:")
    print(flights[numeric].groupby("MONTH").size().to_string())


def profile_scope(q: pd.DataFrame, airlines: pd.DataFrame, airports: pd.DataFrame) -> None:
    section(f"In scope (months {MONTHS_IN_SCOPE}): {len(q):,} rows")

    print("Nulls per column:")
    nulls = q.isna().sum()
    print(nulls[nulls > 0].to_string())

    cancelled = int(q["CANCELLED"].sum())
    diverted = int(q["DIVERTED"].sum())
    print(f"\nCancelled: {cancelled:,}  Diverted: {diverted:,}")
    # ARRIVAL_DELAY is expected to be null exactly for cancelled + diverted flights
    print(f"ARRIVAL_DELAY nulls == cancelled + diverted? "
          f"{nulls['ARRIVAL_DELAY'] == cancelled + diverted}")

    print("\nCancellation reason (A=carrier, B=weather, C=NAS, D=security):")
    print(q["CANCELLATION_REASON"].value_counts(dropna=False).to_string())

    print(f"\nDuplicate natural keys: {q.duplicated(NATURAL_KEY).sum():,}")

    # Referential integrity: every code must exist in its master file
    airport_codes = set(airports["IATA_CODE"])
    airline_codes = set(airlines["IATA_CODE"])
    print(f"Orphan origin airports: {(~q['ORIGIN_AIRPORT'].isin(airport_codes)).sum():,}")
    print(f"Orphan destination airports: {(~q['DESTINATION_AIRPORT'].isin(airport_codes)).sum():,}")
    print(f"Orphan airlines: {(~q['AIRLINE'].isin(airline_codes)).sum():,}")

    sched = q["SCHEDULED_DEPARTURE"]
    print(f"SCHEDULED_DEPARTURE range: {sched.min()}-{sched.max()}, "
          f"lengths: {sched.str.len().value_counts().to_dict()}")


def baseline_otp(q: pd.DataFrame) -> None:
    section("Baseline OTP")
    # OTP = share of completed flights (not cancelled, not diverted)
    # arriving no more than 15 minutes after schedule
    completed = q[(q["CANCELLED"] == 0) & (q["DIVERTED"] == 0)]
    otp = (completed["ARRIVAL_DELAY"] <= 15).mean() * 100
    print(f"Completed flights: {len(completed):,}")
    print(f"OTP: {otp:.2f}%  <- warehouse must reproduce this")


def profile_airports(airports: pd.DataFrame) -> None:
    section("airports.csv")
    print(f"Rows: {len(airports):,}")
    nulls = airports.isna().sum()
    print("Nulls:")
    print(nulls[nulls > 0].to_string() if nulls.any() else "none")


def main() -> None:
    flights, airlines, airports = load_sources()
    profile_full_year(flights)
    q = flights[flights["MONTH"].isin(MONTHS_IN_SCOPE)]
    profile_scope(q, airlines, airports)
    baseline_otp(q)
    profile_airports(airports)


if __name__ == "__main__":
    main()
