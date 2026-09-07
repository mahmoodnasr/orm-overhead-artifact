# MOEF Troubleshooting Guide

**Solutions to common issues when running MOEF analysis**

---

## Quick Diagnosis

Run this diagnostic command first:

```bash
./scripts/utils/diagnose_moef.sh
```

If that doesn't exist, use this manual checklist:

```bash
# 1. Check database connections
python scripts/1-setup/test_connections.py

# 2. Check for execution plans
ls -la results/execution_plans/

# 3. Check MOEF outputs
ls -la results/moef/

# 4. Check logs
tail -50 results/moef/*.log 2>/dev/null || echo "No logs found"
```

---

## Problem Categories

- [Plan Collection Issues](#plan-collection-issues)
- [Parser Errors](#parser-errors)
- [Analysis Failures](#analysis-failures)
- [Statistical Linking Problems](#statistical-linking-problems)
- [Performance Issues](#performance-issues)
- [Data Quality](#data-quality)

---

## Plan Collection Issues

### Issue: No Execution Plans Collected

**Symptoms**:
```
Found 0 plan files
```

**Diagnosis**:
```bash
# Check if collector ran
python scripts/3-moef/collect_execution_plans.py \
    --database postgresql \
    --orm django \
    --queries 8 \
    --with-execution \
    --verbose
```

**Common Causes**:

#### Cause 1: Database Not Running

**Check**:
```bash
docker ps | grep postgres
docker ps | grep mysql
```

**Solution**:
```bash
docker-compose up -d
# Wait 30 seconds for databases to initialize
sleep 30
python scripts/1-setup/test_connections.py
```

#### Cause 2: Database Connection Refused

**Error**:
```
psycopg2.OperationalError: could not connect to server: Connection refused
```

**Solution**:
```bash
# Check database is listening
docker exec -it postgres-container pg_isready

# If not ready, restart
docker-compose restart postgresql

# Update connection settings if needed
vi config/databases/default.yaml
```

#### Cause 3: Missing Database Credentials

**Error**:
```
authentication failed for user "orm_user"
```

**Solution**:
```bash
# Check environment variables
echo $DATABASE_URL
echo $MYSQL_PASSWORD

# If missing, source the env file
source .env

# Or set manually
export DATABASE_URL="postgresql://orm_user:password@localhost:5432/benchmark_db"
```

#### Cause 4: Queries Not Loaded

**Error**:
```
ModuleNotFoundError: No module named 'django_app.queries'
```

**Solution**:
```bash
# Ensure PYTHONPATH is set
export PYTHONPATH="${PYTHONPATH}:$(pwd)"

# Verify query files exist
ls -la django_app/queries/tpch/base/
ls -la sqlalchemy_app/queries/tpch/base/

# Try importing manually
python -c "from django_app.queries.tpch.base.q8 import execute_query"
```

### Issue: Plans Collected But Empty

**Symptoms**:
```json
{
  "metadata": {...},
  "plan": null
}
```

**Cause**: EXPLAIN returned no plan (query syntax error or timeout)

**Diagnosis**:
```bash
# Run query manually
docker exec -it postgres-container psql -U orm_user -d benchmark_db

# In psql:
\timing on
EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)
SELECT * FROM lineitem LIMIT 1;
```

**Solutions**:

1. **Syntax Error**: Fix query in `django_app/queries/` or `sqlalchemy_app/queries/`

2. **Timeout**:
```sql
-- Increase statement timeout
SET statement_timeout = '5min';
```

3. **Permission Issue**:
```sql
-- Grant necessary permissions
GRANT SELECT ON ALL TABLES IN SCHEMA public TO orm_user;
```

### Issue: Partial Plan Collection

**Symptoms**:
```
Collected 45 plans, expected 88
```

**Analysis**:
```bash
# Find which queries failed
ls results/execution_plans/postgresql/ | grep -o 'q[0-9]*' | sort -u

# Expected queries
echo "Q1 Q2 Q3 Q4 Q5 Q6 Q7 Q8 Q9 Q10 ..." | tr ' ' '\n' | sort

# Compare
comm -23 <(echo "Q1 Q2 ... Q22" | tr ' ' '\n' | sort) \
         <(ls results/execution_plans/postgresql/ | grep -o 'q[0-9]*' | sort -u)
```

**Solutions**:

1. **Specific Queries Failing**: Run those queries manually to find the error

2. **Timeout on Complex Queries**:
```bash
# Collect with longer timeout
python scripts/3-moef/collect_execution_plans.py \
    --database postgresql \
    --timeout 600  # 10 minutes
```

3. **Out of Memory**:
```yaml
# Increase Docker memory in docker-compose.yml
services:
  postgresql:
    deploy:
      resources:
        limits:
          memory: 8G
```

---

## Parser Errors

### Issue: JSON Parsing Failed

**Error**:
```
json.decoder.JSONDecodeError: Expecting value: line 1 column 1 (char 0)
```

**Cause**: EXPLAIN output is not valid JSON

**Diagnosis**:
```bash
# Check raw plan file
cat results/execution_plans/postgresql/q8_django_indexed_plan.json

# If it's not JSON, check what database returned
```

**Solutions**:

1. **PostgreSQL**: Ensure FORMAT JSON is used
```python
# In parsers/postgres_parser.py
cursor.execute("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) %s", [query])
```

2. **MySQL**: Handle both JSON and text formats
```python
# MySQL sometimes returns text even when JSON requested
try:
    plan = json.loads(output)
except json.JSONDecodeError:
    plan = parse_mysql_text_format(output)
```

### Issue: Missing Required Fields

**Error**:
```
KeyError: 'Plan'
```

**Cause**: Parser expects field that doesn't exist in this database version

**Diagnosis**:
```python
# Print the full plan to see structure
import json
with open('results/execution_plans/postgresql/q8_plan.json') as f:
    plan = json.load(f)
print(json.dumps(plan, indent=2))
```

**Solution**: Update parser to handle missing fields
```python
# Before (will crash):
root_plan = plan_json['Plan']

# After (graceful handling):
root_plan = plan_json.get('Plan')
if not root_plan:
    logger.warning(f"No 'Plan' key in {plan_file}")
    root_plan = plan_json.get('QUERY PLAN', {})
```

### Issue: Unexpected Plan Structure

**Error**:
```
AttributeError: 'list' object has no attribute 'get'
```

**Cause**: Plan structure different than expected

**Example**:
```python
# Parser expects:
{'Plan': {'Node Type': 'Hash Join', ...}}

# But gets:
[{'Plan': {'Node Type': 'Hash Join', ...}}]  # Wrapped in list!
```

**Solution**: Add defensive checks
```python
def parse_postgres_plan(plan_json):
    # Handle list wrapper
    if isinstance(plan_json, list):
        plan_json = plan_json[0] if plan_json else {}

    # Handle missing Plan key
    if 'Plan' not in plan_json:
        return {'type': 'Unknown', 'children': []}

    return _parse_node(plan_json['Plan'])
```

---

## Analysis Failures

### Issue: Join Enumeration Analysis Failed

**Error**:
```
ValueError: No valid join operations found
```

**Cause**: Parser didn't extract joins, or queries have no joins

**Diagnosis**:
```bash
# Check if join data was extracted
python -c "
import pandas as pd
df = pd.read_csv('results/moef/join_enumeration.csv')
print(f'Records: {len(df)}')
print(f'Columns: {df.columns.tolist()}')
print(df.head())
"
```

**Solutions**:

1. **No Join Queries in Dataset**:
```bash
# Run queries with joins (Q3, Q5, Q7, Q8, Q9)
./scripts/3-moef/run_moef_pipeline.sh --queries "3,5,7,8,9"
```

2. **Parser Not Detecting Joins**:
```python
# Debug: Print what parser extracts
in scripts/3-moef/analyze_join_enumeration.py:

joins = self._extract_joins(plan)
print(f"Extracted {len(joins)} joins from {plan_file}")
if len(joins) == 0:
    print(json.dumps(plan, indent=2))  # See why no joins found
```

3. **Case Sensitivity Issue**:
```python
# Parser looking for 'join' but plan has 'Join'
node_type = node.get('type', '').lower()  # Always lowercase
if 'join' in node_type:
    # Process join
```

### Issue: Q-error Calculation Returns Inf

**Symptoms**:
```
avg_join_qerror: inf
```

**Cause**: Division by zero (estimated or actual rows = 0)

**This is Usually OK** if:
- Actual rows = 0 (empty result): Optimizer was correct
- Estimated > 0, Actual = 0: Optimizer overestimated but result is still correct

**This is a PROBLEM** if:
- Estimated = 0, Actual > 0: **Catastrophic underestimation!**

**Solution**: Filter infinite q-errors before aggregation
```python
# In analyze_join_methods.py
join_qerrors = [
    j['qerror']
    for j in joins
    if j['qerror'] is not None
    and not np.isinf(j['qerror'])  # Filter out infinite
    and j['qerror'] > 0  # Filter out invalid
]

avg_qerror = np.mean(join_qerrors) if join_qerrors else 0.0
```

### Issue: No Index Utilization Data

**Error**:
```
index_utilization.csv is empty
```

**Cause**: Plans don't contain index usage information

**Diagnosis**:
```bash
# Check a sample plan manually
cat results/execution_plans/postgresql/q8_plan.json | grep -i index
```

**Solutions**:

1. **PostgreSQL**: Ensure BUFFERS option is used (shows I/O stats)
```python
EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) SELECT ...
```

2. **MySQL**: Index usage in `type` field
```json
{
  "type": "index",  // or "ref", "range", etc.
  "possible_keys": ["idx_customer_id"],
  "key": "idx_customer_id"
}
```

3. **No Indexes Exist**: Create indexes first
```bash
python scripts/1-setup/create_indexes.py --schema indexed
```

---

## Statistical Linking Problems

### Issue: Correlation Analysis Has No Data

**Error**:
```
correlations.csv is empty
```

**Cause**: Missing benchmark performance data

**Solution**:
```bash
# Check for benchmark results
ls -la results/raw/benchmark_results.csv

# If missing, run benchmarks
python scripts/2-benchmark/run_benchmark.py \
    --benchmark tpch \
    --database postgresql \
    --orm both \
    --queries 8,9 \
    --repetitions 5

# Then re-run statistical linking
python scripts/3-moef/statistical_linking.py \
    --moef-dir results/moef \
    --benchmark-file results/raw/benchmark_results.csv
```

### Issue: Insufficient Samples for Correlation

**Error**:
```
ValueError: Need at least 10 samples, got 3
```

**Cause**: Not enough data points for statistical significance

**Solution**:
```bash
# Run more queries
./scripts/3-moef/run_moef_pipeline.sh --queries "1,3,5,7,8,9,10,12,14,19"

# Or increase repetitions in benchmarks
python scripts/2-benchmark/run_benchmark.py \
    --repetitions 9  # Increased from default 3
```

### Issue: Columns Don't Match

**Error**:
```
KeyError: 'execution_time'
```

**Cause**: Column names differ between MOEF results and benchmark results

**Diagnosis**:
```python
import pandas as pd

moef_df = pd.read_csv('results/moef/join_methods.csv')
bench_df = pd.read_csv('results/raw/benchmark_results.csv')

print("MOEF columns:", moef_df.columns.tolist())
print("Benchmark columns:", bench_df.columns.tolist())
```

**Solution**: Rename columns to match
```python
# In statistical_linking.py
performance_df = performance_df.rename(columns={
    'mean_time_ms': 'execution_time',
    'query': 'query_id',
    'db': 'database'
})
```

---

## Performance Issues

### Issue: Plan Collection Takes Forever

**Symptoms**:
- Collecting plans for one query takes > 5 minutes
- Process appears hung

**Diagnosis**:
```bash
# Check what's running
ps aux | grep python
ps aux | grep postgres

# Check database locks
docker exec -it postgres-container psql -U orm_user -d benchmark_db -c "
SELECT pid, query, state, wait_event_type, wait_event
FROM pg_stat_activity
WHERE state != 'idle';
"
```

**Solutions**:

1. **Query is Actually Slow**: That's OK, it's measuring real performance
```bash
# Use --quick mode for testing
./scripts/3-moef/run_moef_pipeline.sh --quick
```

2. **Database is Overloaded**:
```bash
# Reduce concurrency
python scripts/3-moef/collect_execution_plans.py \
    --workers 1  # Single-threaded
```

3. **Large Result Sets**: Add LIMIT for plan collection
```python
# In collect_execution_plans.py
# Don't fetch actual results, just get the plan
cursor.execute(f"EXPLAIN (ANALYZE) SELECT * FROM (...) LIMIT 0")
```

### Issue: Analysis Scripts Using Too Much Memory

**Error**:
```
MemoryError: Unable to allocate array
```

**Cause**: Loading too many large plan files at once

**Solution**: Process in batches
```python
# Instead of:
plan_files = list(self.plans_dir.rglob('*_plan.json'))
for plan_file in plan_files:  # Loads all into memory
    ...

# Use generator:
def plan_generator(plans_dir):
    for plan_file in plans_dir.rglob('*_plan.json'):
        with open(plan_file) as f:
            yield json.load(f)

for plan in plan_generator(self.plans_dir):  # One at a time
    ...
```

---

## Data Quality

### Issue: Q-error Values Seem Wrong

**Symptoms**:
```
Q-error: 0.01 (impossibly low)
Q-error: 10000 (impossibly high)
```

**Diagnosis**: Check the actual estimated vs actual rows

```python
import pandas as pd
df = pd.read_csv('results/moef/join_methods.csv')

# Expand join_details to see raw numbers
for _, row in df.iterrows():
    print(f"{row['query_id']}:")
    for join in row['join_details']:
        print(f"  Est: {join['estimated_rows']}, "
              f"Act: {join['actual_rows']}, "
              f"Q-err: {join['qerror']}")
```

**Common Issues**:

1. **Estimated = Actual by Coincidence**: Valid, just rare
2. **Both Very Small (< 10)**: Q-error unreliable at small scales
3. **Actual = 0**: Query returned no rows (not an error)
4. **Estimated = 0, Actual > 0**: **Critical optimizer bug!**

**Solution**: Filter unreliable q-errors
```python
# Only use q-errors where both estimated and actual > 10
reliable_qerrors = df[
    (df['estimated_rows'] > 10) &
    (df['actual_rows'] > 10)
]['avg_join_qerror']
```

### Issue: Pushdown Ratio is 0% or 100%

**Suspicious Values**:
```
Pushdown ratio: 0.0%  (no filters pushed down - unlikely)
Pushdown ratio: 100%  (all filters pushed down - suspicious if complex query)
```

**Diagnosis**:
```bash
# Check predicate handling details
python -c "
import pandas as pd
df = pd.read_csv('results/moef/predicate_handling.csv')

print('Pushdown distribution:')
print(df['pushdown_ratio'].describe())

# Check specific query
q8 = df[df['query_id'] == 'Q8']
print(f\"Q8 pushdown: {q8['pushdown_ratio'].values[0]}\")
print(f\"Q8 predicates: {q8['total_predicates'].values[0]}\")
"
```

**Potential Issues**:

1. **0% Pushdown**: Parser not detecting scan-level filters
```python
# Debug: Check what filters are being extracted
predicates = self._extract_predicates(plan)
print(f"Found {len(predicates)} predicates")
for p in predicates:
    print(f"  {p['condition']} at {p['node_type']}, pushed={p['pushed_down']}")
```

2. **100% Pushdown**: Query has no filters, or all are trivial
```sql
-- This has no filters:
SELECT * FROM customers;  -- 100% pushdown is meaningless

-- This has one filter at scan level:
SELECT * FROM customers WHERE city = 'NYC';  -- 100% is correct
```

### Issue: Index Comparison Shows No Difference

**Symptoms**:
```
Indexed:     1234 ms
Non-indexed: 1236 ms
Impact:      -0.2%  (basically the same)
```

**Possible Causes**:

1. **Indexes Not Created**:
```bash
# Verify indexes exist
docker exec -it postgres-container psql -U orm_user -d benchmark_db -c "
\di  -- List all indexes
"

# Create if missing
python scripts/1-setup/create_indexes.py --schema indexed
```

2. **Data Too Small**: Indexes don't help on tiny tables
```sql
-- Check table sizes
SELECT
    schemaname,
    tablename,
    pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename))
FROM pg_tables
WHERE schemaname = 'public'
ORDER BY pg_total_relation_size(schemaname||'.'||tablename) DESC;
```

If tables < 1MB, indexes won't make much difference.

3. **Query Doesn't Use Indexed Columns**:
```sql
-- This won't use index on customer_id:
SELECT * FROM orders WHERE order_date > '2024-01-01';

-- Need index on order_date:
CREATE INDEX idx_orders_date ON orders(order_date);
```

---

## Environment Issues

### Issue: Import Errors

**Error**:
```
ModuleNotFoundError: No module named 'scipy'
```

**Solution**:
```bash
# Reinstall dependencies
pip install -r requirements.txt

# If specific package missing
pip install scipy pandas numpy scikit-learn
```

### Issue: Permission Denied

**Error**:
```
PermissionError: [Errno 13] Permission denied: 'results/moef/join_methods.csv'
```

**Solution**:
```bash
# Fix permissions
chmod -R u+w results/

# If Docker volume issue
docker-compose down
docker volume rm orm-benchmark_results
docker-compose up -d
```

### Issue: Disk Space Full

**Error**:
```
OSError: [Errno 28] No space left on device
```

**Check**:
```bash
df -h .
du -sh results/
```

**Solution**:
```bash
# Clean old results
rm -rf results/execution_plans/old_*
rm -rf results/moef/backup_*

# Compress old plans
tar -czf results/plans_archive_$(date +%Y%m%d).tar.gz results/execution_plans/
rm -rf results/execution_plans/*
```

---

## Getting Help

If none of these solutions work:

1. **Enable Debug Logging**:
```bash
export MOEF_DEBUG=1
./scripts/3-moef/run_moef_pipeline.sh --verbose 2>&1 | tee moef_debug.log
```

2. **Collect Diagnostic Info**:
```bash
# System info
uname -a
python --version
docker --version

# Environment
env | grep -E '(DATABASE|PYTHON|PATH)'

# Files
find results/ -name "*.csv" -o -name "*.json" | head -20

# Sizes
du -sh results/*
```

3. **Create Minimal Reproducible Example**:
```bash
# Test with single query
python scripts/3-moef/collect_execution_plans.py \
    --database postgresql \
    --orm django \
    --queries 6 \
    --verbose

python scripts/3-moef/analyze_join_methods.py \
    --plans-dir results/execution_plans/ \
    --verbose
```

4. **Report Issue**: Include the diagnostic log and example when reporting

---

## Prevention

### Pre-flight Checklist

Before running MOEF analysis:

```bash
# 1. Verify databases are running and accessible
docker ps
python scripts/1-setup/test_connections.py

# 2. Verify data is loaded
docker exec -it postgres-container psql -U orm_user -d benchmark_db -c "
SELECT COUNT(*) FROM lineitem;
"
# Should return > 0

# 3. Verify queries can execute
python -c "
from django_app.queries.tpch.base.q6 import execute_query
result = execute_query()
print(f'Q6 returned {len(result)} rows')
"

# 4. Verify disk space
df -h . | grep -v tmpfs

# 5. Verify output directories exist
mkdir -p results/{execution_plans,moef}

# 6. Run quick test
./scripts/3-moef/run_moef_pipeline.sh --quick
```

If all checks pass, you're ready for full MOEF analysis.

---

## Quick Reference

```
┌─────────────────────────────────────────────────────────────┐
│ Common Error Patterns                                        │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│ "Connection refused"                                        │
│   → Docker not running or database not started             │
│   → Fix: docker-compose up -d                              │
│                                                             │
│ "No plans found"                                            │
│   → Plans not collected yet                                │
│   → Fix: Run collect_execution_plans.py first              │
│                                                             │
│ "KeyError: 'Plan'"                                          │
│   → Parser incompatibility                                 │
│   → Fix: Check plan format matches parser expectations     │
│                                                             │
│ "Q-error is infinite"                                       │
│   → Estimated or actual rows = 0                           │
│   → Usually OK, filter before analysis                     │
│                                                             │
│ "Insufficient samples"                                      │
│   → Not enough queries run                                 │
│   → Fix: Run more queries or increase repetitions          │
│                                                             │
│ "MemoryError"                                               │
│   → Too many plans loaded at once                          │
│   → Fix: Process in batches or increase RAM                │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

**Still stuck?** See [MOEF-RESULTS-GUIDE.md](MOEF-RESULTS-GUIDE.md) for interpretation help.
