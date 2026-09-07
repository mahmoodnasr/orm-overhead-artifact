# MOEF Quick Start Tutorial


> **Current as of the SF10 four-system campaign.** Dataset generation moved
> to DuckDB (`scripts/1-setup/generate_tpch_duckdb.py`) and the loaders now
> stream from it, so any `tpch-dbgen` / `.tbl` / `load_data_*.sh` step below
> has been replaced. `REPRODUCE.md` in the repository root is the path that
> was actually used to produce `results/all_results.csv`.

**Get started with MOEF analysis in 15 minutes**

---

## What You'll Learn

By the end of this tutorial, you'll:
- ✅ Run your first MOEF analysis
- ✅ Understand the comprehensive report
- ✅ Identify one optimization opportunity
- ✅ Apply a fix and measure improvement

**Time Required**: 15 minutes
**Prerequisites**: Databases running, data loaded

---

## Step 1: Verify Your Environment (2 minutes)

### Check Databases Are Running

```bash
# Check Docker containers
docker ps

# Should see:
# - postgres-container
# - mysql-container
```

**If not running**:
```bash
docker-compose up -d
sleep 30  # Wait for startup
```

### Test Database Connections

```bash
python scripts/1-setup/test_connections.py
```

**Expected output**:
```
✓ PostgreSQL: Connected
✓ MySQL: Connected
```

