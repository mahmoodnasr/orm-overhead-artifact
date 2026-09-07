# Contributing to TPC-H ORM Benchmark


> **Current as of the SF10 four-system campaign.** Dataset generation moved
> to DuckDB (`scripts/1-setup/generate_tpch_duckdb.py`) and the loaders now
> stream from it, so any `tpch-dbgen` / `.tbl` / `load_data_*.sh` step below
> has been replaced. `REPRODUCE.md` in the repository root is the path that
> was actually used to produce `results/all_results.csv`.

Thank you for your interest in contributing! This document provides guidelines for contributing to the project.

## 🤝 How to Contribute

### Reporting Issues

If you find a bug or have a suggestion:

1. **Check existing issues** to avoid duplicates
2. **Create a new issue** with:
   - Clear title and description
   - Steps to reproduce (for bugs)
   - Expected vs actual behavior
   - Environment details (OS, Python version, Docker version)
   - Relevant logs or error messages

### Submitting Changes

1. **Fork the repository**
2. **Create a feature branch**: `git checkout -b feature/your-feature-name`
3. **Make your changes** following the guidelines below
4. **Test your changes** thoroughly
5. **Commit with clear messages**: `git commit -m "Add feature: description"`
6. **Push to your fork**: `git push origin feature/your-feature-name`
7. **Create a Pull Request** with a clear description

## 📝 Development Guidelines

### Code Style

- **Python**: Follow PEP 8 style guide
- **Line length**: Maximum 100 characters
- **Imports**: Group by standard library, third-party, local
- **Docstrings**: Use for all functions, classes, and modules

Example:
```python
def run_query_orm(using='default'):
    """
    Execute TPC-H Query via Django ORM.
    
    Args:
        using (str): Database alias to use
        
    Returns:
        list: Query results as list of dictionaries
    """
    # Implementation
    pass
```

### Adding New Queries

When adding or modifying TPC-H queries:

1. **Standard version**: Create `qXX.py` with PostgreSQL/MySQL compatible syntax
2. **Database-specific versions**: Create `qXX_oracle.py` or `qXX_sqlserver.py` if needed
3. **Both implementations**: Include both `run_query_orm()` and `run_query_sql()`
4. **Metadata**: Include `get_query_info()` with query details
5. **Comments**: Document any SQL syntax differences

Example structure:
```python
"""TPC-H Query XX - Description"""
from django.db.models import Count, Sum, Avg
from django_app.models import Customer, Orders

def run_query_orm(using='default'):
    """Execute via Django ORM."""
    # ORM implementation
    pass

def run_query_sql(connection):
    """Execute via direct SQL."""
    sql = """
    SELECT ...
    """
    with connection.cursor() as cursor:
        cursor.execute(sql)
        columns = [col[0] for col in cursor.description]
        results = [dict(zip(columns, row)) for row in cursor.fetchall()]
    return results

def get_query_info():
    """Return query metadata."""
    return {
        'number': XX,
        'name': 'Query Name',
        'description': 'Brief description',
        'complexity': 'Simple|Medium|Complex|Very Complex',
    }
```

### Adding Database Support

To add a new database system:

1. **Docker configuration**: Add to `docker-compose.yml` and create `docker/[dbname]/`
2. **Django settings**: Add database configuration to `django_app/settings.py`
3. **Setup scripts**: Create `scripts/1-setup/load_<dbname>.py`
4. **Index definitions**: Add `data/indexes/[dbname]_indexes.sql`
5. **Query loader**: Update `django_app/queries/__init__.py` if syntax differs
6. **Documentation**: Update README.md and QUICKSTART.md
7. **Test**: Verify all 22 queries work

### Testing

Before submitting:

```bash
# Test database connections
python scripts/test_connections.py

# Run a quick benchmark test
./venv/bin/python scripts/benchmark/run_benchmark.py \
  --database postgres \
  --queries 1 \
  --repetitions 2

# Verify results format
head results/raw/all_results.csv
```

### Documentation

- Update README.md for major features
- Update QUICKSTART.md if setup process changes
- Add comments for complex logic
- Update docstrings when changing function signatures

## 🐛 Bug Fixes

When fixing bugs:

1. **Describe the bug** in your PR description
2. **Include steps to reproduce**
3. **Explain the fix** and why it works
4. **Test the fix** on all affected databases
5. **Check for side effects** on other queries

## ✨ Feature Requests

For new features:

1. **Open an issue first** to discuss the feature
2. **Explain the use case** and benefits
3. **Consider backwards compatibility**
4. **Provide implementation details** if possible

## 🔍 Code Review Process

Pull requests will be reviewed for:

- **Correctness**: Does it work as intended?
- **Performance**: Does it impact benchmark accuracy?
- **Code quality**: Is it readable and maintainable?
- **Testing**: Is it adequately tested?
- **Documentation**: Is it properly documented?

## 📋 Checklist for PRs

- [ ] Code follows project style guidelines
- [ ] All tests pass
- [ ] Documentation is updated
- [ ] Commit messages are clear
- [ ] No unnecessary files included
- [ ] Changes are backwards compatible (or documented)

## 🎯 Areas for Contribution

We especially welcome contributions in:

### High Priority
- **Additional databases**: TimescaleDB, CockroachDB, etc.
- **Performance optimizations**: Faster data loading, query execution
- **Analysis tools**: Better visualization, statistical analysis
- **Documentation**: Tutorials, examples, troubleshooting guides

### Medium Priority
- **Query optimizations**: Better ORM query implementations
- **Test coverage**: Unit tests, integration tests
- **CI/CD**: Automated testing, Docker image building
- **Monitoring**: Real-time progress tracking

### Nice to Have
- **Web interface**: Dashboard for running benchmarks
- **Result comparison**: Compare across database versions
- **Query plan analysis**: Automatic EXPLAIN analysis
- **Scalability testing**: Different scale factors

## 🚀 Development Setup

```bash
# Clone your fork
git clone https://github.com/YOUR_USERNAME/orm-benchmark-reproducibility.git
cd orm-benchmark-reproducibility

# Add upstream remote
git remote add upstream https://github.com/ORIGINAL_REPO/orm-benchmark-reproducibility.git

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Install development dependencies (if available)
pip install -r requirements-dev.txt

# Start databases
docker-compose up -d

# Run tests
python scripts/test_connections.py
```

## 📞 Getting Help

- **Questions**: Open an issue with the "question" label
- **Discussions**: Use GitHub Discussions (if enabled)
- **Email**: Contact maintainers (see README.md)

## 📜 License

By contributing, you agree that your contributions will be licensed under the same license as the project (see LICENSE file).

## 🙏 Recognition

Contributors will be:
- Listed in the project's contributors
- Mentioned in release notes for significant contributions
- Credited in academic papers using this work (if applicable)

Thank you for contributing! 🎉
