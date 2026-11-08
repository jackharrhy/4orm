#!/usr/bin/env python3
"""Deliver pending enrollment events once; 409 needs operator reconciliation."""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select

from app.db import engine
from app.enrollment_completion import deliver
from app.schema import enrollment_completions

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--limit", type=int, default=100, choices=range(1, 1001))
args = parser.parse_args()
with engine.connect() as conn:
    pending = (
        conn.execute(
            select(enrollment_completions.c.request_id)
            .where(
                enrollment_completions.c.delivered_at.is_(None),
                enrollment_completions.c.last_status.is_distinct_from(409),
            )
            .limit(args.limit)
        )
        .scalars()
        .all()
    )
statuses = [deliver(engine, request_id) for request_id in pending]
print(
    f"Attempted {len(statuses)}; acknowledged {statuses.count(200)}; "
    f"needs reconciliation {statuses.count(409)}; "
    f"other pending {sum(s not in {200, 409} for s in statuses)}"
)
raise SystemExit(0 if all(status == 200 for status in statuses) else 1)
