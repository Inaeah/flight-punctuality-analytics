-- OTP = share of completed flights (not cancelled/diverted) arriving <= 15 min late.

-- 1. Monthly overview
SELECT d.month,
       d.month_name,
       COUNT(*)                                                    AS flights,
       ROUND(100.0 * AVG((NOT f.is_delayed_15)::INT), 2)           AS otp_pct,
       ROUND(100.0 * AVG(f.is_cancelled::INT), 2)                  AS cancel_pct,
       ROUND(AVG(f.arrival_delay_min), 1)                          AS avg_arrival_delay_min
FROM dw.fact_flights f
JOIN dw.dim_date d USING (date_key)
GROUP BY d.month, d.month_name
ORDER BY d.month;


-- 2. Airline ranking by OTP
SELECT RANK() OVER (ORDER BY AVG((NOT f.is_delayed_15)::INT) DESC) AS otp_rank,
       a.airline_name,
       COUNT(*)                                                    AS flights,
       ROUND(100.0 * AVG((NOT f.is_delayed_15)::INT), 2)           AS otp_pct,
       ROUND(100.0 * AVG(f.is_cancelled::INT), 2)                  AS cancel_pct
FROM dw.fact_flights f
JOIN dw.dim_airline a USING (airline_key)
GROUP BY a.airline_name
ORDER BY otp_rank;


-- 3. Worst 10 departure airports by OTP (busy airports only, to avoid small-sample noise)
SELECT ap.airport_code,
       ap.city,
       ap.state,
       COUNT(*)                                                    AS departures,
       ROUND(100.0 * AVG((NOT f.is_delayed_15)::INT), 2)           AS otp_pct,
       ROUND(AVG(f.departure_delay_min), 1)                        AS avg_departure_delay_min
FROM dw.fact_flights f
JOIN dw.dim_airport ap ON ap.airport_key = f.origin_airport_key
GROUP BY ap.airport_code, ap.city, ap.state
HAVING COUNT(*) >= 10000
ORDER BY otp_pct
LIMIT 10;


-- 4. Cancellation causes per month, with share of the month's cancellations
SELECT d.month_name,
       CASE f.cancellation_reason
            WHEN 'A' THEN 'Airline/Carrier'
            WHEN 'B' THEN 'Weather'
            WHEN 'C' THEN 'National Air System'
            WHEN 'D' THEN 'Security'
       END                                                         AS reason,
       COUNT(*)                                                    AS cancellations,
       ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (PARTITION BY d.month), 1) AS share_pct
FROM dw.fact_flights f
JOIN dw.dim_date d USING (date_key)
WHERE f.is_cancelled
GROUP BY d.month, d.month_name, f.cancellation_reason
ORDER BY d.month, cancellations DESC;


-- 5. Delay by scheduled departure hour: delays accumulate through the day
SELECT EXTRACT(HOUR FROM f.scheduled_departure)::INT               AS dep_hour,
       COUNT(*)                                                    AS flights,
       ROUND(100.0 * AVG((NOT f.is_delayed_15)::INT), 2)           AS otp_pct,
       ROUND(AVG(f.departure_delay_min), 1)                        AS avg_departure_delay_min
FROM dw.fact_flights f
GROUP BY dep_hour
ORDER BY dep_hour;


-- 6. OTP by day of week
SELECT d.day_of_week,
       d.day_name,
       COUNT(*)                                                    AS flights,
       ROUND(100.0 * AVG((NOT f.is_delayed_15)::INT), 2)           AS otp_pct
FROM dw.fact_flights f
JOIN dw.dim_date d USING (date_key)
GROUP BY d.day_of_week, d.day_name
ORDER BY d.day_of_week;


-- 7. Top 10 busiest routes: dim_airport joined twice (origin and destination roles)
WITH route_stats AS (
    SELECT o.airport_code || ' - ' || dst.airport_code             AS route,
           COUNT(*)                                                AS flights,
           ROUND(100.0 * AVG((NOT f.is_delayed_15)::INT), 2)       AS otp_pct,
           MAX(f.distance_miles)                                   AS distance_miles
    FROM dw.fact_flights f
    JOIN dw.dim_airport o   ON o.airport_key   = f.origin_airport_key
    JOIN dw.dim_airport dst ON dst.airport_key = f.dest_airport_key
    GROUP BY o.airport_code, dst.airport_code
)
SELECT route, flights, otp_pct, distance_miles
FROM route_stats
ORDER BY flights DESC
LIMIT 10;
