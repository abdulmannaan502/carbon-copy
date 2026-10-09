"""Load the synthetic demo dataset into the database.

    python -m app.db.seed            # default seed (20261008)
    python -m app.db.seed --seed 7   # any other seed

Idempotent: existing demo data is deleted and the full dataset is re-inserted in
a single transaction, so a run either fully succeeds or leaves the old data intact.
Synthetic demonstration data — not for clinical use.
"""

import argparse
import time

from sqlalchemy import func, insert, select
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.synthetic import DEMO_REQUEST_CODE, SEED, TABLE_ORDER, generate_dataset


# Operational records, not synthetic dataset content: they reference donors, patients and requests by
# public code, so they stay valid when the dataset is regenerated and are never wiped by a reseed.
PRESERVED_TABLES = frozenset({"notifications", "test_recipients"})


def clear_dataset(session: Session) -> None:
    """Delete every row of every dataset table, children before parents."""
    for table in reversed(Base.metadata.sorted_tables):
        if table.name not in PRESERVED_TABLES:
            session.execute(table.delete())


def table_counts(session: Session) -> dict[str, int]:
    tables = Base.metadata.tables
    return {name: session.scalar(select(func.count()).select_from(tables[name])) or 0 for name in TABLE_ORDER}


def seed_database(session: Session, seed: int = SEED) -> dict[str, int]:
    """Replace all data with the dataset for `seed` and return row counts per table."""
    import app.models  # noqa: F401  -- ensure every table is registered

    dataset = generate_dataset(seed)
    tables = Base.metadata.tables
    try:
        clear_dataset(session)
        for name in TABLE_ORDER:
            if dataset[name]:
                session.execute(insert(tables[name]), dataset[name])
        session.commit()
    except Exception:
        session.rollback()
        raise
    return table_counts(session)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Seed Carbon Copy with synthetic demonstration data.")
    parser.add_argument("--seed", type=int, default=SEED, help=f"random seed (default {SEED})")
    args = parser.parse_args(argv)

    from app.core.config import get_settings
    from app.db.session import SessionLocal, init_db

    init_db()
    started = time.perf_counter()
    with SessionLocal() as session:
        counts = seed_database(session, args.seed)

    print(f"Seeded {get_settings().database_url} with seed {args.seed} in {time.perf_counter() - started:.1f}s")
    for name, count in counts.items():
        print(f"  {name:<22} {count:>6,}")
    print(f"Demo scenario: {DEMO_REQUEST_CODE}")
    print("Synthetic demonstration data - not for clinical use.")


if __name__ == "__main__":
    main()
