# ANALYSIS_PLAN.md — frozen statistical analysis plan

Status: **draft, not yet frozen.** Required by `SF1_RERUN_PLAN.md` gate G5,
which states that this document is frozen *before the first primary-campaign
timed run*. The pilot (phase 6) may inform it; once frozen, changes require
re-running anything already measured under the old rule.

Written 2026-09-02 against the harness as it stands on the campaign host.

---

## 1. The primary estimand, and the timed boundary

**Estimand.** For a given cell — one DBMS, one schema configuration, one
query — the quantity of interest is the **paired log ratio of ORM to
hand-written SQL elapsed time, within framework**:

    theta = log( t_ORM / t_SQL )

reported separately for Django and for SQLAlchemy. It is a ratio because the
systems differ by orders of magnitude in absolute time and the study makes no
cross-system absolute claims; it is logged because ratios are multiplicative
and log ratios are symmetric about zero.

**The timed boundary, written out.** `scripts/2-benchmark/run_query.py` starts
`perf_counter` immediately before calling the query function and stops it
immediately after that call returns a materialised list. So the timed region
**includes**:

- ORM query construction (building the QuerySet / Select)
- statement compilation and parameter binding
- transmission of the statement and server-side execution
- row transfer
- row materialisation into Python objects — dicts or model instances

and **excludes**:

- process start, imports, and Django/SQLAlchemy configuration
- connection establishment and session creation (the connection and session
  are created before the timed region and reused across repetitions)
- transaction begin/commit where the harness does not issue one inside the
  function
- session cleanup and connection teardown
- validation, which never runs inside a timed region

This boundary is the same for both frameworks and both access paths, which is
what makes the ratio meaningful. It is **not** the same boundary as the
statement-count microbenchmark (§7), which times a narrower region; the two
must not be reported as though they measure the same thing.

**What the estimand is not.** It is not "ORM overhead" in the sense of cost
attributable to the ORM layer alone. Server-side execution sits inside the
timed region for both arms, so the ratio is diluted by server time and is a
*lower bound* on the framework's share whenever the query is server-dominated.
The paper says this rather than implying otherwise.

---

## 2. The experimental block

A **block** is one execution of all four access paths — Django SQL, Django ORM,
SQLAlchemy SQL, SQLAlchemy ORM — against one cell, under one substitution
parameter set, in one of the four Williams sequences.

Each paired log ratio is formed **within a block**: Django's ORM time is
divided by the Django SQL time *from the same block*, never by a mean or a
median taken across blocks. This is the unit of pairing, and it is what makes
the counterbalancing do any work — a block shares its cache state, parameter
set and position in the sequence between the two arms being compared.

**The warmup uses a ninth parameter instance, never measured.** If the warmup
reused one of the eight, it would warm that set's own pages and predicates, and
the block sharing it would start warmer than the other seven - a warmup that
removes a bias from the cell by introducing one between its blocks. Q18 is the
exception and cannot be otherwise: its substitution domain is four values.

Per cell: one warmup sequence of four paths, discarded, then **eight measured
blocks** — two independently randomised permutations of the four Williams
sequences — each with its own predetermined parameter set. Nine executions per
path in total, eight retained.

The cell-level summary is the **median of the eight within-block log ratios**,
not the log of the ratio of medians. The two differ, and the first is the one
that respects the pairing.

---

### 2.1 Q18 is not exchangeable across its own blocks

Q18 is the only query whose qualification value falls **outside** its own
substitution range: the specification validates at `QUANTITY = 300` and draws
from `[312, 315]`. Set 0 is kept at 300 so that block 0 stays comparable with
every measurement this project has already taken, but it is not an exchangeable
draw alongside sets 1..7. Measured on SF1: **57 order groups at 300 against
9-10 at 312-315.**

Consequences, accepted and reported:

- Q18's across-block spread contains a genuine parameter effect that the other
  21 queries do not have, so its CV is not comparable to theirs and is excluded
  from the CV distribution in section 8.1.
- Its paired log ratio is unaffected: the pairing is *within* a block, and all
  four paths in a block share the parameter set. What changes between blocks
  changes for both arms equally.
- Its domain also has only four legal values, so eight blocks cannot use eight
  distinct instances. Declared in `tpch_paramsets._SMALL_DOMAIN`.

### 2.2 The baseline inlines parameters; the ORM binds them

The hand-written baselines interpolate substitution parameters as **literals**;
both ORMs necessarily emit **bound parameters**. This asymmetry is not an
oversight and is not corrected, for two reasons: it is what the frameworks
actually do, and it is what every measurement this project has taken so far
did, so changing it would silently break comparability with the SF10 campaign.

It does mean the contrast includes any plan difference between a literal and a
bound parameter - generic plans, parameter sniffing, plan-cache reuse. The
paper says so rather than presenting the ratio as pure framework cost, which
section 1 already requires it to do for server time.

One practical consequence worth recording: because the ORM binds, **two
different parameter sets produce byte-identical ORM SQL** and differ only in
the bound values. Any check that compares emitted SQL text alone would report a
parameterisation that never took effect as a clean pass. The regression
snapshots capture statement text and bound parameters together.

