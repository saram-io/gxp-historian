-- =============================================================================
-- 01_telemetry_core.sql
-- Pillar 2: ClickHouse Telemetry Archive, 1-Minute Rollup Materialized View,
-- PostgreSQL Tag Dictionary, and External Event Frames Bridge
-- =============================================================================

CREATE DATABASE IF NOT EXISTS pi_historian;

-- 1. Raw Immutable Telemetry Table
CREATE TABLE IF NOT EXISTS pi_historian.sensor_data
(
    tag_id UInt32 CODEC(Delta, ZSTD(1)),
    ts DateTime64(3, 'UTC') CODEC(DoubleDelta, ZSTD(1)),
    val Float64 CODEC(Gorilla, ZSTD(1)),
    str_val LowCardinality(String) DEFAULT '' CODEC(ZSTD(1)),
    quality UInt8 DEFAULT 192 CODEC(T64, ZSTD(1)),
    status_code UInt16 DEFAULT 0 CODEC(T64, ZSTD(1))
)
ENGINE = MergeTree()
PARTITION BY toYYYYMM(ts)
ORDER BY (tag_id, ts);

-- 2. 1-Minute Rollup Target Table (AggregatingMergeTree)
CREATE TABLE IF NOT EXISTS pi_historian.sensor_rollup_1m
(
    tag_id UInt32,
    bucket_1m DateTime('UTC'),
    avg_val AggregateFunction(avg, Float64),
    min_val AggregateFunction(min, Float64),
    max_val AggregateFunction(max, Float64),
    std_val AggregateFunction(stddevPop, Float64),
    first_val AggregateFunction(argMin, Float64, DateTime64(3, 'UTC')),
    last_val AggregateFunction(argMax, Float64, DateTime64(3, 'UTC')),
    sample_count AggregateFunction(count)
)
ENGINE = AggregatingMergeTree()
PARTITION BY toYYYYMM(bucket_1m)
ORDER BY (tag_id, bucket_1m);

-- 3. Materialized View populating 1-Minute Rollups (Good Quality >= 192 only)
CREATE MATERIALIZED VIEW IF NOT EXISTS pi_historian.mv_sensor_rollup_1m
TO pi_historian.sensor_rollup_1m
AS
SELECT
    tag_id,
    toStartOfMinute(ts) AS bucket_1m,
    avgState(val) AS avg_val,
    minState(val) AS min_val,
    maxState(val) AS max_val,
    stddevPopState(val) AS std_val,
    argMinState(val, ts) AS first_val,
    argMaxState(val, ts) AS last_val,
    countState() AS sample_count
FROM pi_historian.sensor_data
WHERE quality >= 192
GROUP BY tag_id, bucket_1m;

-- 4. In-Memory PostgreSQL Tag & Asset Hierarchy Dictionary
CREATE DICTIONARY IF NOT EXISTS pi_historian.pg_asset_tags
(
    tag_id UInt64,
    tag_name String DEFAULT '',
    asset_name String DEFAULT '',
    asset_path String DEFAULT '',
    attribute_name String DEFAULT '',
    eng_units String DEFAULT '',
    is_step_tag Int32 DEFAULT 0,
    low_limit Float64 DEFAULT 0.0,
    high_limit Float64 DEFAULT 0.0
)
PRIMARY KEY tag_id
SOURCE(POSTGRESQL(
    port 5432
    host 'postgres-control'
    user 'historian_admin'
    password 'GxP_Pg_Secret_2026!'
    db 'pi_control_plane'
    table 'v_clickhouse_tag_dict'
))
LAYOUT(FLAT())
LIFETIME(MIN 5 MAX 15);

-- 5. External PostgreSQL Table Bridge for ISA-88 Event Frames
CREATE TABLE IF NOT EXISTS pi_historian.pg_event_frames
(
    event_id UUID,
    parent_event_id Nullable(UUID),
    event_name String,
    event_template String,
    asset_id Int32,
    start_time DateTime64(6, 'UTC'),
    end_time Nullable(DateTime64(6, 'UTC')),
    severity String,
    captured_metrics String,
    signed_by Nullable(String),
    signature_meaning Nullable(String),
    signed_at Nullable(DateTime64(6, 'UTC')),
    signature_hash Nullable(String)
)
ENGINE = PostgreSQL('postgres-control:5432', 'pi_control_plane', 'event_frames', 'historian_admin', 'GxP_Pg_Secret_2026!');
