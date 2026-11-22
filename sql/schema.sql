CREATE SCHEMA IF NOT EXISTS staging;
CREATE SCHEMA IF NOT EXISTS dw;

-- Staging: raw master data, column names close to the source CSVs
CREATE TABLE IF NOT EXISTS staging.airlines (
    iata_code    TEXT,
    airline      TEXT
);

CREATE TABLE IF NOT EXISTS staging.airports (
    iata_code    TEXT,
    airport      TEXT,
    city         TEXT,
    state        TEXT,
    country      TEXT,
    latitude     NUMERIC(9,5),
    longitude    NUMERIC(9,5)
);

-- dim_date: one row per calendar day, key = YYYYMMDD
CREATE TABLE IF NOT EXISTS dw.dim_date (
    date_key       INTEGER     PRIMARY KEY,          -- e.g. 20150131
    full_date      DATE        NOT NULL UNIQUE,
    year           SMALLINT    NOT NULL,
    quarter        SMALLINT    NOT NULL CHECK (quarter BETWEEN 1 AND 4),
    month          SMALLINT    NOT NULL CHECK (month BETWEEN 1 AND 12),
    month_name     TEXT        NOT NULL,
    day_of_month   SMALLINT    NOT NULL,
    day_of_week    SMALLINT    NOT NULL CHECK (day_of_week BETWEEN 1 AND 7), -- ISO: 1 = Monday
    day_name       TEXT        NOT NULL
);

-- dim_airline: surrogate key + natural key (IATA code)
CREATE TABLE IF NOT EXISTS dw.dim_airline (
    airline_key    SMALLINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    airline_code   CHAR(2)     NOT NULL UNIQUE,
    airline_name   TEXT        NOT NULL
);

-- dim_airport: used twice by origin and destination
CREATE TABLE IF NOT EXISTS dw.dim_airport (
    airport_key    SMALLINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    airport_code   CHAR(3)     NOT NULL UNIQUE,
    airport_name   TEXT        NOT NULL,
    city           TEXT,
    state          CHAR(2),
    country        TEXT,
    latitude       NUMERIC(9,5),              
    longitude      NUMERIC(9,5)
);

-- fact_flights
CREATE TABLE IF NOT EXISTS dw.fact_flights (
    flight_key             BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    date_key               INTEGER   NOT NULL REFERENCES dw.dim_date (date_key),
    airline_key            SMALLINT  NOT NULL REFERENCES dw.dim_airline (airline_key),
    origin_airport_key     SMALLINT  NOT NULL REFERENCES dw.dim_airport (airport_key),
    dest_airport_key       SMALLINT  NOT NULL REFERENCES dw.dim_airport (airport_key),
    flight_number          SMALLINT  NOT NULL,
    scheduled_departure    TIME      NOT NULL,

    -- measures (NULL when the flight never departed / arrived)
    departure_delay_min    SMALLINT,
    arrival_delay_min      SMALLINT,
    distance_miles         SMALLINT  NOT NULL,

    -- flags
    is_cancelled           BOOLEAN   NOT NULL,
    is_diverted            BOOLEAN   NOT NULL,
    cancellation_reason    CHAR(1)   CHECK (cancellation_reason IN ('A','B','C','D')),
    is_delayed_15          BOOLEAN,  -- arrival > 15 min late; NULL if cancelled/diverted

    -- one row per scheduled flight (natural key)
    CONSTRAINT uq_fact_flights_natural
        UNIQUE (date_key, airline_key, flight_number, origin_airport_key, scheduled_departure),

    -- business rules found during source profiling
    CONSTRAINT ck_reason_only_if_cancelled
        CHECK ((is_cancelled AND cancellation_reason IS NOT NULL)
            OR (NOT is_cancelled AND cancellation_reason IS NULL)),
    CONSTRAINT ck_delayed_flag_only_if_completed
        CHECK ((is_cancelled OR is_diverted) = (is_delayed_15 IS NULL))
);