**If connection fails**: See [MOEF-TROUBLESHOOTING.md](MOEF-TROUBLESHOOTING.md#plan-collection-issues)

### Verify Data Is Loaded

```bash
# Quick check
docker exec -it postgres-container psql -U orm_user -d benchmark_db -c "SELECT COUNT(*) FROM lineitem;"
```

**Expected**: Should return a number > 0

**If 0 or error**: Load test data first
```bash
python3 scripts/1-setup/generate_tpch_duckdb.py
./dbgen -s 1  # 1GB scale
./column_split.sh
cd ..
./scripts/1-setup/load_all_databases.sh --scale 1
```

---

## Step 2: Run Quick MOEF Analysis (5 minutes)

### Run Pipeline on Two Sample Queries

We'll analyze Q8 and Q9 (complex queries that reveal interesting patterns):

```bash
./scripts/3-moef/run_moef_pipeline.sh --quick
```

**What happens**:
```
╔════════════════════════════════════════════════════════════╗
║         MOEF Pipeline - Mechanistic ORM Evaluation        ║
╚════════════════════════════════════════════════════════════╝

========================================
Phase 1: Plan Collection
========================================
Collecting plans from postgresql...
  ✓ Q8 django indexed
  ✓ Q8 django nonindexed
  ✓ Q8 sqlalchemy indexed
  ✓ Q8 sqlalchemy nonindexed
  ... (Q9 similar)

========================================
Phase 2: Mechanism Analysis
========================================
  ✓ Join enumeration analysis complete
  ✓ Join method analysis complete
  ✓ Index utilization analysis complete
  ✓ Predicate handling analysis complete

========================================
Phase 3: Causal Linking
========================================
  ⚠ Benchmark results not found
  ⚠ Skipping Phase 4 (non-critical)

========================================
Phase 4: Report Generation
========================================
  ✓ Comprehensive report generated
  ✓ Summary report generated
```

**Time**: 3-5 minutes (depends on your hardware)

**If it fails**: Check [MOEF-TROUBLESHOOTING.md](MOEF-TROUBLESHOOTING.md)

---

## Step 3: Read Your First MOEF Report (5 minutes)

### Open the Comprehensive Report

```bash
cat results/moef/COMPREHENSIVE_MOEF_REPORT.txt
```

Or use your favorite editor:
```bash
less results/moef/COMPREHENSIVE_MOEF_REPORT.txt
code results/moef/COMPREHENSIVE_MOEF_REPORT.txt
```

### Key Sections to Read

#### 1. Executive Summary

Look for the **Data Availability** section:

```
Data Availability:
  ✓ Join Enumeration              8 records
  ✓ Join Methods                  8 records
  ✓ Index Utilization             8 records
  ✓ Predicate Handling            8 records
```

**What this means**: All four MOEF dimensions have data ✓

#### 2. Paper Findings Validation

This is the most important section for your first read:

```
Finding 1: PostgreSQL Indexing Paradox (Section 4.3)
-------------------------------------------------------

Paper Claim:
  Django on PostgreSQL: -12% performance with indexes (DEGRADATION)
  SQLAlchemy on PostgreSQL: +98% performance with indexes (IMPROVEMENT)

Our Results:
  Django         Impact:   -10.5%  [✓ DEGRADATION CONFIRMED]
  SQLAlchemy     Impact:   +95.2%  [✓ IMPROVEMENT CONFIRMED]

  Status: ✓ PARADOX VALIDATED
```

**Key Insight**:
- If you're using **Django + PostgreSQL + Indexes**, you might be losing 10% performance!
- Switching to **SQLAlchemy** could nearly **double** your performance on the same database

#### 3. Q-error Analysis

Look for q-error values:

```
Finding 2: Cardinality Estimation Quality (Section 5.2.2)

Our Results (Q8):
  MySQL          Q-error:   8.45  [Poor]
  PostgreSQL     Q-error:   1.52  [Excellent]
```

**Quick Reference**:
- **< 2.0**: Excellent - optimizer is doing well
- **2-5**: Good - minor issues
- **5-10**: Acceptable - watch for problems
- **> 10**: Poor - optimization needed

**In this case**: MySQL's poor q-error (8.45) means it's likely choosing suboptimal query plans.

---

## Step 4: Find Your First Optimization (2 minutes)

### Locate the Recommendations Section

Scroll to **RECOMMENDATIONS FOR ORM-DATABASE CONFIGURATION**:

```
1. Database Selection:
---------------------------------------

For OLAP workloads (complex queries with many joins):
  ✓ PostgreSQL: Superior join enumeration and cardinality estimation
  ~ MySQL: Acceptable for simpler queries, struggles with complex joins
```

### Identify What Applies to You

**If you have**:
- Complex analytical queries (many joins)
- Currently using MySQL
- Experiencing slow query performance

**Then**: Consider migrating to PostgreSQL

**If you have**:
- Django on PostgreSQL
- Heavily indexed schema
- Performance seems worse than expected

**Then**: Test removing indexes or switching to SQLAlchemy

### Your First Action Item

Pick ONE of these based on your situation:

**Action A**: Update Statistics (Safe, always good)
```sql
-- PostgreSQL
ANALYZE;

-- MySQL
ANALYZE TABLE customers, orders, lineitem;
```

**Action B**: Test Index Impact (If using Django + PostgreSQL)
```bash
# Compare performance with and without indexes
python scripts/2-benchmark/run_benchmark.py \
    --orm django \
    --database postgresql \
    --queries 8 \
    --schema indexed \
    --repetitions 3

python scripts/2-benchmark/run_benchmark.py \
    --orm django \
    --database postgresql \
    --queries 8 \
    --schema nonindexed \
    --repetitions 3

# Compare results
python scripts/4-analysis/compare_schemas.py
```

**Action C**: Compare ORMs (If considering switch)
```bash
# Run same query with both ORMs
python scripts/2-benchmark/run_benchmark.py \
    --orm both \
    --database postgresql \
    --queries 8 \
    --repetitions 5
```

---

## Step 5: Dive Deeper (Optional)

### Explore Individual Reports

Each dimension has a detailed report:

```bash
# Join enumeration - DP vs Greedy
less results/moef/join_enumeration_analysis.txt

# Join methods - Hash vs Nested Loop
less results/moef/join_methods_analysis.txt

# Index usage patterns
less results/moef/index_utilization_analysis.txt

# Filter pushdown effectiveness
less results/moef/predicate_handling_analysis.txt
```

### Use CSV Data for Custom Analysis

```python
import pandas as pd

# Load join methods data
df = pd.read_csv('results/moef/join_methods.csv')

# Find queries with high q-error
high_qerror = df[df['avg_join_qerror'] > 5.0]
print("Queries needing attention:")
print(high_qerror[['query_id', 'database', 'orm', 'avg_join_qerror']])

# Output:
#   query_id  database      orm  avg_join_qerror
# 0       Q8     mysql   django             8.45
# 1       Q9     mysql   django             7.23
```

---

## Common First-Time Questions

### Q: The report shows "⚠ Statistical linking analysis failed"

**A**: This is expected if you haven't run full benchmarks yet. Statistical linking needs performance data.

**To fix**:
```bash
# Run benchmarks first
python scripts/2-benchmark/run_benchmark.py \
    --queries 8,9 \
    --orm both \
    --database both \
    --repetitions 5

# Then re-run MOEF
./scripts/3-moef/run_moef_pipeline.sh --skip-collection
```

### Q: My results don't exactly match the paper values

**A**: That's normal! Differences can be due to:
- Different hardware (CPU, RAM, SSD)
- Different data scale (1GB vs 100GB)
- Different database versions
- Different query workload

**What to look for**: Trends, not exact numbers
- If paper shows Django degrades with indexes, you should see degradation (even if -8% instead of -12%)
- If paper shows MySQL has higher q-error than PostgreSQL, you should see that pattern

### Q: What if I only use one database?

**A**: MOEF still provides value! It shows you:
- Whether your q-error is good (cardinality estimation quality)
- If indexes are helping or hurting
- Whether predicates are pushed down effectively
- Which ORM is better for your database

Run with `--database <your-db>`:
```bash
python scripts/3-moef/collect_execution_plans.py \
    --database postgresql \
    --orm both \
    --queries 8,9
```

### Q: Can I run MOEF on my production database?

**A**: Not directly on production! MOEF:
- Runs queries with EXPLAIN ANALYZE (executes the query)
- May take several minutes per query
- Can consume significant resources

**Recommended**: Use a staging environment or production replica.

---

## What's Next?

### Beginner Path

1. ✅ Complete this tutorial
2. Read [MOEF-RESULTS-GUIDE.md](MOEF-RESULTS-GUIDE.md) - Section "Understanding the Comprehensive Report"
3. Run MOEF on more queries: `--queries "3,5,7,8,9,10"`
4. Apply one optimization from recommendations
5. Re-run MOEF and verify improvement

### Intermediate Path

1. ✅ Complete beginner path
2. Read full [MOEF-RESULTS-GUIDE.md](MOEF-RESULTS-GUIDE.md)
3. Run full MOEF pipeline: `./scripts/3-moef/run_moef_pipeline.sh`
4. Analyze all four dimensions in detail
5. Create custom analysis scripts using CSV data

### Advanced Path

1. ✅ Complete intermediate path
2. Run full benchmarks for statistical linking
3. Implement automated recommendations
4. Integrate MOEF into CI/CD pipeline
5. Contribute improvements (Oracle/SQL Server parsers)

---

## Troubleshooting

**Problem**: "No plans found"
→ **Solution**: Run plan collection first (it's automatic in pipeline)

**Problem**: "Database connection refused"
→ **Solution**: `docker-compose up -d`, wait 30 seconds

**Problem**: "Query timeout"
→ **Solution**: Use smaller data scale or increase timeout

**Full troubleshooting**: [MOEF-TROUBLESHOOTING.md](MOEF-TROUBLESHOOTING.md)

---

## Quick Reference Card

```
┌────────────────────────────────────────────────────────┐
│ MOEF Quick Start - Essential Commands                  │
├────────────────────────────────────────────────────────┤
│                                                        │
│ Run MOEF Analysis:                                     │
│   ./scripts/3-moef/run_moef_pipeline.sh --quick       │
│                                                        │
│ Read Report:                                           │
│   cat results/moef/COMPREHENSIVE_MOEF_REPORT.txt      │
│                                                        │
│ Check What Failed:                                     │
│   tail results/moef/*.log                             │
│                                                        │
│ Re-run Without Re-collecting Plans:                    │
│   ./scripts/3-moef/run_moef_pipeline.sh \             │
│       --skip-collection                                │
│                                                        │
│ Analyze Specific Query:                                │
│   python scripts/3-moef/collect_execution_plans.py \  │
│       --queries 8 --database postgresql --orm both    │
│                                                        │
│ Q-error Thresholds:                                    │
│   < 2.0:  Excellent ✓                                  │
│   2-5:    Good      ✓                                  │
│   5-10:   Poor      ⚠                                  │
│   > 10:   Critical  ✗                                  │
│                                                        │
└────────────────────────────────────────────────────────┘
```

---

## Success Criteria

You've successfully completed this tutorial when you can:

- ✅ Run MOEF pipeline without errors
- ✅ Open and read the comprehensive report
- ✅ Explain what q-error means
- ✅ Identify whether indexes help or hurt in your setup
- ✅ Name one optimization you could apply

---

## Real-World Example

**Scenario**: You're using Django with PostgreSQL and queries feel slow.

**MOEF Analysis Shows**:
```
Index Impact (PostgreSQL):
  Django:
    Non-indexed: 1,234 ms
    Indexed:     1,382 ms
    Impact: -12.0% (DEGRADATION!)
```

**Your Action**:
1. Test query without indexes: 1,234ms
2. Test same query with SQLAlchemy: 789ms (36% faster!)
3. **Decision**: Migrate critical analytics queries to SQLAlchemy
4. **Result**: 36% performance improvement, same database

**Time to insight**: 15 minutes
**Implementation effort**: 2-3 days
**ROI**: Significant performance gain without infrastructure changes

---

## Getting Help

- **Results interpretation**: [MOEF-RESULTS-GUIDE.md](MOEF-RESULTS-GUIDE.md)
- **Troubleshooting**: [MOEF-TROUBLESHOOTING.md](MOEF-TROUBLESHOOTING.md)
- **Framework details**: [04-MOEF-FRAMEWORK.md](04-MOEF-FRAMEWORK.md)
- **General setup**: [01-GETTING-STARTED.md](01-GETTING-STARTED.md)

---

**Ready for more?** → [MOEF-RESULTS-GUIDE.md](MOEF-RESULTS-GUIDE.md)

**Having issues?** → [MOEF-TROUBLESHOOTING.md](MOEF-TROUBLESHOOTING.md)
