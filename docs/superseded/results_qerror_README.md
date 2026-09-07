# Q-error Directory

This directory contains q-error calculations for cardinality estimation accuracy.

## What is Q-error?

Q-error measures the quality of cardinality estimates made by the query optimizer:

```
q_error = max(estimated_rows / actual_rows, actual_rows / estimated_rows)
```

- **q-error = 1.0**: Perfect estimate
- **q-error < 2.0**: Good estimate
- **q-error > 10.0**: Poor estimate (order of magnitude off)

## Files

### `qerror_by_query.csv`
Per-query, per-operator q-error values

**Columns**:
- `query_id`: Query number
- `orm`: ORM implementation
- `dbms`: Database system
- `operator`: Plan node type (Join, Scan, etc.)
- `estimated_rows`: Optimizer's cardinality estimate
- `actual_rows`: Actual row count from execution
- `q_error`: Calculated q-error value
- `underestimate`: Boolean (estimated < actual)

### `qerror_summary.csv`
Aggregated q-error statistics

**Columns**:
- `query_id`: Query number
- `orm`: ORM implementation
- `dbms`: Database system
- `mean_qerror`: Average q-error across all operators
- `median_qerror`: Median q-error
- `max_qerror`: Worst q-error
- `operators_analyzed`: Number of plan nodes analyzed
- `underestimate_rate`: Percentage of underestimates

## Generation

```bash
# Calculate q-error from execution plans
python scripts/3-moef/calculate_qerror.py \
    --plans results/execution_plans/ \
    --output results/qerror/

# Generate q-error visualization (Figure 8)
python scripts/4-analysis/generate_figures.py \
    --figure 8 \
    --qerror results/qerror/qerror_summary.csv
```

## Interpretation

### Q-error Ranges

| Range | Quality | Interpretation |
|-------|---------|----------------|
| 1.0 - 2.0 | Excellent | Within 2x of actual |
| 2.0 - 5.0 | Good | Within 5x of actual |
| 5.0 - 10.0 | Fair | Within order of magnitude |
| > 10.0 | Poor | More than 10x off |

### Impact on Performance

High q-error often correlates with:
- Suboptimal join orders
- Wrong join method selection (e.g., nested loop instead of hash join)
- Poor index utilization
- Larger performance overhead

## Paper Reference

**Section 5.2**: "Q-error Analysis"  
**Figure 8**: "Q-error Distribution by Database System"

## See Also

- [MOEF Framework Documentation](../../docs/04-MOEF-FRAMEWORK.md)
- [Execution Plans README](../execution_plans/README.md)
- [Results README](../README.md)

## References

- Leis et al. (2015): "How Good Are Query Optimizers, Really?"
- Marcus et al. (2019): "Deep Reinforcement Learning for Join Order Enumeration"

