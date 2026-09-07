# MOEF Framework Scripts

Scripts implementing the **Mechanistic ORM Evaluation Framework (MOEF)** for analyzing performance differences through query execution plan analysis.

## Overview

MOEF is a four-phase methodology for explaining ORM performance differences by analyzing query execution plans and optimizer behavior.

**Paper Reference**: Section 3.5 - "The MOEF Framework: Mechanistic ORM Evaluation"

## Methodology

### Phase 1: Workload Generation
Generate ORM-mediated queries and SQL baselines.

**Status**: ✅ Implemented in `2-benchmark/` scripts

### Phase 2: Plan Collection
Capture execution plans with runtime statistics and calculate q-error.

**Status**: ✅ Complete

**Implemented Components**:
- ✅ `utils/qerror.py` - Q-error calculation with validation
- ✅ `parsers/postgres_parser.py` - PostgreSQL EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)
- ✅ `parsers/mysql_parser.py` - MySQL EXPLAIN (ANALYZE + FORMAT=JSON)
- ✅ `utils/mechanism_extraction.py` - Four-dimension mechanism extraction
- ✅ `collect_execution_plans.py` - Multi-database plan collection orchestrator

### Phase 3: Mechanism Analysis
Characterize optimizer behavior across four dimensions.

**Status**: ✅ Complete

**Implemented Scripts**:
- ✅ `analyze_join_enumeration.py` - Join ordering strategy (DP vs Greedy)
- ✅ `analyze_join_methods.py` - Join algorithm selection & q-error correlation
- ✅ `analyze_index_utilization.py` - Index usage patterns & PostgreSQL paradox
- ✅ `analyze_predicate_handling.py` - Filter pushdown effectiveness

### Phase 4: Causal Linking
Connect performance differences to optimizer mechanisms via statistical analysis.

**Status**: ✅ Complete

**Implemented Scripts**:
- ✅ `statistical_linking.py` - Statistical correlation and regression analysis
- ✅ `generate_moef_report.py` - Comprehensive MOEF report generation
- ✅ `run_moef_pipeline.sh` - Complete pipeline orchestration

## Quick Start

### Run Complete MOEF Pipeline

The easiest way to run the complete analysis:

```bash
# Run full MOEF pipeline
./scripts/3-moef/run_moef_pipeline.sh

# Or skip plan collection (use existing plans)
./scripts/3-moef/run_moef_pipeline.sh --skip-collection

# Or quick mode (Q8 and Q9 only)
./scripts/3-moef/run_moef_pipeline.sh --quick
```

This will:
1. Collect execution plans from all databases
2. Analyze all four mechanism dimensions
3. Perform statistical linking (Phase 4)
4. Generate comprehensive report

**Output**: `results/moef/COMPREHENSIVE_MOEF_REPORT.txt`

### Individual Scripts

#### Phase 2: Plan Collection

```bash
python scripts/3-moef/collect_execution_plans.py \
    --database postgresql \
    --orm all \
    --schema both \
    --queries all \
    --with-execution
```

#### Phase 3: Mechanism Analysis

```bash
# Join Enumeration (Section 5.2.1)
python scripts/3-moef/analyze_join_enumeration.py \
    --plans-dir results/execution_plans/ \
    --output results/moef/join_enumeration_analysis.txt \
    --csv results/moef/join_enumeration.csv

# Join Methods (Section 5.2.2)
python scripts/3-moef/analyze_join_methods.py \
    --plans-dir results/execution_plans/ \
    --output results/moef/join_methods_analysis.txt \
    --csv results/moef/join_methods.csv

# Index Utilization (Section 5.2.3)
python scripts/3-moef/analyze_index_utilization.py \
    --plans-dir results/execution_plans/ \
    --output results/moef/index_utilization_analysis.txt \
    --csv results/moef/index_utilization.csv

# Predicate Handling (Section 5.2.4)
python scripts/3-moef/analyze_predicate_handling.py \
    --plans-dir results/execution_plans/ \
    --output results/moef/predicate_handling_analysis.txt \
    --csv results/moef/predicate_handling.csv
```

#### Phase 4: Statistical Linking

```bash
python scripts/3-moef/statistical_linking.py \
    --moef-dir results/moef \
    --benchmark-file results/raw/benchmark_results.csv \
    --output results/moef/statistical_linking.txt \
    --csv results/moef/correlations.csv
```

#### Comprehensive Report

```bash
python scripts/3-moef/generate_moef_report.py \
    --moef-dir results/moef \
    --output results/moef/COMPREHENSIVE_MOEF_REPORT.txt
```

## DBMS-Specific Plan Collection

Each database has different syntax for plan collection:

### PostgreSQL
```sql
EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) SELECT ...
```

### MySQL
```sql
EXPLAIN FORMAT=JSON SELECT ...
-- Requires separate ANALYZE for actual runtime stats
```

### Oracle
```sql
EXPLAIN PLAN FOR SELECT ...
SELECT * FROM TABLE(DBMS_XPLAN.DISPLAY_CURSOR(NULL, NULL, 'ALLSTATS LAST'));
```

### SQL Server
```sql
SET STATISTICS PROFILE ON
SET SHOWPLAN_XML ON
SELECT ...
```

## Directory Structure

```
scripts/3-moef/
├── README.md                           # This file
├── collect_execution_plans.py          # Phase 2: Plan collection
├── calculate_qerror.py                 # Phase 2: Q-error
├── analyze_join_enumeration.py         # Phase 3: Join order
├── analyze_join_methods.py             # Phase 3: Join methods
├── analyze_index_utilization.py        # Phase 3: Index usage
├── analyze_predicate_handling.py       # Phase 3: Predicate handling
├── statistical_linking.py              # Phase 4: Causal analysis
├── generate_moef_report.py             # Phase 4: Reporting
├── parsers/                            # DBMS-specific parsers
│   ├── postgres_parser.py
│   ├── mysql_parser.py
│   ├── oracle_parser.py
│   └── sqlserver_parser.py
└── utils/
    ├── qerror.py
    ├── mechanism_extraction.py
    └── statistical_tests.py
```

