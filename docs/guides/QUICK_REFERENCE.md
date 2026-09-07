# Quick Reference Card


> **Current as of the SF10 four-system campaign.** Dataset generation moved
> to DuckDB (`scripts/1-setup/generate_tpch_duckdb.py`) and the loaders now
> stream from it, so any `tpch-dbgen` / `.tbl` / `load_data_*.sh` step below
> has been replaced. `REPRODUCE.md` in the repository root is the path that
> was actually used to produce `results/all_results.csv`.

**ORM Benchmark Reproducibility Package v1.0.0**

---

## 🚀 Quick Start (30 minutes)

```bash
# 1. Setup
# superseded - see REPRODUCE.md

# 2. Run quick test
# superseded - see REPRODUCE.md

# 3. Validate
./validate_reproducibility.sh
```

---

## 📁 Key Files

| File | Purpose |
|------|---------|
| `README.md` | Project overview |
| `REPRODUCIBILITY.md` | Complete reproduction guide |
| `docs/PAPER-ALIGNMENT.md` | Code ↔ Paper mapping |
| `docs/04-MOEF-FRAMEWORK.md` | MOEF methodology |
| `CITATION.cff` | Citation information |
| `CHANGELOG.md` | Version history |

---

## 🛠️ Main Commands

### Setup
```bash
# superseded - see REPRODUCE.md   # Full setup (one DB at a time)
# superseded - see REPRODUCE.md  # Quick setup (PostgreSQL only)
```

### Run Benchmarks
```bash
# superseded - see REPRODUCE.md  # 30 min validation
# superseded - see REPRODUCE.md        # one DBMS, one schema
# superseded - see REPRODUCE.md        # full four-system campaign
```

### Validate
```bash
./validate_reproducibility.sh        # Standard validation
./validate_reproducibility.sh --full # Full validation with results
```

---

## 📂 Directory Structure

```
orm-benchmark-reproducibility/
├── scripts/
│   ├── 1-setup/      → Data generation & loading
│   ├── 2-benchmark/  → Benchmark execution
│   ├── 3-moef/       → MOEF framework
│   ├── 4-analysis/   → Results & figures
│   └── utils/        → Utilities
├── results/
│   ├── raw/          → Raw benchmark data
│   ├── processed/    → Aggregated results
│   ├── figures/      → Generated figures
│   └── metadata/     → Experiment info
├── docs/             → Documentation
└── tests/            → Test suites
```

---

## 🔧 Common Tasks

### Generate Figures
```bash
python scripts/4-analysis/generate_figures.py --all
```

### Test Database Connections
```bash
python scripts/utils/test_connections.py
```

### Manage Indexes
```bash
python scripts/1-setup/manage_indexes.py --action create --database default
python scripts/1-setup/manage_indexes.py --action drop --database default
```

### Validate Results
```bash
python scripts/4-analysis/validate_results.py --check-data-integrity
```

---

## 🗃️ Database Aliases

| Alias | Database |
|-------|----------|
| `default` | PostgreSQL 14 |
| `mysql` | MySQL 8.0 |
| `oracle` | Oracle 19c |
| `sqlserver` | SQL Server 2019 |

---

## 🐳 Docker Commands

```bash
# Start all databases
docker-compose up -d

# Check status
docker ps

# View logs
docker logs orm-benchmark-postgres
docker logs orm-benchmark-mysql

# Restart specific database
docker-compose restart postgres

# Stop all
docker-compose down
```

---

## 📊 Benchmark Configurations

### Quick Test
- **Time**: 30 minutes
- **Queries**: 2 (Q1, Q6)
- **Databases**: PostgreSQL
- **ORMs**: Django
- **Reps**: 3

### Medium Test
- **Time**: 4 hours
- **Queries**: 6 (Q1, Q6, Q8, Q9, Q12, Q14)
- **Databases**: PostgreSQL, MySQL
- **ORMs**: Django, SQLAlchemy
- **Reps**: 5

### Full Reproduction
- **Time**: ~7 days
- **Queries**: 22 (all TPC-H)
- **Databases**: PostgreSQL, MySQL, Oracle, SQL Server
- **ORMs**: Django, SQLAlchemy
- **Configs**: 432 total
- **Reps**: 5

---

## 🔍 Troubleshooting

### Database won't start
```bash
docker-compose restart postgres
./scripts/1-setup/wait_for_databases.sh
```