---

## 3. Are the 22 queries fixed cases or a sample?

**Decision: fixed benchmark cases, not a random sample from a workload
population.** Taken here, in writing, once, because it determines what every
interval in the paper means.

Consequences, accepted:

- The query-clustered bootstrap (`cluster_boot_ci` in `phase_b.py`) resamples
  queries to characterise **sensitivity of the summary to which queries are
  included**, not to support inference about a population of workloads. Its
  interval is described in exactly those terms.
- No claim of the form "ORM overhead in analytical workloads is X%" is made.
  Claims are of the form "across the 22 TPC-H-derived queries, under this
  envelope, the median overhead was X%".
- TPC-C's five transaction types are likewise five fixed cases, and §5 of the
  rerun plan already confines them to descriptive reporting.

---

## 4. Primary contrasts and multiplicity

**Primary family** — three contrasts, decided in advance:

1. **ORM versus SQL, within framework, pooled across queries** — one contrast
   per (system, schema, framework): is theta different from zero.
2. **Django versus SQLAlchemy**, on the same cell: the difference of the two
   paired log ratios.
3. **Indexed versus non-indexed**, within system and framework: does the
   physical design change the ORM's relative cost.

Everything else is **exploratory** and labelled as such in the paper: per-query
effects, cross-system comparisons of theta, the outlier case studies
(Q15/Q17/Q13), and anything suggested by looking at the data.

**Multiplicity.** Holm–Bonferroni across the primary family only, at
family-wise alpha = 0.05. Exploratory results carry no correction and no
p-values, only intervals, and are described as exploratory in the text and in
the table captions.

**Cross-system comparison is not in the primary family** and never becomes a
performance ranking. The systems differ in edition, licence, supported
platform and — for Oracle here — in running on a platform its vendor does not
support. The paper compares *how ORM cost behaves* across systems, not the
systems.

---

## 5. Failed validation, errors, and missing cells

Every one of the 432 cells is emitted. A cell carries `status` and a
`status_note` in words. The summary rules:

- **`not_run`** — never measured. Excluded from every summary; counted and
  named in the completeness table. Never imputed.
- **`error`** — the path raised. Excluded from ratio summaries; the exception
  type is reported. A path that raises because the ORM *cannot express the
  query* (Q13 on the commercial system and Oracle, C17) is a **result**, is
  reported as such in the text, and is never shown as a gap.
- **`validation_failed`** — measured but a check did not pass. Excluded from
  the primary summaries, reported separately, and never silently pooled. The
  C23 cells are the precedent for why this rule exists.
- **`censored`** — see §6.

No summary in the paper is computed over a set that mixes these silently. Each
table states its N and the number excluded, by reason.

---

## 6. The censoring rule

A timed-out run is neither a missing value nor an observation at the ceiling.

- The ceiling is **read back off the server before each path is timed** and a
  path that is unbounded is not timed at all (C32). A ceiling that was set but
  not in force has produced a number indistinguishable from a measurement
  once already.
- A censored path yields a one-sided bound: `theta > log(ceiling / t_SQL)`.
- The ceiling value **never enters a median as though observed**.
- A censored cell is retried once at a predefined higher ceiling; a
  persistently censored pair is reported as a bound.
- Any aggregate containing censored observations uses a bounded summary
  (median with censored observations ordered above all observed values, which
  is valid because censoring is one-sided and upward) and states the count.

**Two kinds of censoring, recorded distinctly:**

- **Fully censored cell** — all four paths exceed the ceiling. Q17, Q20 and
  Q21 non-indexed are expected to be so on all four systems. Declared in
  advance with their EXPLAIN evidence; not rediscovered at 36 executions.
- **Partially censored cell** — one path exceeds while others complete. Q13
  non-indexed on PostgreSQL and MySQL: Django's ORM arm exceeds any practical
  ceiling while the other three return in about two seconds. Django's ratio
  becomes a bound; **SQLAlchemy's ratio from that cell is intact and is
  used.** Reporting the whole cell as missing would discard three good paths.

---

## 7. The microbenchmark

The statement-count microbenchmark times a narrower region than the grid and
is reported separately, never pooled with it. Its per-statement figures
(0.33 ms Django, 0.26 ms SQLAlchemy from the earlier campaign) are
**reference values, not validation targets**: new hardware, drivers and
framework versions may legitimately move them.

Its replication count is set from the pilot's variance, not chosen in advance.

---


## 8. Go/no-go thresholds for the phase 6 pilot

**These are fixed here, before the pilot runs.** `SF1_RERUN_PLAN.md` §3
requires it in those words, and the requirement is not a formality: a
threshold chosen after seeing the pilot's output is a description of that
output, and it cannot fail. Written 2026-09-02, before any pilot execution.

They are anchored in the **SF10 campaign's own published CV distribution**,
which is historical data from a completed campaign, not pilot data. Across its
776 recorded per-path CVs:

