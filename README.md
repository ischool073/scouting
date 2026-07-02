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