### Connection errors
```bash
python scripts/utils/test_connections.py
docker logs orm-benchmark-postgres
```

### Out of disk space
```bash
./scripts/utils/cleanup.sh --results
docker system prune -f
```

### Python import errors
```bash
source venv/bin/activate
pip install -r requirements.txt
```

---

## 📖 Documentation Index

| Document | Description |
|----------|-------------|
| [01-GETTING-STARTED](docs/01-GETTING-STARTED.md) | 10-minute setup guide |
| [02-INSTALLATION](docs/02-INSTALLATION.md) | Detailed installation |
| [03-RUNNING-BENCHMARKS](docs/03-RUNNING-BENCHMARKS.md) | Benchmark execution |
| [04-MOEF-FRAMEWORK](docs/04-MOEF-FRAMEWORK.md) | MOEF methodology |
| [05-ANALYSIS](docs/05-ANALYSIS.md) | Results analysis |
| [06-TROUBLESHOOTING](docs/06-TROUBLESHOOTING.md) | Common issues |
| [07-EXTENDING](docs/07-EXTENDING.md) | Extending the package |
| [PAPER-ALIGNMENT](docs/PAPER-ALIGNMENT.md) | Code ↔ Paper mapping |

---

## 📈 Result Files

| File | Location | Description |
|------|----------|-------------|
| Raw benchmarks | `results/raw/` | Raw CSV files |
| Summary stats | `results/processed/` | Aggregated results |
| Figures | `results/figures/` | Paper figures |
| Query plans | `results/execution_plans/` | EXPLAIN output |
| Q-error | `results/qerror/` | Cardinality estimates |

---

## ⏱️ Time Estimates

| Task | Duration |
|------|----------|
| Setup (quick) | 10-15 min |
| Setup (full) | 30-45 min |
| Quick test | 30 min |
| Medium test | 4 hours |
| Full reproduction | 7 days |
| Generate figures | 5-10 min |
| Validation | 5 min |

---

## 💻 Hardware Requirements

### Quick Test
- **CPU**: 4 cores
- **RAM**: 8 GB
- **Disk**: 10 GB
- **Network**: Not required

### Full Reproduction
- **CPU**: 8+ cores recommended
- **RAM**: 16 GB minimum, 32 GB recommended
- **Disk**: 50 GB minimum, 100 GB recommended
- **Network**: Not required (all local)

---

## 🎯 Paper Figures

| Figure | Script | Time |
|--------|--------|------|
| Figure 4 | `generate_figures.py --figure 4` | 30 sec |
| Figure 5 | `generate_figures.py --figure 5` | 30 sec |
| Figure 6 | `generate_figures.py --figure 6` | 30 sec |
| Figure 7 | `generate_figures.py --figure 7` | 30 sec |
| Figure 8 | `generate_figures.py --figure 8` | 30 sec |
| Figure 9 | `generate_figures.py --figure 9` | 30 sec |
| All | `generate_figures.py --all` | 3 min |

---

## 📞 Getting Help

1. **Check documentation**: `docs/06-TROUBLESHOOTING.md`
2. **Validate setup**: `./validate_reproducibility.sh`
3. **Check logs**: `logs/` directory
4. **Review**: `REPRODUCIBILITY.md`

---

## 🏷️ Version Information

- **Version**: 1.0.0
- **Release Date**: 2024-12-13
- **Status**: Submission-ready
- **License**: MIT

---

## 📚 Citation

The manuscript this artifact accompanies is under review and not
published. Citing it as a journal article would assert a record that does
not exist, so cite the artifact until there is one:

```bibtex
@software{nasr_orm_overhead_artifact,
  title  = {ORM overhead on four database systems: harness, results and
            correction register},
  author = {Nasr, Mahmoud and El-Ramly, Mohammed and Abdelqawy, Desoky},
  year   = {2026},
  url    = {https://github.com/mahmoodnasr/orm-overhead-artifact}
}
```

See `CITATION.cff` for complete citation information.

---

**Quick Links**:
- 📖 [Full Documentation](docs/)
- 🔄 [Reproducibility Guide](REPRODUCIBILITY.md)
- 📊 [Paper Alignment](docs/PAPER-ALIGNMENT.md)
- 🎓 [MOEF Framework](docs/04-MOEF-FRAMEWORK.md)

---

*Last Updated: 2024-12-13*  
*Package Version: 1.0.0*

