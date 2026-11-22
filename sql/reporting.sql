CREATE SCHEMA IF NOT EXISTS reporting;

CREATE OR REPLACE VIEW reporting.v_flights AS
SELECT d.full_date,
       d.month,
       d.month_name,
       d.day_of_week,
       d.day_name,
       a.airline_code,
       a.airline_name,
       o.airport_code                                   AS origin_code,
       o.airport_name                                   AS origin_airport,
       o.city                                           AS origin_city,
       o.state                                          AS origin_state,
       o.latitude || ',' || o.longitude                 AS origin_latlong,
       ds.airport_code                                  AS dest_code,
       ds.city                                          AS dest_city,
       ds.state                                         AS dest_state,
       o.airport_code || ' - ' || ds.airport_code       AS route,
       f.flight_number,
       f.scheduled_departure,
       EXTRACT(HOUR FROM f.scheduled_departure)::INT    AS dep_hour,
       f.departure_delay_min,
       f.arrival_delay_min,
       f.distance_miles,
       CASE
           WHEN f.is_cancelled  THEN 'Cancelled'
           WHEN f.is_diverted   THEN 'Diverted'
           WHEN f.is_delayed_15 THEN 'Delayed'
           ELSE 'On time'
       END                                              AS flight_status,
       CASE f.cancellation_reason
           WHEN 'A' THEN 'Airline/Carrier'
           WHEN 'B' THEN 'Weather'
           WHEN 'C' THEN 'National Air System'
           WHEN 'D' THEN 'Security'
       END                                              AS cancellation_reason,
       f.is_cancelled::INT                              AS cancelled_flag,
       f.is_diverted::INT                               AS diverted_flag,
       (f.is_delayed_15 IS NOT NULL)::INT               AS completed_flag,
       COALESCE((NOT f.is_delayed_15)::INT, 0)          AS on_time_flag
FROM dw.fact_flights f
JOIN dw.dim_date    d  USING (date_key)
JOIN dw.dim_airline a  USING (airline_key)
JOIN dw.dim_airport o  ON o.airport_key  = f.origin_airport_key
JOIN dw.dim_airport ds ON ds.airport_key = f.dest_airport_key;


CREATE OR REPLACE VIEW reporting.v_daily_otp AS
SELECT d.full_date,
       d.day_name,
       COUNT(*)                                          AS flights,
       COUNT(f.is_delayed_15)                            AS completed,
       COUNT(*) FILTER (WHERE NOT f.is_delayed_15)       AS on_time,
       ROUND(100.0 * AVG((NOT f.is_delayed_15)::INT), 2) AS otp_pct,
       COUNT(*) FILTER (WHERE f.is_cancelled)            AS cancellations,
       ROUND(100.0 * AVG(f.is_cancelled::INT), 2)        AS cancel_pct
FROM dw.fact_flights f
JOIN dw.dim_date d USING (date_key)
GROUP BY d.full_date, d.day_name;