| statistic | SF10 campaign |
|---|---|
| median CV | 3.4 % |
| p75 | 8.0 % |
| p90 | 19.6 % |
| p95 | 29.5 % |
| max | 152.5 % |
| share above 15 % | 14.8 % |

That campaign ran under Docker on a shared laptop with three measured
repetitions. The new envelope — a dedicated host, two cpuset-pinned physical
cores, SMT disabled, turbo disabled, performance governor, one DBMS resident —
exists precisely to improve on it. So the thresholds are set to require that
it did: no worse at the median, and materially better in the tail. If the
controls bought nothing, that is a finding about the envelope and it should
stop the campaign rather than be absorbed into it.

### 8.1 Noise: the CV bound

Computed over every measured path in the pilot that is not pre-declared
censored (§6), each path's CV taken across its eight retained blocks.

| | **go** | **stop and diagnose** |
|---|---|---|
| median CV | ≤ 5.0 % | > 5.0 % |
| p90 CV | ≤ 15.0 % | > 15.0 % |
| share of paths with CV > 25 % | ≤ 5 % | > 5 % |

Q18 is excluded from this distribution for the reason in section 2.1.

All three must hold. The p90 bound is the one doing the work: the median was
already acceptable at SF10, and it was the tail — a fifth of all paths above
10 % — that made per-query claims fragile.

**A CV computed across eight blocks with eight different parameter sets is not
the same quantity as one computed across eight repetitions of a single
parameter set.** It contains genuine parameter-to-parameter variation in
addition to measurement noise, and is therefore expected to be larger. This is
intended: the estimand is the query, not one instance of it. The bound above
applies to this larger quantity, which is why it is not set tighter than the
SF10 numbers would allow.

### 8.2 Completeness: the missing-cell rate

Two levels, because they gate different things.

**Pilot (gates the campaign).** Across the pilot's cells, the number of
executions that fail for a reason **not already declared** in §6 must be
**zero**. An unplanned failure is diagnosed and fixed before the campaign
starts; it is not carried into it as a known gap. This is deliberately strict:
the pilot is 12 cells, a single unexplained failure there projects to roughly
36 across the grid, and every reload in this project's history has surfaced
new defects (C27–C30).

**Campaign (gates how results are reported).** Of the 432 cells, at most
**5 %** — 21 cells — may end as `not_run` for reasons other than pre-declared
censoring (§6) or C17 inexpressibility. Above 5 %, the completeness table
leads the results section and no summary is described as grid-wide; pooled
figures are reported per-system only, over the systems that are complete.

### 8.3 The timeout ceiling, and its margin

The ceiling is a **parameter of the experiment**, and both it and the margin
it left are recorded, per the plan's §2.

- **Default ceiling: 900 s per path**, the value the SF10 campaign used, so
  the two campaigns' censoring decisions stay comparable.
- **The pilot validates the default rather than choosing it freely.** Go if
  every pilot path that is not pre-declared censored completes with a margin
  of at least **5×** — that is, observed maximum ≤ 180 s. A path finishing
  between 180 s and 900 s is a warning: the ceiling is raised for that query
  on that system before the campaign, and the pilot measurements for it are
  excluded from the primary campaign under the plan's own rule.
- **Retry ceiling for a censored cell: 2700 s, applied once** (§6's "predefined
  higher ceiling" — 3× the default). Beyond that the cell is reported as a
  bound.
- **The ceiling is read back off the server before each path is timed** (C32).
  This is not part of the go/no-go; it is unconditional.

Recorded per cell: ceiling value, observed maximum, and margin = ceiling /
observed maximum.

### 8.4 Microbenchmark replication

Predefined as a **rule**, with the number it produces coming from the pilot's
variance:

    n = smallest block size for which the half-width of the 95% CI on the
        per-block mean latency is <= 10% of the smallest per-statement
        increment the pilot observed

with a floor of **100** transactions per block and a cap of **2000**. If the
cap is reached the slope is reported with its interval and explicitly not
claimed to be resolved at that precision.

### 8.5 What happens if a threshold is missed

The pilot's purpose is to be able to fail. If any bound in §8.1–8.3 is missed:

1. The cause is diagnosed before any primary-campaign execution.
2. If the protocol changes as a result, **every pilot measurement is excluded
   from the primary campaign** — the plan's §3 rule, applied without
   exception.
3. The miss, the diagnosis and the change are written into this document and
   into `docs/CORRECTIONS.md`, and reported in the paper's methods section.
   A pilot that failed and was fixed is a stronger disclosure than a pilot
   that is not mentioned.

---

## 9. What is still open

- Replication count for the microbenchmark — the *rule* is fixed in §8.4; the
  *number* comes from the pilot.
- The ceiling — the *default and its validation rule* are fixed in §8.3; any
  per-query raise comes from the pilot.
- Confirmation that the bounded-summary method in §6 is implemented in
  `phase_b.py` rather than assumed.
- Whether sessions are recreated or cleared between blocks (plan §5: "one
  rule, applied everywhere"). Must be decided at the freeze, not per system.
