# How portable is ORM query performance?

Clean source and public measurements for **How Portable Is ORM Query Performance?
Evidence from Four Database Systems**, aligned with the manuscript revision of
9 September 2026.

The source supports Django and SQLAlchemy on four database systems. The retained
measurements cover **PostgreSQL, MySQL, Oracle and Commercial System A** at scale
factor 1. All **432 planned cells** are included: **336 measured analytical
comparisons**, 12 timeouts, four inexpressible cells and **80 measured transactional
comparisons**. All measurement values and full four-system results are retained.
Commercial System A uses the identifier `commercial_a` in the data and analysis.

## Download or clone

Download the ZIP and SHA-256 checksum from the
[v1.1.0 release](https://github.com/mahmoodnasr/orm-overhead-artifact/releases/tag/v1.1.0),
or clone the repository and check out `v1.1.0` for the same fixed version.
See [docs/PACKAGING.md](docs/PACKAGING.md) for archive construction and verification.

## Verify and reproduce

Python 3.11 or 3.12 can check the files and dataset without installing packages:

```sh
python3 review.py verify
```

For the offline analysis, use Python 3.12 in an isolated environment:

```sh
python3.12 -m venv .venv-analysis
. .venv-analysis/bin/activate
python -m pip install -r requirements-analysis.txt
python review.py reproduce
```

The command reads only the supplied public CSV files. It writes five tables,
three PDF figures and seven numerical exports under `outputs/`, then checks the
CSV, JSON and LaTeX against the public reference outputs (numeric tolerance
`1e-12`; LaTeX tables must match exactly). PDF byte identity is
not required because renderer metadata can differ. No database is contacted.

The analytical medians round to **1.13% for Django (165 cells)** and **0.67% for
SQLAlchemy (171 cells)**. Transactional median overheads are **90.46%** and
**69.18%**, respectively (40 cells each). These are the full four-system estimates.
The fourth system is labeled “Commercial System A” in the tables and figures.

## What to read

| Path | Purpose |
|---|---|
| [REPRODUCE.md](REPRODUCE.md) | Offline analysis, tests and optional new database measurements |
| [MANIFEST.md](MANIFEST.md) | Included measurements, naming and provenance |
| [docs/PROTOCOL.md](docs/PROTOCOL.md) | Estimands, execution protocols and scientific limits |
| [docs/DATA_DICTIONARY.md](docs/DATA_DICTIONARY.md) | File layout, columns and units |
| [docs/ENVIRONMENT.md](docs/ENVIRONMENT.md) | Recorded campaign environment and separate dependency sets |
| `django_app/`, `sqlalchemy_app/` | Query implementations, SQL baselines and models |
| `scripts/1-setup/`, `scripts/2-benchmark/` | Dataset preparation and timing harnesses |
| `results/sf1/` | The public coverage grid and 24 measurement CSVs |
| `analysis/` | Full four-system analysis and reference outputs |
| `tests/` | Source, pairing, integrity and completeness checks |
| `MANIFEST.json`, `PUBLIC_INPUTS.json` | File checksums and input preservation checks |

Reproducing calculations does not prove whole-result equivalence for every
historical timing. Source versions were not recorded on individual measurements,
and the historical validator has known limitations. See `docs/PROTOCOL.md`.

## Development

```sh
python -m pip install -r requirements-dev.txt
python -m pytest
ruff check .
ruff format --check .
```

These checks are also run by GitHub Actions. Installing the database benchmark
runtime is a separate step (`requirements.txt`, Python 3.12); database services
and native driver libraries are not bundled.

The original [analysis plan](ANALYSIS_PLAN.md) and
[correction register](docs/CORRECTIONS.md) remain as historical methodological
evidence. Their older commands and manuscript descriptions are superseded by
this README and `REPRODUCE.md`. Earlier release snapshots remain available in Git
and on the releases page.

Project code retains its [MIT license](LICENSE). See
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) and [CITATION.cff](CITATION.cff).
The manuscript is not presented as a published journal article.
