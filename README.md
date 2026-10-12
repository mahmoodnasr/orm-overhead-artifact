# How portable is ORM query performance?

Code, measurements and analysis for **How Portable Is ORM Query Performance?
Evidence from Four Database Systems**, aligned with the manuscript revision of
October 2026.

The study measures Django and SQLAlchemy against handwritten SQL on
PostgreSQL, MySQL, Oracle and Commercial System A, using TPC-H-derived
analytical queries and TPC-C-derived transactions. The fourth system is
anonymous because the licence of its software restricts publishing
vendor-attributed benchmark results; its identifier is `commercial_a`.

## Two datasets

| Dataset | Path | Role |
|---|---|---|
| Revision campaign rc20261008, 8–11 October 2026 | [`campaign/`](campaign/README.md) | The manuscript's results: the SF1 grid measured again under a frozen protocol, with transactions, SF2, a separate client, a second server, a four-path decomposition and censored-cell validation |
| September 2026 SF1 measurements | [`results/sf1/`](results/sf1/README.md) | The data of the first submission, kept unchanged as the comparison the manuscript reports |

From the campaign (`campaign/rc20261008/analysis/`):

| | Cells | Median overhead | 95 % interval |
|---|---:|---:|---|
| Analytical, SF1, all systems | 332 | +0.85 % | 0.51–1.60 |
| Django | 165 | +1.35 % | 0.53–4.41 |
| SQLAlchemy | 167 | +0.60 % | 0.31–1.39 |
| Transactions, all systems | 80 | +104.7 % | — |

Each framework is compared with its own handwritten baseline, so these rows
do not rank the frameworks. The large gaps, the transaction results and every
sensitivity row are in [`campaign/README.md`](campaign/README.md).

## Download or clone

Download the ZIP and its SHA-256 checksum from the
[v2.0.0 release](https://github.com/mahmoodnasr/orm-overhead-artifact/releases/tag/v2.0.0),
or clone the repository and check out `v2.0.0`. See
[docs/PACKAGING.md](docs/PACKAGING.md) for how the archive is built and checked.

## Verify and reproduce

Python 3.11 or 3.12 checks every file and both datasets without installing
anything:

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

`reproduce` reads only released files and writes to `outputs/`. For the
campaign it reruns the campaign's own analysis scripts on its per-call
records, rebuilds all 23 reference outputs, and re-checks every accepted
ORM/SQL pair of phases A, D and E against the full results stored in the
records. For the September data it rebuilds five tables, three figures and
seven numerical exports. Numeric comparisons allow `1e-12` for platform math
libraries; a value printed with fixed decimals may also differ by one unit
in its last place. No database is contacted.

## What to read

| Path | Purpose |
|---|---|
| [campaign/README.md](campaign/README.md) | The campaign: phases, layout, which run counts, limitations, what was changed for release |
| [REPRODUCE.md](REPRODUCE.md) | Offline reproduction, tests, and new database measurements |
| [MANIFEST.md](MANIFEST.md) | Release scope, naming and provenance |
| [docs/PROTOCOL.md](docs/PROTOCOL.md) | Estimands and execution protocols of both datasets |
| [docs/DATA_DICTIONARY.md](docs/DATA_DICTIONARY.md) | File layout, columns and units |
| [docs/ENVIRONMENT.md](docs/ENVIRONMENT.md) | Recorded environments and dependency sets |
| [docs/CORRECTIONS.md](docs/CORRECTIONS.md) | The defect register of the study's earlier versions |
| `django_app/`, `sqlalchemy_app/` | Query implementations, handwritten baselines and models |
| `scripts/` | Dataset preparation and the September timing harness |
| `analysis/` | Offline analysis: the September rebuild and the campaign checks |
| `tests/` | Source, pairing, integrity and completeness checks |
| `MANIFEST.json`, `campaign/SHA256SUMS`, `PUBLIC_INPUTS.json` | Checksums and input preservation records |

The maintained source in `django_app/` and `sqlalchemy_app/` executes as the
campaign's measured source in `campaign/source/`; `tests/test_campaign.py`
checks it statement for statement.

## Development

```sh
python -m pip install -r requirements-dev.txt
python -m pytest
ruff check .
ruff format --check .
```

GitHub Actions runs these checks and `review.py reproduce`. The database
benchmark runtime is a separate installation (`requirements.txt`, Python
3.12); database services and native driver libraries are not bundled.

The original [analysis plan](ANALYSIS_PLAN.md) and the
[correction register](docs/CORRECTIONS.md) are historical methodological
evidence; their older commands are superseded by this README and
`REPRODUCE.md`. Earlier release snapshots remain available in Git and on the
releases page.

Project code is under the [MIT license](LICENSE). See
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) and [CITATION.cff](CITATION.cff).
The manuscript is under review and is not presented as a published article.
