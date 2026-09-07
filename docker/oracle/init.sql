-- Oracle Database Initialization for TPC-H Benchmark
-- Configure benchmark user (created by gvenzl/oracle-xe) and enable result cache per paper

-- Note: The 'benchmark' user is automatically created by the gvenzl/oracle-xe image
-- using APP_USER and APP_USER_PASSWORD environment variables from docker-compose.yml

-- Grant additional privileges to benchmark user
GRANT CONNECT, RESOURCE, CREATE VIEW TO benchmark;
GRANT SELECT ANY TABLE TO benchmark;
GRANT CREATE SESSION TO benchmark;
GRANT UNLIMITED TABLESPACE TO benchmark;

-- Result cache: MANUAL, which is Oracle's default.
--
-- This said FORCE, with the comment "enable result cache (mentioned in paper)".
-- FORCE caches the result set of *every* query and serves repeats from the
-- cache without re-executing them, and the measurement protocol here is four
-- repetitions with the first discarded as warmup - so the warmup populated the
-- cache and all three timed repetitions read it back.
--
-- Measured consequence: Q02 took 17.5 s on its first execution and 0.004 s on
-- the next, and Oracle's v$result_cache_statistics reported Find Count 4,368 -
-- that many results returned without executing the query. The recorded
-- overheads were correspondingly meaningless: +328% on a query whose two paths
-- both rounded to 0.00 s.
--
-- It also gave Oracle a capability no other system in the study has. PostgreSQL,
-- MySQL and SQL Server cache *pages*, so a repeat still executes the query
-- against warm buffers; none of them can return a stored result set. Comparing
-- a cached lookup against three real executions is not a comparison of database
-- systems, and within Oracle it is not a comparison of ORM against SQL either,
-- since both paths return the same cached rows.
--
-- MANUAL restores Oracle's default: the cache is used only by a query carrying
-- a /*+ RESULT_CACHE */ hint, and no query in this study carries one.
ALTER SYSTEM SET result_cache_mode = MANUAL;

-- Set optimizer settings
ALTER SYSTEM SET optimizer_mode = ALL_ROWS;
ALTER SYSTEM SET optimizer_features_enable = '21.1.0';

-- Memory settings (within XE limits)
ALTER SYSTEM SET pga_aggregate_target = 2G;
ALTER SYSTEM SET shared_pool_size = 1G;

-- Commit changes
COMMIT;

EXIT;