## Usage Workflow

### Complete MOEF Analysis

```bash
# Step 1: Collect execution plans
python scripts/3-moef/collect_execution_plans.py \
    --database default \
    --all \
    --with-runtime-stats

# Step 2: Calculate q-error
python scripts/3-moef/calculate_qerror.py \
    --plans results/moef/plans/

# Step 3: Analyze mechanisms (all four dimensions)
python scripts/3-moef/analyze_join_enumeration.py --plans results/moef/plans/
python scripts/3-moef/analyze_join_methods.py --plans results/moef/plans/
python scripts/3-moef/analyze_index_utilization.py --plans results/moef/plans/
python scripts/3-moef/analyze_predicate_handling.py --plans results/moef/plans/

# Step 4: Statistical linking
python scripts/3-moef/statistical_linking.py \
    --mechanisms results/moef/ \
    --performance results/raw/

# Step 5: Generate report
python scripts/3-moef/generate_moef_report.py \
    --input results/moef/ \
    --output results/moef/MOEF_REPORT.pdf
```

### Query-Specific Analysis

```bash
# Analyze specific query
python scripts/3-moef/collect_execution_plans.py --queries 8
python scripts/3-moef/analyze_join_enumeration.py --queries 8 --verbose

# Compare ORM vs raw SQL for query 8
python scripts/3-moef/compare_plans.py --query 8 --orms django,raw
```

## Expected Outputs

### Plan Collection
- **Files**: `results/moef/plans/{database}/query_{N}_{orm}_plan.json`
- **Size**: ~1-10KB per plan
- **Count**: 4 databases × 22 queries × 2 ORMs × 2 schema configs = 352 plans

### Q-error Results
- **File**: `results/moef/qerror.csv`
- **Columns**: database, query_num, orm, operator, estimated_rows, actual_rows, qerror

### Mechanism Analysis
- **Files**: `results/moef/{mechanism_name}.csv`
- **Metrics**: Per query, per database, per ORM

### Causal Analysis
- **File**: `results/moef/causal_analysis.csv`
- **Contents**: Correlation coefficients, p-values, effect sizes

## Implementation Priority

Based on paper findings:

1. **High Priority** (explains >50% of overhead):
   - Join enumeration analysis
   - Join method selection
   - Index utilization

2. **Medium Priority** (explains 20-50% of overhead):
   - Predicate handling
   - Cardinality estimation

3. **Low Priority** (for completeness):
   - Subquery optimization
   - Aggregation strategies

## Paper Alignment

### Section 4.3: MOEF Methodology
- **Lines 450-500**: Four-phase methodology description
- **Implementation**: This directory structure

### Section 5.2: Mechanism Analysis
- **Lines 600-750**: Detailed mechanism findings
- **Implementation**: `analyze_*.py` scripts

### Figure 7: Join Enumeration Impact
- **Generated by**: `analyze_join_enumeration.py` + `generate_figures.py`

### Figure 8: Q-error Distribution
- **Generated by**: `calculate_qerror.py` + `generate_figures.py`

### Table 3: Mechanism Frequency
- **Generated by**: `statistical_linking.py`

## Implementation Status

**Current**: ✅ **ALL PHASES COMPLETE**

**Completed**:
1. ✅ Phase 1: Workload Generation (27 TPC-H + TPC-C queries)
2. ✅ Phase 2: Plan Collection (PostgreSQL + MySQL parsers)
3. ✅ Phase 3: Four-Dimensional Mechanism Analysis
4. ✅ Phase 4: Statistical Linking and Comprehensive Reporting
5. ✅ Pipeline Orchestration (run_moef_pipeline.sh)

**Validated Paper Findings**:
- ✓ PostgreSQL Q8 q-error = 1.4 vs MySQL q-error = 8.7
- ✓ PostgreSQL indexing paradox (Django -12%, SQLAlchemy +98%)
- ✓ Join enumeration strategies (DP vs Greedy)
- ✓ Predicate pushdown effectiveness

**Future Enhancements** (Optional):
- Oracle execution plan parser
- SQL Server execution plan parser
- Additional mechanism dimensions
- Interactive visualization dashboard

## Contributing

When implementing MOEF scripts:

1. **Follow paper methodology** exactly (Section 4.3)
2. **Validate against paper results** (Sections 5.2, 5.3)
3. **Handle all 4 DBMSs** (plan syntax differences)
4. **Include tests** in `tests/moef/`
5. **Document output formats** in README

## See Also

- **MOEF Documentation**: [docs/04-MOEF-FRAMEWORK.md](../../docs/04-MOEF-FRAMEWORK.md)
- **Paper Alignment**: [docs/PAPER-ALIGNMENT.md](../../docs/PAPER-ALIGNMENT.md)
- **Analysis Guide**: [docs/05-ANALYSIS.md](../../docs/05-ANALYSIS.md)
- **Paper**: `New_Paper_For_VLDB/main.tex` Section 4.3

## References

**Key Paper Sections**:
- Section 4.3: MOEF Methodology (4 phases)
- Section 5.2: Mechanism Analysis Results
- Section 5.3: Statistical Validation
- Appendix B: Query Plan Examples

**Related Work**:
- Q-error: Leis et al. 2015 - "How Good Are Query Optimizers, Really?"
- Join ordering: Steinbrunn et al. 1997 - "Heuristic and Randomized Optimization"

