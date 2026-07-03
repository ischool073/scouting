# Scouting

Small utilities for tracking Scout badge and requirement progress.

## Contents

- `badge_tracker.py` — helper functions for computing progress toward a badge.
- `test_badge_tracker.py` — unit tests for the tracker.

## Usage

```python
from badge_tracker import percent_complete

percent_complete(3, 5)  # 60.0
```

## Running tests

```bash
python -m unittest test_badge_tracker.py
```

## scouting_reports: automated football scouting reports

Phase 1 of a system that builds player scouting reports from free data sources
(FBref/Understat via `soccerdata`, Transfermarkt via the `dcaribou/transfermarkt-datasets`
bulk dataset), currently covering the Premier League end-to-end. See
[`.claude/plans/fluttering-chasing-minsky.md`](../../.claude/plans/fluttering-chasing-minsky.md)
in this checkout for the full design, or ask about it in-session -- the short version:

- **Working today:** FBref + Understat + Transfermarkt ingestion, cross-source player identity
  resolution (exact/fuzzy matching with a human review queue), percentile-based deterministic
  report generation (no free-form LLM narrative -- every sentence traces back to a real stat).
- **Known gap:** 2nd/3rd tier league coverage (Championship, League One, etc.) is not yet
  working. `fbrefdata`'s claimed tier-2 support and a custom `soccerdata` league config both
  failed against real requests, and the Transfermarkt bulk dataset turned out to only include
  one top-flight competition per country. Needs a follow-up decision (build a live tier-2/3
  scraper, or find another source) before Phase 1's original tier-2/3 scope is met.

### Setup

```bash
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
python -m scouting_reports.cli init
```

You'll also need the Transfermarkt bulk dataset (~200MB, not checked into git):

```bash
curl -L -o data/transfermarkt_bulk/transfermarkt-datasets.duckdb \
    https://pub-e682421888d945d684bcae8890b0ec20.r2.dev/data/transfermarkt-datasets.duckdb
```

### Usage

```bash
python -m scouting_reports.cli ingest --competition ENG1 --season 2024-2025 --source all
```

```python
from scouting_reports.db.connection import get_connection
from scouting_reports.reports.generator import generate_report

conn = get_connection()
player = conn.execute("SELECT player_id FROM player WHERE canonical_name = 'Mohamed Salah'").fetchone()
print(generate_report(conn, player["player_id"], "ENG1", "2024-2025"))
```

### Tests

```bash
.venv\Scripts\python -m pytest tests/unit -v
```
