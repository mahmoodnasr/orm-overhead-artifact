# MOEF Framework: Mechanistic ORM Evaluation

**Mechanistic ORM Evaluation Framework (MOEF)**  
**Paper Section**: 3.3 - Methodology  
**Purpose**: Understand *why* performance differs, not just *what* differences exist

---

## Table of Contents

1. [Overview](#overview)
2. [Why MOEF?](#why-moef)
3. [The Four Phases](#the-four-phases)
4. [Phase 1: Workload Generation](#phase-1-workload-generation)
5. [Phase 2: Plan Collection](#phase-2-plan-collection)
6. [Phase 3: Mechanism Analysis](#phase-3-mechanism-analysis)
7. [Phase 4: Causal Linking](#phase-4-causal-linking)
8. [Example Walkthrough](#example-walkthrough-tpc-h-query-8)
9. [Running MOEF](#running-moef)
10. [Interpreting Results](#interpreting-results)

---

## Overview

MOEF transforms ORM benchmarking from **black-box observation** to **mechanistic explanation** through systematic analysis of query execution plans.

### The Problem

Traditional ORM benchmarks tell you:
- ❌ "Django is 726% slower than SQL on Oracle"
- ❌ "PostgreSQL performs better with SQLAlchemy"

But they don't explain **WHY**.

### The MOEF Solution

MOEF explains the mechanisms:
- ✅ "Django overhead is high on Oracle because object materialization dominates (434s vs 1s SQL)"
- ✅ "PostgreSQL's dynamic programming join enumeration enables SQLAlchemy to utilize indexes effectively"

---

## Why MOEF?

### Traditional Approach (Black Box)

```
Query → Execute → Measure Time → Report Overhead
```

**Limitations:**
- Cannot predict behavior on new queries
- Cannot guide optimization efforts
- Cannot explain unexpected results
- Cannot transfer insights to other systems

### MOEF Approach (White Box)

```
Query → Execute → Collect Plan → Analyze Mechanisms → Link to Performance
```

**Advantages:**
- Explains **why** performance differs
- Enables **prediction** of behavior
- Guides **optimization** decisions
- Provides **transferable** insights

---

## The Four Phases

```
┌─────────────────┐
│   Phase 1:      │
│   Workload      │ → Generate ORM queries + SQL baselines
│   Generation    │
└────────┬────────┘
         │
         ↓
┌─────────────────┐
│   Phase 2:      │
│   Plan          │ → Collect execution plans with actual stats
│   Collection    │ → Calculate q-error for estimation quality
└────────┬────────┘
         │
         ↓
┌─────────────────┐
│   Phase 3:      │
│   Mechanism     │ → Analyze join enumeration
│   Analysis      │ → Analyze join methods
│                 │ → Analyze index usage
│                 │ → Analyze predicate handling
└────────┬────────┘
         │
         ↓
┌─────────────────┐
│   Phase 4:      │
│   Causal        │ → Statistical analysis
│   Linking       │ → Correlation: mechanism → performance
│                 │ → Effect size quantification
└─────────────────┘
```

---

## Phase 1: Workload Generation

**Purpose**: Create comparable ORM and SQL queries for all configurations.

### What It Does

For each query (e.g., TPC-H Q8):
1. Implement in **Django ORM**
2. Implement in **SQLAlchemy ORM**
3. Create **direct SQL baseline**
4. Ensure all three are **semantically equivalent**

### Implementation Status

✅ **Complete** - All queries implemented:
- `django_app/queries/tpch/base/q01.py` through `q22.py`
- `sqlalchemy_app/queries/tpch/base/q01.py` through `q22.py`
- Vendor-specific variants for Oracle, SQL Server, MySQL

### Verification

```bash
# Verify query equivalence
python scripts/utils/verify_query_equivalence.py --query 8

# Output:
# ✓ Django, SQLAlchemy, SQL return identical results
# ✓ Row counts match: 2 rows
# ✓ Column values match (within floating point tolerance)
```

**Key Principle**: If results differ, the queries are not comparable and must be fixed before proceeding.

---

## Phase 2: Plan Collection

**Purpose**: Collect query execution plans with actual runtime statistics.

### What It Collects

For each ORM-DBMS-query combination:
1. **Query execution plan** (structure)
2. **Estimated row counts** (optimizer predictions)
3. **Actual row counts** (runtime reality)
4. **Buffer usage** (I/O statistics)
5. **Execution time** per operator

### DBMS-Specific Commands

#### PostgreSQL
```sql
EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) 
SELECT ...;
```

**Output**: JSON with complete tree, actual rows, buffer hits/misses

#### MySQL
```sql
EXPLAIN ANALYZE 
SELECT ...;
```

**Output**: Tree format with actual execution time and rows

#### Oracle
```sql
EXPLAIN PLAN FOR SELECT ...;
SELECT * FROM TABLE(DBMS_XPLAN.DISPLAY('PLAN_TABLE', NULL, 'ALLSTATS LAST'));
```

**Output**: Text format with estimated rows (actual rows require DBMS_SQLTUNE)

#### SQL Server
```sql
SET STATISTICS PROFILE ON;
SET SHOWPLAN_XML ON;
SELECT ...;
```

**Output**: XML plan with estimated and actual rows

### Running Plan Collection

```bash
# Collect plans for all queries on PostgreSQL
python scripts/3-moef/collect_execution_plans.py \
    --orm django \
    --dbms postgresql \
    --queries all

# Output: results/execution_plans/django/postgresql/q*.json
```

### Q-Error Calculation

**Q-error** measures cardinality estimation quality:

```
q-error = max(estimated_rows / actual_rows, actual_rows / estimated_rows)
```

- **q-error = 1.0**: Perfect estimation ✅
- **q-error = 2.0**: Off by 2× (common)
- **q-error = 10.0**: Off by 10× (problematic)
- **q-error = 100.0**: Off by 100× (severe)

**Why It Matters**: High q-error leads to suboptimal plans.

```bash
# Calculate q-error for all collected plans
python scripts/3-moef/calculate_qerror.py

# Output: results/qerror/qerror_analysis_by_query.csv
```

**Example Output**:
```csv
query_id,dbms,min_qerror,max_qerror,median_qerror,mean_qerror,p95_qerror
Q08,postgresql,1.0,1.8,1.4,1.3,1.7
Q08,mysql,1.2,15.3,8.7,9.1,14.2
Q08,oracle,1.0,1.5,1.2,1.2,1.4
Q08,sqlserver,1.1,3.2,2.1,2.0,2.9
```

**Interpretation**: MySQL's high q-error on Q8 (median 8.7) explains why it selects suboptimal plans.

---

## Phase 3: Mechanism Analysis

**Purpose**: Characterize optimizer behavior across four key dimensions.

### Dimension 1: Join Enumeration Strategy

**What It Determines**: How the optimizer searches for the best join order.

#### Strategies

| DBMS | Strategy | Search Space | Notes |
|------|----------|--------------|-------|
| **PostgreSQL** | Dynamic Programming | O(3^n) | ≤12 tables, then GEQO |
| **MySQL** | Greedy | O(n^2) | Limited search depth |
| **Oracle** | Dynamic Programming | O(n!) | Adaptive, ≤10 tables |
| **SQL Server** | Dynamic Programming | O(3^n) | Adaptive complexity |

**Why It Matters**: Complex queries (Q8, Q9) with 8+ joins expose differences.

**Running Analysis**:
```bash
python scripts/3-moef/analyze_join_enumeration.py

# Output: results/processed/join_enumeration_analysis.csv
```

**Example Finding** (from paper):
- **PostgreSQL Q8**: DP finds optimal join order → 6.3s execution
- **MySQL Q8**: Greedy finds suboptimal order → 117s execution (18× slower)

### Dimension 2: Join Method Selection

**What It Determines**: Physical join algorithm used at each join operator.

#### Join Methods

| Method | Best For | Cost Model |
|--------|----------|------------|
| **Nested Loop** | Small inner table | O(outer × inner) |
| **Hash Join** | Large tables, equi-joins | O(outer + inner) + hash build |
| **Merge Join** | Sorted inputs | O(outer + inner) if sorted |
| **Index Nested Loop** | Indexed inner | O(outer × log(inner)) |

**Why It Matters**: Wrong method (e.g., NL instead of Hash) can be 100× slower.

**Running Analysis**:
```bash
python scripts/3-moef/analyze_join_methods.py

# Output: results/processed/join_methods_analysis.csv
```

**Example Finding**:
- **PostgreSQL**: Correctly chooses Hash Join for large tables
- **MySQL**: Sometimes chooses Nested Loop due to high q-error

### Dimension 3: Index Utilization

**What It Determines**: Whether optimizer uses available indexes effectively.

#### Index Access Patterns

| Pattern | Description | When Used |
|---------|-------------|-----------|
| **Index Scan** | Read index + heap | Selective predicates |
| **Index-Only Scan** | Read index only | Covering index |
| **Bitmap Index Scan** | Index → bitmap → heap | Multiple indexes |
| **Full Table Scan** | Read entire table | Low selectivity or no index |

**Why It Matters**: Index usage can change performance by 10-100×.

**Running Analysis**:
```bash
python scripts/3-moef/analyze_index_usage.py

# Output: results/processed/index_usage_analysis.csv
```

**Example Finding** (from paper):
- **Django + PostgreSQL + Indexes**: Full table scans → 12% slower
- **SQLAlchemy + PostgreSQL + Indexes**: Index scans → 98% faster
- **Reason**: Django's query patterns cause PostgreSQL to avoid indexes

### Dimension 4: Predicate Pushdown & Subquery Handling

**What It Determines**: How predicates and subqueries are optimized.

#### Techniques

| Technique | Description | Benefit |
|-----------|-------------|---------|
| **Predicate Pushdown** | Apply filters early | Reduce intermediate data |
| **Subquery Flattening** | Convert to join | Enable better optimization |
| **Subquery Materialization** | Execute once, cache | Avoid re-execution |
| **Apply Operators** | Correlated execution | Handle complex cases |

**Why It Matters**: Proper handling reduces intermediate result sizes by 10-1000×.

**Running Analysis**:
```bash
python scripts/3-moef/analyze_predicate_pushdown.py

# Output: results/processed/predicate_analysis.csv
```

---

## Phase 4: Causal Linking

**Purpose**: Connect observed mechanisms to performance outcomes through statistical analysis.

### Statistical Methods

#### 1. Correlation Analysis

**Question**: Does high q-error correlate with longer execution time?

```python
# Calculate Pearson correlation
correlation = pearsonr(qerrors, execution_times)

# Example result:
# r = 0.73, p < 0.001
# Interpretation: High q-error strongly predicts slow execution
```

#### 2. ANOVA

**Question**: Does join enumeration strategy significantly affect performance?

```python
# One-way ANOVA across strategies
f_stat, p_value = f_oneway(dp_times, greedy_times, heuristic_times)

# Example result:
# F(2, 66) = 42.3, p < 0.001
# Interpretation: Strategy choice has significant impact
```

#### 3. Effect Size (Cohen's d)

**Question**: How *large* is the impact?

```python
# Calculate effect size
cohens_d = (mean1 - mean2) / pooled_std

# Interpretation:
# |d| < 0.2: Small effect
# |d| < 0.5: Medium effect
# |d| < 0.8: Large effect
# |d| ≥ 0.8: Very large effect
```

**Example from paper**:
- PostgreSQL vs MySQL on Very Complex queries: **d = 2.34** (very large)
- Django vs SQLAlchemy overhead on Oracle: **d = 1.87** (very large)

#### 4. Variance Decomposition

**Question**: Which factors matter most?

From paper Table 3.7:
| Factor | Variance Explained |
|--------|-------------------|
| DBMS choice | 42% |
| ORM framework | 23% |
| Query complexity | 18% |
| Schema (indexing) | 9% |
| ORM × DBMS interaction | 5% |
| Residual | 3% |

**Interpretation**: DBMS matters most, but ORM + interactions = 28% (almost as much!)

### Running Causal Analysis

```bash
python scripts/3-moef/causal_analysis.py

# Performs:
# - Correlation tests
# - ANOVA
# - Effect size calculations
# - Variance decomposition
# - Generates causal diagrams

# Output: results/processed/causal_analysis/
```

---

## Example Walkthrough: TPC-H Query 8

Let's walk through MOEF analysis for Q8, which shows dramatic performance differences.

### Background

**Query 8**: Multi-join query with 8 tables, complex aggregation, date filtering.

**Observed Performance** (Indexed schema):
- PostgreSQL: 6.3s
- MySQL: 117s (18× slower)
- Oracle: 0.2s (with adaptive optimization)
- SQL Server: 0.4s

### Phase 1: Workload Generation ✅

All three versions (Django, SQLAlchemy, SQL) return identical results:
- 2 rows
- Same market share values
- Verification passed

### Phase 2: Plan Collection

**PostgreSQL Plan**:
```json
{
  "query_id": "Q08",
  "dbms": "postgresql",
  "plan": {
    "Node Type": "Aggregate",
    "Plan Rows": 2,
    "Actual Rows": 2,
    "Plans": [
      {
        "Node Type": "Hash Join",
        "Join Type": "Inner",
        "Plan Rows": 1234,
        "Actual Rows": 1189,
        ...
      }
    ]
  }
}
```

**Q-Error Calculation**:
- PostgreSQL: **1.4** (excellent)
- MySQL: **8.7** (poor)
- Oracle: **1.2** (excellent)
- SQL Server: **2.1** (good)

### Phase 3: Mechanism Analysis

#### Dimension 1: Join Enumeration

| DBMS | Strategy | Join Order Quality | Intermediate Rows |
|------|----------|-------------------|-------------------|
| PostgreSQL | Dynamic Programming | Optimal | Max 15K |
| MySQL | Greedy | Suboptimal | Max 750K (50× larger!) |
| Oracle | Dynamic Programming | Optimal | Max 12K |
| SQL Server | Dynamic Programming | Good | Max 18K |

**Finding**: MySQL's greedy search produces join order with massive intermediate results.

#### Dimension 2: Join Methods

| DBMS | Dominant Method | Correctness |
|------|-----------------|-------------|
| PostgreSQL | Hash Join | ✅ Correct |
| MySQL | Nested Loop → Hash | ⚠️ Initially wrong due to q-error |
| Oracle | Hash + Bitmap | ✅ Correct |
| SQL Server | Hash (parallel) | ✅ Correct |

**Finding**: MySQL's high q-error causes it to initially select Nested Loop, then fallback to Hash Join.

#### Dimension 3: Index Usage

| DBMS | Index Scans | Full Scans | Effectiveness |
|------|-------------|------------|---------------|
| PostgreSQL | 6 | 2 | ✅ Good |
| MySQL | 2 | 6 | ❌ Poor |
| Oracle | 8 | 0 | ✅ Excellent |
| SQL Server | 7 | 1 | ✅ Excellent |

**Finding**: MySQL fails to utilize available indexes effectively.

### Phase 4: Causal Linking

**Causal Chain for MySQL's Poor Performance**:

```
Greedy Join Enumeration
    ↓
Suboptimal Join Order
    ↓
Large Intermediate Results (750K vs 15K)
    ↓
Poor Cardinality Estimates (q-error = 8.7)
    ↓
Wrong Join Method Selection (Nested Loop)
    ↓
Inefficient Execution (117s vs 6.3s)
```

**Statistical Validation**:
- Correlation (join order quality vs time): r = -0.82, p < 0.001
- Effect size (PostgreSQL vs MySQL): d = 2.34 (very large)

### Mechanistic Explanation

**Why is MySQL 18× slower?**

1. **Root Cause**: Greedy join enumeration (architectural choice)
2. **Immediate Effect**: Selects join order that creates 750K intermediate rows
3. **Compounding Effect**: High cardinality estimates (q-error 8.7) mislead optimizer
4. **Final Effect**: Chooses Nested Loop join for 750K rows → catastrophic performance

**Prediction**: MySQL will struggle with any complex multi-join query (Q8, Q9, Q21).

**Validation**: Paper results confirm Q9 (935s vs 84s PostgreSQL), Q21 similar pattern.

---

## Running MOEF

### Complete Pipeline

```bash
# Run entire MOEF framework
./scripts/3-moef/run_moef_pipeline.sh

# Takes ~12 hours for all configurations
```

### Step-by-Step

```bash
# Phase 2: Collect plans
python scripts/3-moef/collect_execution_plans.py --all

# Phase 2: Calculate q-error
python scripts/3-moef/calculate_qerror.py

# Phase 3: All dimensions
python scripts/3-moef/analyze_join_enumeration.py
python scripts/3-moef/analyze_join_methods.py
python scripts/3-moef/analyze_index_usage.py
python scripts/3-moef/analyze_predicate_pushdown.py

# Phase 4: Causal analysis
python scripts/3-moef/causal_analysis.py
```

### Targeted Analysis

```bash
# Analyze specific queries only
python scripts/3-moef/collect_execution_plans.py --queries 8,9

# Analyze single DBMS
python scripts/3-moef/collect_execution_plans.py --dbms mysql

# Analyze single ORM
python scripts/3-moef/collect_execution_plans.py --orm django
```

---

## Interpreting Results

### Q-Error Values

| Range | Interpretation | Action |
|-------|----------------|--------|
| 1.0 - 2.0 | Excellent | No action needed |
| 2.0 - 5.0 | Good | Monitor complex queries |
| 5.0 - 10.0 | Poor | Investigate statistics |
| > 10.0 | Severe | Update statistics, check histograms |

### Join Strategy Impact

| Observation | Likely Cause | Recommendation |
|-------------|--------------|----------------|
| Slow on 5+ joins | Greedy enumeration | Use PostgreSQL/Oracle |
| Fast simple, slow complex | Search depth limit | Tune optimizer_search_depth (MySQL) |
| Unstable performance | Adaptive falling back | Check query patterns |

### Index Usage Patterns

| Pattern | Interpretation | Action |
|---------|----------------|--------|
| Full scans despite indexes | Cost model issue | Tune random_page_cost (PostgreSQL) |
| Indexes help some queries only | ORM-specific pattern | Review ORM query generation |
| Bitmap scans frequent | Multiple low-selectivity predicates | Consider composite indexes |

---

## Key Insights from Paper

### Finding 1: ORM Framework Dominates

**Observation**: 10-50× overhead difference between Django and SQLAlchemy on same DBMS.

**Mechanism**: Object materialization efficiency
- Django: 434s for SQL Server Q10
- SQLAlchemy: Much lower across board

**MOEF Explanation**: Django's object construction patterns are less efficient.

### Finding 2: Indexing Paradox

**Observation**: PostgreSQL + Django degrades 12% with indexes; SQLAlchemy improves 98%.

**Mechanism**: Query pattern interaction with optimizer
- Django generates patterns that cause PostgreSQL to avoid indexes
- SQLAlchemy generates patterns that enable effective index use

**MOEF Explanation**: ORM query structure affects plan selection.

### Finding 3: Workload-Type Dependency

**Observation**: SQLAlchemy better for analytical; Django better for transactional.

**Mechanism**:
- **Analytical**: Complex SQL generation, large result sets → SQLAlchemy optimized
- **Transactional**: Simple queries, frequent commits → Django optimized

**MOEF Explanation**: Different optimization strategies for different workloads.

---

## Comprehensive Documentation Suite

Now that you understand MOEF, explore these detailed guides:

### 🚀 **Quick Start**
- **[MOEF-QUICKSTART.md](MOEF-QUICKSTART.md)** - Get started in 15 minutes
  - Step-by-step tutorial
  - Your first MOEF analysis
  - Real-world example
  - Quick reference card

### 📊 **Results Interpretation**
- **[MOEF-RESULTS-GUIDE.md](MOEF-RESULTS-GUIDE.md)** - Complete interpretation guide (800+ lines)
  - Understanding comprehensive reports
  - Q-error thresholds and interpretation
  - PostgreSQL indexing paradox explained
  - Practical application with decision trees
  - Real-world case studies
  - Common patterns and anti-patterns

### 🔧 **Troubleshooting**
- **[MOEF-TROUBLESHOOTING.md](MOEF-TROUBLESHOOTING.md)** - Comprehensive troubleshooting (600+ lines)
  - Plan collection issues
  - Parser errors and fixes
  - Analysis failures
  - Performance problems
  - Data quality concerns
  - Prevention checklist

### 📚 **Additional Resources**
- **Paper Section 3.3**: Complete MOEF methodology
- **Paper Section 4.2**: Example walkthrough (Q8, Q9)
- **[API Reference](API-REFERENCE.md)**: Code documentation
- **[Implementation](../scripts/3-moef/)**: Source code and scripts

---

## Quick Troubleshooting

**For detailed troubleshooting, see [MOEF-TROUBLESHOOTING.md](MOEF-TROUBLESHOOTING.md)**

### Most Common Issues

#### No Plans Collected

```bash
# Quick diagnosis
docker ps  # Are databases running?
python scripts/1-setup/test_connections.py  # Can we connect?
ls -la results/execution_plans/  # Any plan files?
```

**Solution**: See [Plan Collection Issues](MOEF-TROUBLESHOOTING.md#plan-collection-issues)

#### Q-error is Infinite

**This is usually OK** if actual rows = 0 (empty result)

**This is a PROBLEM** if estimated = 0 and actual > 0

**Solution**: See [Q-error Issues](MOEF-TROUBLESHOOTING.md#issue-q-error-calculation-returns-inf)

#### Statistical Linking Failed

**Common cause**: Missing benchmark performance data

```bash
# Run benchmarks first
python scripts/2-benchmark/run_benchmark.py --queries 8,9

# Then re-run MOEF
./scripts/3-moef/run_moef_pipeline.sh --skip-collection
```

**Solution**: See [Statistical Linking Problems](MOEF-TROUBLESHOOTING.md#statistical-linking-problems)

---

**MOEF enables you to understand WHY performance differs, not just WHAT the differences are.**

This understanding is essential for:
- Selecting the right ORM-DBMS combination
- Optimizing query patterns
- Predicting behavior on new queries
- Making informed architectural decisions

---

**Next**: See [PAPER-ALIGNMENT.md](PAPER-ALIGNMENT.md) for mapping to paper sections.

